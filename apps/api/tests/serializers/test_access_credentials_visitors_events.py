"""Access credentials + visitors + events serializer tests
(Phase 4A PR3 Cluster 2).

Manager methods covered:
  - ``CredentialManager.create_credential`` / ``revoke_credential`` -> preview dicts
  - ``VisitorManager.list_visitors`` -> list[dict]
  - ``VisitorManager.get_visitor`` -> dict
  - ``VisitorManager.create_visitor`` / ``delete_visitor`` -> preview dicts
  - ``EventManager.list_events`` -> list[dict]  (event log)
  - ``EventManager.get_event`` -> dict (event detail)
  - ``EventManager.get_recent_from_buffer`` -> list[dict]  (event log)
  - ``EventManager.get_activity_summary`` -> dict (histogram payload)

The ``access_subscribe_events`` tool has no AST-discoverable manager call
(it composes a dict from ``event_manager.buffer_size``); the serializer
still needs to be registered for coverage. Phase 4B PR3 Task 14 migrates
this to ``AccessStreamSubscriptionSerializer`` (STREAM kind) returning
``{stream_url, transport: "sse", buffer_size, instructions}``.
"""

from unifi_api.serializers._registry import (
    discover_serializers,
    serializer_registry_singleton,
)


def _registry():
    discover_serializers(manifest_tool_names=set())
    return serializer_registry_singleton()


# ---- credentials (mutation acks) ----


def test_credential_mutation_ack_create() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("access_create_credential")
    sample = {
        "credential_type": "nfc",
        "credential_data": {"user_id": "user-1", "token": "abc123"},
        "proposed_changes": {"action": "create", "type": "nfc", "user_id": "user-1"},
    }
    out = s.serialize_action(sample, tool_name="access_create_credential")
    assert out["success"] is True
    assert out["data"]["credential_type"] == "nfc"
    assert out["data"]["proposed_changes"]["action"] == "create"
    assert out["render_hint"]["kind"] == "detail"


def test_credential_mutation_ack_revoke() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("access_revoke_credential")
    sample = {
        "credential_id": "cred-001",
        "current_state": {"id": "cred-001", "user_id": "user-1", "type": "nfc"},
        "proposed_changes": {"action": "revoke"},
    }
    out = s.serialize_action(sample, tool_name="access_revoke_credential")
    assert out["success"] is True
    assert out["data"]["credential_id"] == "cred-001"
    assert out["render_hint"]["kind"] == "detail"


def test_access_credential_projection_redacts_token_and_pin() -> None:
    from unifi_api.graphql.types.access.credentials import Credential
    from unifi_core.redaction import REDACTED

    out = Credential.from_manager_output(
        {"id": "cred1", "type": "pin", "token": "nfc-token", "pin_code": "123456"}
    ).to_dict()

    assert out["token"] == REDACTED
    assert out["pin_code"] == REDACTED


# ---- visitors ----


def test_visitor_list_serializer_shape() -> None:
    """Phase 6 PR4 Task B — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.access.visitors import Visitor

    sample = {
        "id": "vis-001",
        "name": "Jane Doe",
        "host_user_id": "user-1",
        "valid_from": "2026-04-29T08:00:00Z",
        "valid_until": "2026-04-29T18:00:00Z",
        "status": "active",
        "credential_count": 1,
    }
    out = Visitor.from_manager_output(sample).to_dict()
    assert out["id"] == "vis-001"
    assert out["name"] == "Jane Doe"
    assert out["status"] == "active"
    assert out["credential_count"] == 1
    assert Visitor.render_hint("list")["kind"] == "list"


def test_visitor_detail_serializer_shape() -> None:
    """Phase 6 PR4 Task B — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.access.visitors import Visitor

    sample = {
        "id": "vis-002",
        "name": "John Roe",
        "host_user_id": "user-2",
        "valid_from": "2026-04-29T09:00:00Z",
        "valid_until": "2026-04-29T17:00:00Z",
        "status": "scheduled",
        "credential_count": 0,
    }
    out = Visitor.from_manager_output(sample).to_dict()
    assert out["id"] == "vis-002"
    assert out["host_user_id"] == "user-2"
    assert Visitor.render_hint("detail")["kind"] == "detail"


