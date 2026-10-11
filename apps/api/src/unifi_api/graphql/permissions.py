"""Strawberry permission classes mirroring the REST scope dependencies.

`IsRead` allows read or admin (matches REST `require_scope(Scope.READ)`).
`IsAdmin` allows admin only. A write-only key cannot read GraphQL fields,
matching REST semantics — there is no write→read implication.
On denial, Strawberry raises an error caught by the error formatter and
projected into `extensions.code = "FORBIDDEN"`.
"""

from __future__ import annotations

from typing import Any

from graphql import GraphQLError
from strawberry.permission import BasePermission

from unifi_api.auth.scopes import Scope, parse_scopes, scope_allows
from unifi_api.graphql.context import GraphQLContext


def _scopes_from_info(info: Any) -> frozenset[Scope]:
    ctx: GraphQLContext = info.context  # type: ignore[assignment]
    return parse_scopes(ctx.api_key_scopes or "")


class ScopeDenied(GraphQLError):
    """Raised by the permission classes on denial; the error formatter classifies by this type."""


class IsRead(BasePermission):
    message = "insufficient scope"
    error_class = ScopeDenied

    def has_permission(self, source: Any, info: Any, **kwargs: Any) -> bool:
        return scope_allows(_scopes_from_info(info), Scope.READ)


class IsAdmin(BasePermission):
    message = "insufficient scope"
    error_class = ScopeDenied

    def has_permission(self, source: Any, info: Any, **kwargs: Any) -> bool:
        return scope_allows(_scopes_from_info(info), Scope.ADMIN)
