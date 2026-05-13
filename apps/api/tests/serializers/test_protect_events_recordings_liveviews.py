"""Protect events + recordings + liveviews + chimes serializer tests
(Phase 4A PR2 Cluster 2).

Manager methods covered:
  - ``EventManager.get_event`` -> dict (event detail)
  - ``EventManager.get_event_thumbnail`` -> dict with image_base64+content_type
  - ``EventManager.list_smart_detections`` -> list[dict] (event log)
  - ``EventManager.acknowledge_event`` -> preview dict
  - ``RecordingManager.get_recording_status`` -> {cameras: [...], count}
  - ``RecordingManager.delete_recording`` / ``export_clip`` -> preview dicts
  - ``LiveviewManager.list_liveviews`` -> list[dict] of summaries
  - ``LiveviewManager.create_liveview`` / ``delete_liveview`` -> preview dicts
  - ``ChimeManager.trigger_chime`` / ``update_chime`` -> dicts

For ``protect_recent_events`` the tool layer returns
``{success, data: {events: [...], ...}}`` wrapper dicts; we register a
DETAIL pass-through serializer because the wrapper *is* the payload.

Phase 4B PR3 Task 14 migrates ``protect_subscribe_events`` to
``ProtectStreamSubscriptionSerializer`` (STREAM kind) returning
``{stream_url, transport: "sse", buffer_size, instructions}``.
"""

from unifi_api.serializers._registry import (
    discover_serializers,
    serializer_registry_singleton,
)


def _registry():
    discover_serializers(manifest_tool_names=set())
    return serializer_registry_singleton()


# ---- liveviews.py ----


def test_liveview_list_serializer_shape() -> None:
    """Phase 6 PR3 Task C — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.protect.liveviews import Liveview

    sample = {
        "id": "lv-001",
        "name": "Front Yard",
        "is_default": True,
        "is_global": False,
        "layout": 4,
        "owner_id": "user-1",
        "slots": [
            {"camera_ids": ["cam1", "cam2"], "cycle_mode": "none", "cycle_interval": 0},
            {"camera_ids": ["cam3"], "cycle_mode": "none", "cycle_interval": 0},
        ],
        "slot_count": 2,
        "camera_count": 3,
    }
    out = Liveview.from_manager_output(sample).to_dict()
    assert out["id"] == "lv-001"
    assert out["name"] == "Front Yard"
    assert out["layout"] == 4
    assert out["cameras"] == ["cam1", "cam2", "cam3"]
    assert out["slot_count"] == 2
    assert out["camera_count"] == 3
    assert Liveview.render_hint("list")["kind"] == "list"


def test_liveview_mutation_ack_create() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("protect_create_liveview")
    sample = {
        "name": "Test View",
        "camera_ids": ["cam1"],
        "invalid_camera_ids": [],
        "camera_count": 1,
        "supported": False,
        "message": "Liveview creation is not directly supported...",
    }
    out = s.serialize_action(sample, tool_name="protect_create_liveview")
    assert out["success"] is True
    assert out["data"]["name"] == "Test View"
    assert out["data"]["supported"] is False
    assert out["render_hint"]["kind"] == "detail"


def test_liveview_mutation_ack_delete() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("protect_delete_liveview")
    sample = {
        "liveview_id": "lv-001",
        "liveview_name": "Front Yard",
        "is_default": True,
        "is_global": False,
        "slot_count": 2,
        "supported": False,
        "message": "Liveview deletion is not directly supported...",
    }
    out = s.serialize_action(sample, tool_name="protect_delete_liveview")
    assert out["success"] is True
    assert out["data"]["liveview_id"] == "lv-001"
    assert out["render_hint"]["kind"] == "detail"


# ---- events.py extensions ----


def test_event_detail_serializer_shape() -> None:
    """Phase 6 PR3 Task B — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.protect.events import Event

    sample = {
        "id": "evt-1",
        "type": "smartDetectZone",
        "start": "2026-04-29T08:00:00+00:00",
        "end": "2026-04-29T08:00:05+00:00",
        "score": 87,
        "smart_detect_types": ["person"],
        "camera_id": "cam1",
        "thumbnail_id": "thumb-1",
        "recognized_person_id": "face-group-1",
        "recognized_person_name": "Assigned Person",
        "recognized_person_confidence": 94,
        "detected_thumbnail_id": "crop-1",
    }
    out = Event.from_manager_output(sample).to_dict()
    assert out["id"] == "evt-1"
    assert out["type"] == "smartDetectZone"
    assert out["score"] == 87
    assert out["camera"] == "cam1"
    assert out["thumbnail"] == "thumb-1"
    assert out["smart_detect_types"] == ["person"]
    assert out["recognized_person_id"] == "face-group-1"
    assert out["recognized_person_name"] == "Assigned Person"
    assert out["recognized_person_confidence"] == 94
    assert out["detected_thumbnail_id"] == "crop-1"
    assert Event.render_hint("detail")["kind"] == "detail"
    assert Event.render_hint("event_log")["sort_default"] == "start:desc"