def test_visitor_mutation_ack_create() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("access_create_visitor")
    sample = {
        "visitor_data": {
            "name": "Alice",
            "access_start": "2026-04-29T08:00:00Z",
            "access_end": "2026-04-29T18:00:00Z",
        },
        "proposed_changes": {"action": "create", "name": "Alice"},
    }
    out = s.serialize_action(sample, tool_name="access_create_visitor")
    assert out["success"] is True
    assert out["data"]["visitor_data"]["name"] == "Alice"
    assert out["data"]["proposed_changes"]["action"] == "create"
    assert out["render_hint"]["kind"] == "detail"


def test_visitor_mutation_ack_delete() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("access_delete_visitor")
    sample = {
        "visitor_id": "vis-001",
        "visitor_name": "Jane Doe",
        "current_state": {"id": "vis-001", "name": "Jane Doe"},
        "proposed_changes": {"action": "delete"},
    }
    out = s.serialize_action(sample, tool_name="access_delete_visitor")
    assert out["success"] is True
    assert out["data"]["visitor_id"] == "vis-001"
    assert out["render_hint"]["kind"] == "detail"


# ---- events ----


def test_access_event_log_list_shape() -> None:
    """Phase 6 PR4 Task B — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.access.events import Event

    sample = {
        "id": "evt-1",
        "type": "access_granted",
        "timestamp": "2026-04-29T08:00:00Z",
        "door_id": "door-1",
        "user_id": "user-1",
        "credential_id": "cred-001",
        "result": "granted",
    }
    out = Event.from_manager_output(sample).to_dict()
    assert out["id"] == "evt-1"
    assert out["result"] == "granted"
    assert Event.render_hint("list")["kind"] == "list"


def test_access_recent_events_shape() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("access_recent_events")
    sample = [
        {
            "id": "evt-2",
            "type": "access_denied",
            "timestamp": "2026-04-29T08:01:00Z",
            "door_id": "door-1",
            "user_id": "user-2",
            "credential_id": None,
            "result": "denied",
        }
    ]
    out = s.serialize_action(sample, tool_name="access_recent_events")
    assert out["success"] is True
    assert out["data"][0]["id"] == "evt-2"
    assert out["data"][0]["result"] == "denied"
    assert out["render_hint"]["kind"] == "event_log"


def test_access_event_detail_shape() -> None:
    """Phase 6 PR4 Task B — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.access.events import Event

    sample = {
        "id": "evt-3",
        "type": "door_open",
        "timestamp": "2026-04-29T08:02:00Z",
        "door_id": "door-2",
        "user_id": "user-3",
        "credential_id": "cred-002",
        "result": "granted",
    }
    out = Event.from_manager_output(sample).to_dict()
    assert out["id"] == "evt-3"
    assert out["door_id"] == "door-2"
    assert Event.render_hint("detail")["kind"] == "detail"


def test_activity_summary_shape() -> None:
    """Phase 6 PR4 Task B — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.access.events import ActivitySummary

    sample = {
        "period_start": "2026-04-22T00:00:00Z",
        "period_end": "2026-04-29T00:00:00Z",
        "total_events": 142,
        "granted_count": 130,
        "denied_count": 12,
        "top_users": [{"user_id": "user-1", "count": 47}],
    }
    out = ActivitySummary.from_manager_output(sample).to_dict()
    assert out["total_events"] == 142
    assert out["granted_count"] == 130
    assert out["top_users"][0]["user_id"] == "user-1"
    assert ActivitySummary.render_hint("detail")["kind"] == "detail"


def test_subscribe_events_shape() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("access_subscribe_events")
    sample = {
        "resource_uri": "access://events/stream",
        "summary_uri": "access://events/stream/summary",
        "instructions": "Read the resource at ...",
        "buffer_size": 100,
    }
    out = s.serialize_action(sample, tool_name="access_subscribe_events")
    assert out["success"] is True
    assert out["data"]["stream_url"] == "/v1/streams/access/events"
    assert out["data"]["transport"] == "sse"
    assert out["data"]["buffer_size"] == 100
    assert out["data"]["instructions"] == "Read the resource at ..."
    assert out["render_hint"]["kind"] == "stream"


def test_subscribe_events_non_dict_input() -> None:
    """Non-dict inputs still surface the stream metadata."""
    reg = _registry()
    s = reg.serializer_for_tool("access_subscribe_events")
    out = s.serialize_action("sub-xyz-789", tool_name="access_subscribe_events")
    assert out["success"] is True
    assert out["data"]["stream_url"] == "/v1/streams/access/events"
    assert out["data"]["transport"] == "sse"
    assert out["render_hint"]["kind"] == "stream"
