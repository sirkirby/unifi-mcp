"""GraphQL error formatter — projects Python exceptions into extensions.code."""

from graphql import GraphQLError
from unifi_api.graphql.errors import format_graphql_error
from unifi_api.services.access_event_key import InvalidAccessEventCursor
from unifi_api.services.controllers import ControllerNotFound
from unifi_api.services.pagination import InvalidCursor


def test_format_unauthenticated() -> None:
    err = GraphQLError("missing bearer token")
    err.original_error = PermissionError("UNAUTHENTICATED:missing bearer token")
    formatted = format_graphql_error(err)
    assert formatted["message"] == "missing bearer token"
    assert formatted["extensions"]["code"] == "UNAUTHENTICATED"


def test_format_forbidden_via_permission_error() -> None:
    err = GraphQLError("insufficient scope")
    err.original_error = PermissionError("FORBIDDEN:insufficient scope")
    formatted = format_graphql_error(err)
    assert formatted["extensions"]["code"] == "FORBIDDEN"


def test_format_forbidden_via_strawberry_permission_denial() -> None:
    """Strawberry permission denials raise a GraphQLError with no original_error
    and a message containing 'scope'. Classify as FORBIDDEN.
    """
    err = GraphQLError("insufficient scope")
    err.original_error = None
    formatted = format_graphql_error(err)
    assert formatted["extensions"]["code"] == "FORBIDDEN"


def test_format_not_found_from_controller_not_found() -> None:
    err = GraphQLError("controller xyz not found")
    err.original_error = ControllerNotFound("xyz")
    formatted = format_graphql_error(err)
    assert formatted["extensions"]["code"] == "NOT_FOUND"


def test_format_invalid_access_event_cursor_as_bad_request() -> None:
    err = GraphQLError("unsupported Access event cursor version: 99")
    err.original_error = InvalidAccessEventCursor("unsupported Access event cursor version: 99")
    formatted = format_graphql_error(err)
    assert formatted["extensions"]["code"] == "BAD_REQUEST"


def test_format_invalid_generic_cursor_as_bad_request() -> None:
    err = GraphQLError("invalid cursor")
    err.original_error = InvalidCursor("invalid cursor")
    formatted = format_graphql_error(err)
    assert formatted["extensions"]["code"] == "BAD_REQUEST"


def test_format_unknown_internal() -> None:
    err = GraphQLError("boom")
    err.original_error = RuntimeError("unexpected")
    formatted = format_graphql_error(err)
    assert formatted["extensions"]["code"] == "INTERNAL"
