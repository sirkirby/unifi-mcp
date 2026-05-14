"""Per-request, in-process cache + Info.context shape for GraphQL resolvers.

The RequestCache lives for one HTTP request only — it dedupes manager calls
within a single GraphQL query. No persistence, no cross-request sharing.
Resolvers reaching the same snapshot share one fetch.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from strawberry.fastapi import BaseContext

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from unifi_api.services.managers import ManagerFactory


class RequestCache:
    """Memoizes async fetches by key for the lifetime of one request.

    Concurrency-safe: two coroutines requesting the same key share a single
    in-flight Future, so concurrent resolvers don't double-fetch.
    """

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}
        self._inflight: dict[str, asyncio.Future] = {}

    async def get_or_fetch(self, key: str, fetch: Callable[[], Awaitable[Any]]) -> Any:
        if key in self._values:
            return self._values[key]
        if key in self._inflight:
            return await self._inflight[key]
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._inflight[key] = fut
        try:
            value = await fetch()
            self._values[key] = value
            fut.set_result(value)
            return value
        except Exception as exc:
            fut.set_exception(exc)
            raise
        finally:
            self._inflight.pop(key, None)


class GraphQLContext(BaseContext):
    """Shape attached to Strawberry's Info.context for every resolver call.

    Inherits Strawberry's `BaseContext` so the FastAPI router accepts this as
    a non-dict custom context (Strawberry rejects arbitrary objects otherwise).
    """

    def __init__(
        self,
        *,
        cache: RequestCache | None = None,
        sessionmaker: "async_sessionmaker[AsyncSession] | None" = None,
        manager_factory: "ManagerFactory | None" = None,
        api_key_id: str | None = None,
        api_key_scopes: str | None = None,
        api_key_prefix: str | None = None,
    ) -> None:
        super().__init__()
        self.cache = cache if cache is not None else RequestCache()
        self.sessionmaker = sessionmaker
        self.manager_factory = manager_factory
        self.api_key_id = api_key_id
        self.api_key_scopes = api_key_scopes
        self.api_key_prefix = api_key_prefix
