"""Protect capability mutation serializer tests."""

from unifi_api.serializers._registry import (
    discover_serializers,
    serializer_registry_singleton,
)


def _registry():
    discover_serializers(manifest_tool_names=set())
    return serializer_registry_singleton()


def test_protect_update_sensor_settings_mutation_ack_preview_and_confirm() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("protect_update_sensor_settings")

    preview = {
        "sensor_id": "sensor-1",
        "sensor_name": "Garage",
        "current_state": {"name": "Old Garage"},
        "proposed_changes": {"name": "Garage"},
    }
    preview_out = s.serialize_action(preview, tool_name="protect_update_sensor_settings")
    assert preview_out["success"] is True
    assert preview_out["data"]["sensor_id"] == "sensor-1"
    assert preview_out["data"]["proposed_changes"]["name"] == "Garage"
    assert preview_out["render_hint"]["kind"] == "detail"

    confirmed = {
        "sensor_id": "sensor-1",
        "sensor_name": "Garage",
        "applied": {"name": "Garage"},
        "updated_state": {"name": "Garage"},
    }
    confirm_out = s.serialize_action(confirmed, tool_name="protect_update_sensor_settings")
    assert confirm_out["success"] is True
    assert confirm_out["data"]["applied"]["name"] == "Garage"
    assert confirm_out["data"]["updated_state"]["name"] == "Garage"
    assert confirm_out["render_hint"]["kind"] == "detail"


def test_protect_update_viewer_mutation_ack_preview_and_confirm() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("protect_update_viewer")

    preview = {
        "viewer_id": "viewer-1",
        "viewer_name": "Lobby",
        "current_state": {"liveview_id": "old-view"},
        "proposed_changes": {"liveview_id": "new-view"},
    }
    preview_out = s.serialize_action(preview, tool_name="protect_update_viewer")
    assert preview_out["success"] is True
    assert preview_out["data"]["viewer_id"] == "viewer-1"
    assert preview_out["data"]["proposed_changes"]["liveview_id"] == "new-view"
    assert preview_out["render_hint"]["kind"] == "detail"

    confirmed = {
        "viewer_id": "viewer-1",
        "viewer_name": "Lobby",
        "applied": {"liveview_id": "new-view"},
        "updated_state": {"liveview_id": "new-view"},
    }
    confirm_out = s.serialize_action(confirmed, tool_name="protect_update_viewer")
    assert confirm_out["success"] is True
    assert confirm_out["data"]["applied"]["liveview_id"] == "new-view"
    assert confirm_out["data"]["updated_state"]["liveview_id"] == "new-view"
    assert confirm_out["render_hint"]["kind"] == "detail"


def test_protect_update_chime_mutation_ack_preview_and_confirm() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("protect_update_chime")

    preview = {
        "chime_id": "chime-1",
        "chime_name": "Front Door",
        "current_state": {"volume": 50},
        "proposed_changes": {"volume": 75},
    }
    preview_out = s.serialize_action(preview, tool_name="protect_update_chime")
    assert preview_out["success"] is True
    assert preview_out["data"]["proposed_changes"]["volume"] == 75
    assert preview_out["render_hint"]["kind"] == "detail"

    confirmed = {
        "chime_id": "chime-1",
        "chime_name": "Front Door",
        "applied": ["volume=75"],
    }
    confirm_out = s.serialize_action(confirmed, tool_name="protect_update_chime")
    assert confirm_out["success"] is True
    assert confirm_out["data"]["applied"] == ["volume=75"]
    assert confirm_out["render_hint"]["kind"] == "detail"
