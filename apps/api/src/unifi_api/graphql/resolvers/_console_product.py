"""GraphQL read plumbing shared by the console products.

Each field calls the same core manager method as the REST route and the
action, through :func:`unifi_api.services.console_product.read`, so a failure
maps to the same fixed text; here it surfaces as a GraphQL error code. Each
read is cached for the request by manager method and arguments.
"""

from __future__ import annotations

from typing import Any

from strawberry.types import Info

from unifi_api.graphql.context import GraphQLContext
from unifi_api.services.console_product import ConsoleProduct, map_error, read
from unifi_api.services.controllers import get_controller
from unifi_api.services.incident_evidence import require_product


class ConsoleQueries:
    """The ``read`` and ``project`` helpers of one console product's GraphQL fields."""

    def __init__(self, product: ConsoleProduct) -> None:
        self.product = product

    async def read(
        self,
        info: Info,
        controller: str,
        *,
        manager_attr: str,
        method: str,
        operation: str,
        args: tuple[Any, ...] = (),
        **kwargs: Any,
    ) -> Any:
        ctx: GraphQLContext = info.context
        product = self.product
        async with ctx.sessionmaker() as session:
            row = await get_controller(session, str(controller))
        require_product(row, product.key)
        key = f"{product.key}/{controller}/{manager_attr}.{method}/{args!r}/{sorted(kwargs.items())!r}"

        async def _fetch() -> Any:
            return await read(
                product,
                sessionmaker=ctx.sessionmaker,
                factory=ctx.manager_factory,
                controller_id=str(controller),
                manager_attr=manager_attr,
                method=method,
                operation=operation,
                args=args,
                kwargs=kwargs,
            )

        return await ctx.cache.get_or_fetch(key, _fetch)

    def project(self, info: Info, type_class: type, obj: Any, operation: str) -> Any:
        """Project one result; a result it cannot project maps like any other read failure."""
        ctx: GraphQLContext = info.context
        try:
            return type_class.from_manager_output(obj, redact_sensitive=ctx.redact_sensitive_fields)
        except Exception as exc:
            raise map_error(self.product, exc, operation) from None
