"""Protect cameras + lights + chimes serializer unit tests (Phase 4A PR2 Cluster 1).

Manager methods in unifi-core return plain dicts already shaped by helpers
(``_format_chime_summary``, ``get_camera_streams``, ``get_camera_analytics``,
``get_snapshot``, ptz/toggle/reboot/update preview methods). Tests feed dicts
(or bytes for snapshot) and check shape + DETAIL/LIST contract.
"""

from unifi_api.serializers._registry import (
    discover_serializers,
    serializer_registry_singleton,
)
from unifi_core.redaction import REDACTED


def _registry():
    discover_serializers(manifest_tool_names=set())
    return serializer_registry_singleton()


# ---- chimes.py ----


def test_chime_list_serializer_shape() -> None:
    """Phase 6 PR3 Task A — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.protect.chimes import Chime

    sample = {
        "id": "chime1",
        "mac": "aa:bb:cc:dd:ee:01",
        "name": "Front Door Chime",
        "model": "UFP-Chime",
        "type": "UFP-CHIME",
        "state": "CONNECTED",
        "is_connected": True,
        "firmware_version": "1.2.3",
        "volume": 50,
        "camera_ids": ["cam1", "cam2"],
        "ring_settings": [],
        "available_tracks": [],
    }
    out = Chime.from_manager_output(sample).to_dict()
    assert out["id"] == "chime1"
    assert out["name"] == "Front Door Chime"
    assert out["state"] == "CONNECTED"
    assert out["paired_cameras"] == ["cam1", "cam2"]
    assert Chime.render_hint("list")["kind"] == "list"


# ---- cameras.py extensions ----


def test_camera_analytics_serializer_shape() -> None:
    """Phase 6 PR3 Task A — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.protect.cameras import CameraAnalytics

    sample = {
        "camera_id": "cam1",
        "camera_name": "Front Door",
        "detections": {
            "is_motion_detected": False,
            "is_smart_detected": True,
            "last_motion": "2026-04-29T08:30:00+00:00",
        },
        "smart_detects": {"person": "2026-04-29T08:30:00+00:00"},
        "smart_audio_detects": {},
        "currently_detected": {"person": True, "vehicle": False},
        "motion_zone_count": 2,
        "smart_detect_zone_count": 1,
        "stats": {},
    }
    out = CameraAnalytics.from_manager_output(sample).to_dict()
    assert out["camera_id"] == "cam1"
    assert out["motion_zone_count"] == 2
    assert out["smart_detects"] == {"person": "2026-04-29T08:30:00+00:00"}
    assert CameraAnalytics.render_hint("detail")["kind"] == "detail"


def test_camera_streams_serializer_shape() -> None:
    """Phase 6 PR3 Task A — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.protect.cameras import CameraStreams

    sample = {
        "camera_id": "cam1",
        "camera_name": "Front Door",
        "channels": {
            "high": {
                "channel_id": 0,
                "enabled": True,
                "rtsp_alias": "abc123",
                "rtsps_url": "rtsps://nvr.local:7441/abc123",
                "rtsp_url": "rtsp://nvr.local:7447/abc123",
                "width": 1920,
                "height": 1080,
                "fps": 30,
                "bitrate": 4000,
            }
        },
        "rtsps_streams": {"high": "rtsps://nvr.local:7441/xyz789"},
    }
    out = CameraStreams.from_manager_output(sample).to_dict()
    assert out["camera_id"] == "cam1"
    assert "high" in out["channels"]
    assert out["channels"]["high"]["rtsp_alias"] == REDACTED
    assert out["channels"]["high"]["rtsps_url"] == REDACTED
    assert out["channels"]["high"]["rtsp_url"] == REDACTED
    assert out["rtsps_streams"] == REDACTED
    assert CameraStreams.render_hint("detail")["kind"] == "detail"


def test_camera_streams_policy_disabled_returns_raw_urls() -> None:
    from unifi_api.graphql.types.protect.cameras import CameraStreams

    sample = {
        "camera_id": "cam1",
        "camera_name": "Front Door",
        "channels": {
            "high": {
                "rtsp_alias": "abc123",
                "rtsps_url": "rtsps://nvr.local:7441/abc123",
                "rtsp_url": "rtsp://nvr.local:7447/abc123",
            }
        },
        "rtsps_streams": {"high": "rtsps://nvr.local:7441/xyz789"},
    }
    out = CameraStreams.from_manager_output(sample, redact_sensitive=False).to_dict()
    assert out["channels"]["high"]["rtsp_alias"] == "abc123"
    assert out["channels"]["high"]["rtsps_url"] == "rtsps://nvr.local:7441/abc123"
    assert out["channels"]["high"]["rtsp_url"] == "rtsp://nvr.local:7447/abc123"
    assert out["rtsps_streams"]["high"] == "rtsps://nvr.local:7441/xyz789"


def test_snapshot_serializer_bytes_shape() -> None:
    """Phase 6 PR3 Task A — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.protect.cameras import Snapshot

    sample = b"\xff\xd8\xff\xe0" + b"\x00" * 1020  # fake JPEG header + padding
    out = Snapshot.from_manager_output(sample).to_dict()
    assert out["size_bytes"] == 1024
    assert out["content_type"] == "image/jpeg"
    assert Snapshot.render_hint("detail")["kind"] == "detail"


def test_camera_mutation_ack_ptz_move() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("protect_ptz_move")
    sample = {
        "camera_id": "cam1",
        "camera_name": "Front Door",
        "movement": {"pan": 50, "tilt": -25, "duration_ms": 250},
        "actions_taken": ["pan=50", "tilt=-25", "duration_ms=250"],
    }
    out = s.serialize_action(sample, tool_name="protect_ptz_move")
    assert out["success"] is True
    assert out["data"]["camera_id"] == "cam1"
    assert out["render_hint"]["kind"] == "detail"


def test_camera_mutation_ack_dispatches_for_all() -> None:
    reg = _registry()
    for tool in (
        "protect_ptz_move",
        "protect_ptz_preset",
        "protect_ptz_zoom",
        "protect_reboot_camera",
        "protect_toggle_recording",
        "protect_update_camera_settings",
    ):
        s = reg.serializer_for_tool(tool)
        out = s.serialize_action({"camera_id": "cam1"}, tool_name=tool)
        assert out["render_hint"]["kind"] == "detail"
        assert out["success"] is True


# ---- lights.py extension ----


def test_light_mutation_ack_update_light() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("protect_update_light")
    sample = {
        "light_id": "light1",
        "light_name": "Driveway",
        "current_state": {"light_on": False, "led_level": 3},
        "proposed_changes": {"light_on": True, "led_level": 5},
    }
    out = s.serialize_action(sample, tool_name="protect_update_light")
    assert out["success"] is True
    assert out["data"]["light_id"] == "light1"
    assert out["data"]["proposed_changes"]["light_on"] is True
    assert out["render_hint"]["kind"] == "detail"
