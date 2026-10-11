"""Strawberry schema for unifi-api. Code-first; SDL exported to schema.graphql.

PR1 ships only the smoke `health` field. PR2/3/4 add product-namespaced
NetworkQuery / ProtectQuery / AccessQuery roots.
"""

from __future__ import annotations

import logging
import sys

import strawberry
from graphql import GraphQLError
from strawberry.types import ExecutionContext

from unifi_api._version import __version__ as _api_version
from unifi_api.graphql.errors import is_request_error, safe_message
from unifi_api.graphql.permissions import IsRead
from unifi_api.graphql.resolvers.access import AccessQuery
from unifi_api.graphql.resolvers.network import NetworkQuery
from unifi_api.graphql.resolvers.protect import ProtectQuery


@strawberry.type(description="Service health snapshot — smoke field for the GraphQL endpoint.")
class HealthSnapshot:
    ok: bool
    version: str
    python_version: str


@strawberry.type
class Query:
    @strawberry.field(
        permission_classes=[IsRead],
        description="Liveness probe; mirrors GET /v1/health/ready.",
    )
    def health(self) -> HealthSnapshot:
        return HealthSnapshot(
            ok=True,
            version=_api_version,
            python_version=sys.version.split()[0],
        )

    @strawberry.field(description="Read-only access to UniFi Network resources.")
    def network(self) -> NetworkQuery:
        return NetworkQuery()

    @strawberry.field(description="Read-only access to UniFi Protect resources.")
    def protect(self) -> ProtectQuery:
        return ProtectQuery()

    @strawberry.field(description="Read-only access to UniFi Access resources.")
    def access(self) -> AccessQuery:
        return AccessQuery()


_logger = logging.getLogger("strawberry.execution")


class _Schema(strawberry.Schema):
    """Logs request errors (parse, validation, argument coercion) without the rejected values they quote."""

    def process_errors(self, errors: list[GraphQLError], execution_context: ExecutionContext | None = None) -> None:
        request_errors = [error for error in errors if is_request_error(error)]
        for error in request_errors:
            _logger.info("GraphQL request rejected: %s", safe_message(error))
        super().process_errors([error for error in errors if not is_request_error(error)], execution_context)


schema = _Schema(query=Query)
