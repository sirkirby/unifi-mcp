"""Protect serializer unit tests — one fixture per resource.

Protect managers in unifi-core return plain dicts (already shaped by
``_format_*_summary`` / ``_event_to_dict`` helpers), so each fixture is a
dict and the serializer reads dict keys directly.
"""

from unifi_api.serializers._registry import (
    discover_serializers,
    serializer_registry_singleton,
)


def _registry():
    """Trigger discovery once for the test module."""
    discover_serializers(manifest_tool_names=set())
    return serializer_registry_singleton()


def test_camera_serializer_shape() -> None:
    """Phase 6 PR3 Task A — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.protect.cameras import Camera

    sample = {
        "id": "cam1",
        "mac": "aa:bb:cc:dd:ee:01",
        "name": "Front Door",
        "model": "G4 Pro",
        "type": "G4PRO",
        "state": "CONNECTED",
        "is_recording": True,
        "is_motion_detected": False,
        "is_smart_detected": False,
        "firmware_version": "5.4.132",
        "ip_address": "10.0.0.50",
        "smart_detect_types": ["person", "vehicle"],
        "is_ptz": False,
        "channels": [{"id": 0, "name": "high"}],
    }
    out = Camera.from_manager_output(sample).to_dict()
    assert out["id"] == "cam1"
    assert out["mac"] == "aa:bb:cc:dd:ee:01"
    assert out["name"] == "Front Door"
    assert out["model"] == "G4 Pro"
    assert out["state"] == "CONNECTED"
    assert out["firmware_version"] == "5.4.132"
    assert out["host"] == "10.0.0.50"
    assert out["smart_detect_types"] == ["person", "vehicle"]
    assert out["is_ptz"] is False


def test_event_serializer_shape() -> None:
    """Phase 6 PR3 Task B — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.protect.events import Event

    sample = {
        "id": "evt1",
        "type": "smartDetectZone",
        "start": "2026-04-29T10:00:00+00:00",
        "end": "2026-04-29T10:00:30+00:00",
        "score": 87,
        "smart_detect_types": ["person"],
        "camera_id": "cam1",
        "thumbnail_id": "thumb1",
    }
    out = Event.from_manager_output(sample).to_dict()
    assert out["id"] == "evt1"
    assert out["type"] == "smartDetectZone"
    assert out["start"] == "2026-04-29T10:00:00+00:00"
    assert out["end"] == "2026-04-29T10:00:30+00:00"
    assert out["score"] == 87


def test_light_serializer_shape() -> None:
    """Phase 6 PR3 Task C — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.protect.lights import Light

    sample = {
        "id": "light1",
        "mac": "aa:bb:cc:dd:ee:02",
        "name": "Driveway Light",
        "model": "UFP-FloodLight",
        "state": "CONNECTED",
        "is_pir_motion_detected": False,
        "is_light_on": True,
    }
    out = Light.from_manager_output(sample).to_dict()
    assert out["id"] == "light1"
    assert out["mac"] == "aa:bb:cc:dd:ee:02"
    assert out["name"] == "Driveway Light"
    assert out["state"] == "CONNECTED"
    assert Light.render_hint("list")["kind"] == "list"


def test_recording_serializer_shape() -> None:
    """Phase 6 PR3 Task B — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.protect.recordings import Recording

    sample = {
        "id": "rec1",
        "type": "timelapse",
        "camera_id": "cam1",
        "start": "2026-04-29T09:00:00+00:00",
        "end": "2026-04-29T09:15:00+00:00",
        "file_size": 12345678,
    }
    out = Recording.from_manager_output(sample).to_dict()
    assert out["id"] == "rec1"
    assert out["type"] == "timelapse"
    assert out["camera"] == "cam1"
    assert out["start"] == "2026-04-29T09:00:00+00:00"
    assert out["end"] == "2026-04-29T09:15:00+00:00"
    assert out["file_size"] == 12345678


def test_sensor_serializer_shape() -> None:
    """Phase 6 PR3 Task C — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.protect.sensors import Sensor

    sample = {
        "id": "sensor1",
        "mac": "aa:bb:cc:dd:ee:03",
        "name": "Garage Sensor",
        "type": "UFP-SENSOR",
        "battery": {"status": "normal", "percentage": 92},
        "stats": {
            "humidity": {"status": "normal", "value": 45},
            "light": {"status": "normal", "value": 120},
        },
        "motion_detected_at": "2026-04-29T08:30:00+00:00",
    }
    out = Sensor.from_manager_output(sample).to_dict()
    assert out["id"] == "sensor1"
    assert out["mac"] == "aa:bb:cc:dd:ee:03"
    assert out["name"] == "Garage Sensor"
    assert out["type"] == "UFP-SENSOR"
    assert out["battery_status"] == "normal"
    assert out["humidity_status"] == "normal"
    assert out["light_status"] == "normal"
    assert Sensor.render_hint("list")["kind"] == "list"
