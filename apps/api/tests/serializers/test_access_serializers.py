"""Access serializer unit tests — one fixture per resource.

Access managers in unifi-core return plain dicts (proxy path returns the
raw location/user/credential dicts; API-client path returns flattened dicts).
Each fixture below mirrors the proxy-path shape, since that's the richer one
the catalog will most often see.
"""

from unifi_api.serializers._registry import (
    discover_serializers,
    serializer_registry_singleton,
)


def _registry():
    """Trigger discovery once for the test module."""
    discover_serializers(manifest_tool_names=set())
    return serializer_registry_singleton()


def test_door_serializer_shape() -> None:
    """Phase 6 PR4 Task A — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.access.doors import Door

    sample = {
        "id": "door1",
        "name": "Front Door",
        "location_type": "door",
        "is_online": True,
        "door_position_status": "close",
        "lock_relay_status": "lock",
        "devices": [{"id": "dev1", "name": "G2 Reader", "online": True}],
        "last_event": {
            "name": "Access Granted",
            "timestamp": "2026-04-29T10:00:00+00:00",
        },
    }
    out = Door.from_manager_output(sample).to_dict()
    assert out["id"] == "door1"
    assert out["name"] == "Front Door"
    assert "location" in out
    assert "is_online" in out
    assert "is_locked" in out
    assert "lock_state" in out
    assert "last_event" in out


def test_user_serializer_shape() -> None:
    """Phase 6 PR4 Task A — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.access.users import User

    sample = {
        "unique_id": "user1",
        "first_name": "Ada",
        "last_name": "Lovelace",
        "full_name": "Ada Lovelace",
        "employee_number": "E-1815",
        "status": "ACTIVE",
        "roles": [{"name": "Super Admin", "system_key": "super_administrator"}],
        "create_time": 1767225600,
    }
    out = User.from_manager_output(sample).to_dict()
    assert out["id"] == "user1"
    assert out["name"] == "Ada Lovelace"
    assert out["employee_id"] == "E-1815"
    assert out["status"] == "ACTIVE"
    assert out["role"] == "Super Admin"
    assert out["created_at"] == "2026-01-01T00:00:00Z"
    # A row without full_name stitches the name from its parts.
    assert User.from_manager_output({**sample, "full_name": ""}).to_dict()["name"] == "Ada Lovelace"


def test_credential_serializer_shape() -> None:
    """Phase 6 PR4 Task B — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.access.credentials import Credential

    sample = {
        "id": "cred1",
        "user_id": "user1",
        "type": "nfc_card",
        "status": "active",
        "expiry": "2027-01-01T00:00:00+00:00",
        "last_used": "2026-04-28T18:30:00+00:00",
    }
    out = Credential.from_manager_output(sample).to_dict()
    assert out["id"] == "cred1"
    assert out["user_id"] == "user1"
    assert out["type"] == "nfc_card"
    assert out["status"] == "active"
    assert out["expiry"] == "2027-01-01T00:00:00+00:00"
    assert out["last_used"] == "2026-04-28T18:30:00+00:00"
