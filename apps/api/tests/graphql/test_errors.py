"""GraphQL error formatter — projects Python exceptions into extensions.code."""

from graphql import GraphQLError
from unifi_api.graphql.errors import format_graphql_error
from unifi_api.graphql.permissions import ScopeDenied
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
    """The permission classes raise ScopeDenied; the formatter classifies by that type."""
    err = GraphQLError("insufficient scope", path=["network", "incidentEvidence"])
    err.original_error = ScopeDenied("insufficient scope")
    formatted = format_graphql_error(err)
    assert formatted["extensions"]["code"] == "FORBIDDEN"


def test_a_message_mentioning_scope_never_decides_the_category() -> None:
    """Caller input can put any text in a message; only exception types classify."""
    coercion = GraphQLError("Variable '$maxCalls' got invalid value 'private-scope-sentinel'; Int cannot represent")
    assert format_graphql_error(coercion)["extensions"]["code"] == "BAD_REQUEST"
    resolver = GraphQLError("private-scope-sentinel", path=["network", "incidentEvidence"])
    resolver.original_error = RuntimeError("private-scope-sentinel")
    assert format_graphql_error(resolver)["extensions"]["code"] == "INTERNAL"


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


def test_argument_coercion_errors_are_bad_requests_without_the_rejected_value() -> None:
    coercion = GraphQLError("Int cannot represent non-integer value: 'operator-value'")
    variable = GraphQLError(
        "Variable '$maxCalls' got invalid value 'operator-value'; "
        "Int cannot represent non-integer value: 'operator-value'",
        original_error=GraphQLError("Int cannot represent non-integer value: 'operator-value'"),
    )
    for error in (coercion, variable):
        formatted = format_graphql_error(error)
        assert formatted["extensions"]["code"] == "BAD_REQUEST"
        assert "operator-value" not in formatted["message"]
    assert format_graphql_error(variable)["message"] == "Variable '$maxCalls' has an invalid value."