def test_event_thumbnail_serializer_shape() -> None:
    """Phase 6 PR3 Task B — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.protect.events import EventThumbnail

    sample = {
        "event_id": "evt-1",
        "thumbnail_id": "thumb-1",
        "thumbnail_available": True,
        "image_base64": "QUJDRA==",
        "content_type": "image/jpeg",
    }
    out = EventThumbnail.from_manager_output(sample).to_dict()
    assert out["event_id"] == "evt-1"
    assert out["content_type"] == "image/jpeg"
    assert out["thumbnail_available"] is True
    assert EventThumbnail.render_hint("detail")["kind"] == "detail"


def test_event_thumbnail_serializer_unavailable_shape() -> None:
    """Phase 6 PR3 Task B — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.protect.events import EventThumbnail

    sample = {
        "event_id": "evt-1",
        "thumbnail_available": False,
        "message": "Event has no thumbnail (may still be in progress).",
    }
    out = EventThumbnail.from_manager_output(sample).to_dict()
    assert out["thumbnail_available"] is False
    assert out["message"] == "Event has no thumbnail (may still be in progress)."


def test_smart_detections_serializer_shape() -> None:
    """Phase 6 PR3 Task B — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.protect.events import SmartDetection

    sample = {
        "id": "evt-2",
        "type": "smartDetectZone",
        "start": "2026-04-29T08:00:00+00:00",
        "end": "2026-04-29T08:00:05+00:00",
        "score": 90,
        "smart_detect_types": ["vehicle"],
        "camera_id": "cam1",
        "thumbnail_id": "thumb-2",
        "recognized_person_id": "face-group-2",
        "recognized_person_name": "Another Person",
        "recognized_person_confidence": 91,
        "detected_thumbnail_id": "crop-2",
    }
    out = SmartDetection.from_manager_output(sample).to_dict()
    assert out["id"] == "evt-2"
    assert out["smart_detect_types"] == ["vehicle"]
    assert out["camera"] == "cam1"
    assert out["recognized_person_name"] == "Another Person"
    assert out["recognized_person_confidence"] == 91
    assert out["detected_thumbnail_id"] == "crop-2"
    assert SmartDetection.render_hint("event_log")["kind"] == "event_log"
    assert "smart_detect_types" in SmartDetection.render_hint("event_log")["display_columns"]
    assert "recognized_person_name" in SmartDetection.render_hint("event_log")["display_columns"]


def test_recent_events_serializer_passthrough() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("protect_recent_events")
    sample = {
        "events": [{"id": "evt-3", "type": "motion"}],
        "count": 1,
        "source": "websocket_buffer",
        "buffer_size": 100,
    }
    out = s.serialize_action(sample, tool_name="protect_recent_events")
    assert out["success"] is True
    assert out["data"]["count"] == 1
    assert out["data"]["events"][0]["id"] == "evt-3"
    assert out["render_hint"]["kind"] == "detail"


def test_subscribe_events_serializer_shape() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("protect_subscribe_events")
    sample = {
        "resource_uri": "protect://events/stream",
        "summary_uri": "protect://events/stream/summary",
        "instructions": "Read the resource at ...",
        "buffer_size": 100,
    }
    out = s.serialize_action(sample, tool_name="protect_subscribe_events")
    assert out["success"] is True
    assert out["data"]["stream_url"] == "/v1/streams/protect/events"
    assert out["data"]["transport"] == "sse"
    assert out["data"]["buffer_size"] == 100
    assert out["data"]["instructions"] == "Read the resource at ..."
    assert out["render_hint"]["kind"] == "stream"


def test_subscribe_events_serializer_non_dict_input() -> None:
    """Non-dict inputs still surface the stream metadata."""
    reg = _registry()
    s = reg.serializer_for_tool("protect_subscribe_events")
    out = s.serialize_action("sub-abc-123", tool_name="protect_subscribe_events")
    assert out["success"] is True
    assert out["data"]["stream_url"] == "/v1/streams/protect/events"
    assert out["data"]["transport"] == "sse"
    assert out["render_hint"]["kind"] == "stream"


def test_event_mutation_ack_acknowledge() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("protect_acknowledge_event")
    sample = {
        "event_id": "evt-1",
        "type": "motion",
        "camera_id": "cam1",
        "camera_name": "Front Door",
        "current_is_favorite": False,
        "proposed_is_favorite": True,
    }
    out = s.serialize_action(sample, tool_name="protect_acknowledge_event")
    assert out["success"] is True
    assert out["data"]["event_id"] == "evt-1"
    assert out["data"]["proposed_is_favorite"] is True
    assert out["render_hint"]["kind"] == "detail"


# ---- recordings.py extensions ----


def test_recording_status_serializer_shape() -> None:
    """Phase 6 PR3 Task B — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.protect.recordings import RecordingStatusList

    sample = {
        "cameras": [
            {
                "camera_id": "cam1",
                "camera_name": "Front Door",
                "recording_mode": "always",
                "is_recording": True,
                "has_recordings": True,
                "video_stats": {
                    "recording_start": "2026-04-29T00:00:00+00:00",
                    "recording_end": "2026-04-29T08:00:00+00:00",
                    "timelapse_start": None,
                    "timelapse_end": None,
                },
            }
        ],
        "count": 1,
    }
    out = RecordingStatusList.from_manager_output(sample).to_dict()
    assert out["count"] == 1
    assert out["cameras"][0]["camera_id"] == "cam1"
    assert out["cameras"][0]["is_recording"] is True
    assert RecordingStatusList.render_hint("detail")["kind"] == "detail"


