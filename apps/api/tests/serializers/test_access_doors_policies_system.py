"""Phase 4A PR3 Cluster 1 — access doors/policies/schedules/devices/system.

Each manager returns plain dicts (or list of dicts). For lock/unlock/reboot
the manager preview returns a dict (current_state + proposed_changes); we
pass that through. The mutation acks coerce bools to ``{"success": bool}``.
"""

from unifi_api.serializers._registry import (
    discover_serializers,
    serializer_registry_singleton,
)


def _registry():
    discover_serializers(manifest_tool_names=set())
    return serializer_registry_singleton()


def test_door_group_serializer_shape() -> None:
    """Phase 6 PR4 Task A — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.access.doors import DoorGroup

    sample = {
        "id": "grp1",
        "name": "Lobby Group",
        "door_ids": ["door1", "door2"],
        "location": "HQ Floor 1",
    }
    out = DoorGroup.from_manager_output(sample).to_dict()
    assert out["id"] == "grp1"
    assert out["name"] == "Lobby Group"
    assert out["door_ids"] == ["door1", "door2"]
    assert out["location"] == "HQ Floor 1"


def test_door_status_serializer_shape() -> None:
    """Phase 6 PR4 Task A — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.access.doors import DoorStatus

    sample = {
        "id": "door1",
        "name": "Front Door",
        "door_position_status": "close",
        "lock_relay_status": "lock",
    }
    out = DoorStatus.from_manager_output(sample).to_dict()
    assert out["door_id"] == "door1"
    assert out["is_locked"] is True
    assert out["lock_state"] == "lock"


def test_policy_serializer_shape() -> None:
    """Phase 6 PR4 Task B — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.access.policies import Policy

    sample = {
        "id": "pol1",
        "name": "Office Hours",
        "schedule_id": "sch1",
        "resources": [{"id": "door1"}, {"id": "door2"}],
        "user_group_ids": ["ug1"],
        "status": "active",
    }
    out = Policy.from_manager_output(sample).to_dict()
    assert out["id"] == "pol1"
    assert out["name"] == "Office Hours"
    assert out["schedule_id"] == "sch1"
    assert "door_ids" in out
    assert "user_group_ids" in out
    assert "enabled" in out


def test_schedule_serializer_shape() -> None:
    """Phase 6 PR4 Task B — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.access.schedules import Schedule

    sample = {
        "id": "sch1",
        "name": "Weekdays 9-5",
        "week_schedule": {"monday": [{"start": "09:00", "end": "17:00"}]},
        "status": "active",
    }
    out = Schedule.from_manager_output(sample).to_dict()
    assert out["id"] == "sch1"
    assert out["name"] == "Weekdays 9-5"
    assert out["weekly_pattern"] == sample["week_schedule"]
    assert out["enabled"] is True


def test_access_device_serializer_shape() -> None:
    """Phase 6 PR4 Task A — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.access.devices import AccessDevice

    sample = {
        "unique_id": "dev1",
        "name": "Front Reader",
        "device_type": "UA-G2",
        "is_online": True,
        "firmware": "2.10.0",
        "_door_name": "Front Door",
    }
    out = AccessDevice.from_manager_output(sample).to_dict()
    assert out["id"] == "dev1"
    assert out["name"] == "Front Reader"
    assert out["type"] == "UA-G2"
    assert out["is_online"] is True
    assert out["firmware_version"] == "2.10.0"
    # location is now a structured AccessLocation object; the proxy-path
    # ``_door_name`` string maps to its ``name`` field.
    assert out["location"] == {
        "unique_id": None,
        "name": "Front Door",
        "up_id": None,
        "location_type": None,
        "full_name": None,
        "level": None,
    }


def test_access_device_serializer_from_typed_core_model() -> None:
    """The device_manager may return a typed unifi-core AccessDevice whose
    ``location`` is an AccessLocation pydantic object (not a dict). The
    Strawberry projection must read that object path, not just dicts."""
    from unifi_api.graphql.types.access.devices import AccessDevice
    from unifi_core.access.models.devices import from_controller

    core = from_controller(
        {
            "id": "dev1",
            "name": "Hub B",
            "type": "UA-Hub",
            "is_online": True,
            "location": {
                "unique_id": "loc-1",
                "name": "Front Door",
                "up_id": "loc-parent",
                "location_type": "door",
                "full_name": "Site - Floor 1 - Front Door",
                "level": 3,
            },
        }
    )
    # core.location is a unifi_core AccessLocation pydantic object, not a dict.
    out = AccessDevice.from_manager_output(core).to_dict()
    assert out["id"] == "dev1"
    assert out["location"] == {
        "unique_id": "loc-1",
        "name": "Front Door",
        "up_id": "loc-parent",
        "location_type": "door",
        "full_name": "Site - Floor 1 - Front Door",
        "level": 3,
    }


def test_access_device_serializer_location_none() -> None:
    """No location and no proxy ``_door_name`` -> to_dict surfaces None (the
    value the REST route returns to callers)."""
    from unifi_api.graphql.types.access.devices import AccessDevice

    out = AccessDevice.from_manager_output({"id": "dev1", "name": "Reader A"}).to_dict()
    assert out["location"] is None


def test_access_system_info_and_health() -> None:
    """Phase 6 PR4 Task B — projections moved to Strawberry types. Same dict
    shape contract as the old serializers; verified via Type.to_dict()."""
    from unifi_api.graphql.types.access.system import (
        AccessHealth,
        AccessSystemInfo,
    )

    info_sample = {
        "name": "Access Application",
        "version": "1.24.0",
        "hostname": "udm-pro",
        "uptime": 12345,
    }
    info_out = AccessSystemInfo.from_manager_output(info_sample).to_dict()
    assert info_out["name"] == "Access Application"
    assert info_out["version"] == "1.24.0"
    assert info_out["hostname"] == "udm-pro"
    assert info_out["uptime"] == 12345

    nested_host_out = AccessSystemInfo.from_manager_output(
        {
            "source": "access-proxy",
            "version": 4,
            "host": {"device_type": "UNVR", "ip": "192.0.2.10"},
            "uptime": 83622.28,
        }
    ).to_dict()
    assert nested_host_out["name"] == "access-proxy"
    assert nested_host_out["version"] == "4"
    assert nested_host_out["hostname"] == "192.0.2.10"
    assert nested_host_out["uptime"] == 83622

    health_sample = {
        "host": "10.0.0.1",
        "is_connected": True,
        "api_client_available": True,
        "proxy_available": True,
        "api_client_healthy": True,
        "proxy_healthy": True,
    }
    health_out = AccessHealth.from_manager_output(health_sample).to_dict()
    assert "status" in health_out
    assert health_out["status"] == "healthy"


def test_access_mutation_acks() -> None:
    reg = _registry()
    lock = reg.serializer_for_tool("access_lock_door")
    # Manager preview shape passes through unchanged
    preview = {"door_id": "d1", "proposed_changes": {"action": "lock"}}
    assert lock.serialize(preview) == preview
    # Bool coerces to {"success": bool}
    assert lock.serialize(True) == {"success": True}

    reboot = reg.serializer_for_tool("access_reboot_device")
    assert reboot.serialize(False) == {"success": False}

    upd = reg.serializer_for_tool("access_update_policy")
    assert upd.serialize({"policy_id": "p1", "result": "success"}) == {
        "policy_id": "p1",
        "result": "success",
    }
