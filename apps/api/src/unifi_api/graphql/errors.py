"""Project Python exceptions raised inside resolvers into the GraphQL standard
error shape with extensions.code values.

This is wired into the Strawberry router as `error_formatter=...`. Strawberry
calls it for every error in the response.
"""

from __future__ import annotations

import re
from typing import Any

from graphql import GraphQLError

from unifi_api.services.access_event_key import InvalidAccessEventCursor, InvalidAccessEventTopic
from unifi_api.services.controllers import ControllerNotFound
from unifi_api.services.incident_evidence import IncidentRequestError
from unifi_api.services.pagination import InvalidCursor

# graphql-core quotes a rejected argument or variable value in these messages.
_VALUE_ECHO = re.compile(
    r"cannot represent|got invalid value|expected value of type|does not exist in|expected type", re.IGNORECASE
)
_VARIABLE = re.compile(r"^Variable '(\$\w+)'")


def is_request_error(error: GraphQLError) -> bool:
    """Parse, validation and argument-coercion errors: raised before any resolver ran.

    They have no path, and wrap nothing but graphql-core's own coercion error.
    """
    return not error.path and (error.original_error is None or isinstance(error.original_error, GraphQLError))


def safe_message(error: GraphQLError) -> str:
    """The error's message, without the rejected value an argument-coercion error quotes."""
    if not is_request_error(error) or not _VALUE_ECHO.search(error.message):
        return error.message
    variable = _VARIABLE.match(error.message)
    if variable:
        return f"Variable '{variable.group(1)}' has an invalid value."
    return "An argument has an invalid value."


def _classify(error: GraphQLError) -> str:
    orig = error.original_error
    if isinstance(orig, ControllerNotFound):
        return "NOT_FOUND"
    if isinstance(orig, (InvalidAccessEventCursor, InvalidAccessEventTopic, InvalidCursor, IncidentRequestError)):
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
    if is_request_error(error):
        return "BAD_REQUEST"
    return "INTERNAL"


def format_graphql_error(error: GraphQLError) -> dict[str, Any]:
    """Format a GraphQLError dict to send to the client.

    Strips internal trace details; surfaces only message + extensions.code.
    """
    code = _classify(error)
    return {
        "message": safe_message(error),
        "path": list(error.path) if error.path else None,
        "extensions": {"code": code},
    }