def test_recording_mutation_ack_export_clip() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("protect_export_clip")
    sample = {
        "camera_id": "cam1",
        "start": "2026-04-29T08:00:00+00:00",
        "end": "2026-04-29T08:01:00+00:00",
        "output_path": "/tmp/clip.mp4",
        "size_bytes": 524288,
    }
    out = s.serialize_action(sample, tool_name="protect_export_clip")
    assert out["success"] is True
    assert out["data"]["camera_id"] == "cam1"
    assert out["data"]["size_bytes"] == 524288
    assert out["render_hint"]["kind"] == "detail"


def test_recording_mutation_ack_delete_recording() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("protect_delete_recording")
    sample = {
        "camera_id": "cam1",
        "start": "2026-04-29T08:00:00+00:00",
        "end": "2026-04-29T08:01:00+00:00",
        "deleted": True,
    }
    out = s.serialize_action(sample, tool_name="protect_delete_recording")
    assert out["success"] is True
    assert out["data"]["deleted"] is True
    assert out["render_hint"]["kind"] == "detail"


# ---- chimes.py extensions ----


def test_chime_mutation_ack_trigger() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("protect_trigger_chime")
    sample = {
        "chime_id": "chime1",
        "chime_name": "Front Door Chime",
        "triggered": True,
        "volume": 50,
        "repeat_times": 1,
    }
    out = s.serialize_action(sample, tool_name="protect_trigger_chime")
    assert out["success"] is True
    assert out["data"]["chime_id"] == "chime1"
    assert out["data"]["triggered"] is True
    assert out["render_hint"]["kind"] == "detail"


def test_chime_mutation_ack_update() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("protect_update_chime")
    sample = {
        "chime_id": "chime1",
        "chime_name": "Front Door Chime",
        "current_state": {"volume": 50},
        "proposed_changes": {"volume": 75},
    }
    out = s.serialize_action(sample, tool_name="protect_update_chime")
    assert out["success"] is True
    assert out["data"]["proposed_changes"]["volume"] == 75
    assert out["render_hint"]["kind"] == "detail"
