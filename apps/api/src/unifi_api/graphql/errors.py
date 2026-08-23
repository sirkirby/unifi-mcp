"""Project Python exceptions raised inside resolvers into the GraphQL standard
error shape with extensions.code values.

This is wired into the Strawberry router as `error_formatter=...`. Strawberry
calls it for every error in the response.
"""

from __future__ import annotations

from typing import Any

from graphql import GraphQLError

from unifi_api.services.access_event_key import InvalidAccessEventCursor
from unifi_api.services.controllers import ControllerNotFound
from unifi_api.services.pagination import InvalidCursor


def _classify(error: GraphQLError) -> str:
    orig = error.original_error
    if isinstance(orig, ControllerNotFound):
        return "NOT_FOUND"
    if isinstance(orig, (InvalidAccessEventCursor, InvalidCursor)):
        return "BAD_REQUEST"
    if isinstance(orig, PermissionError):
        msg = str(orig)
        if msg.startswith("UNAUTHENTICATED:"):
            return "UNAUTHENTICATED"
        if msg.startswith("FORBIDDEN:"):
            return "FORBIDDEN"
        return "FORBIDDEN"
    # Strawberry permission denials surface as either a bare GraphQLError with
    # original_error=None, or a StrawberryGraphQLError wrapped as the original.
    # In both cases the message mirrors the permission class's `message` attr,
    # so we classify as FORBIDDEN whenever the message mentions "scope".
    if "scope" in error.message.lower():
        return "FORBIDDEN"
    if orig is None:
        return "INTERNAL"
    return "INTERNAL"


def format_graphql_error(error: GraphQLError) -> dict[str, Any]:
    """Format a GraphQLError dict to send to the client.

    Strips internal trace details; surfaces only message + extensions.code.
    """
    code = _classify(error)
    return {
        "message": error.message,
        "path": list(error.path) if error.path else None,
        "extensions": {"code": code},
    }
