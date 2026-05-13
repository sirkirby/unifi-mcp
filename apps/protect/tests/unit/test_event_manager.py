"""Tests for EventManager domain logic."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from uiprotect.data import EventType, ModelType, SmartDetectObjectType, WSAction

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.managers.event_manager import EventManager


def _make_event(**overrides) -> MagicMock:
    """Build a mock uiprotect Event object."""
    ev = MagicMock()
    ev.id = overrides.get("id", "evt-001")
    ev.type = overrides.get("type", EventType.MOTION)
    ev.camera_id = overrides.get("camera_id", "cam-001")
    ev.start = overrides.get("start", datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc))
    ev.end = overrides.get("end", None)
    ev.score = overrides.get("score", 85)
    ev.smart_detect_types = overrides.get("smart_detect_types", [])
    ev.thumbnail_id = overrides.get("thumbnail_id", "thumb-001")
    ev.category = overrides.get("category", "motion")
    ev.sub_category = overrides.get("sub_category", None)
    ev.is_favorite = overrides.get("is_favorite", False)
    ev.metadata = overrides.get("metadata", None)
    ev.get_detected_thumbnail = MagicMock(return_value=overrides.get("detected_thumbnail", None))
    ev.model = overrides.get("model", ModelType.EVENT)
    ev.save_device = AsyncMock()
    return ev


def _make_ws_message(action="add", model_type=None, new_obj=None):
    """Build a mock WSSubscriptionMessage."""
    msg = MagicMock()
    msg.action = WSAction(action) if isinstance(action, str) else action
    msg.new_obj = new_obj
    return msg


def _make_connection_manager(events=None) -> MagicMock:
    """Build a mock ProtectConnectionManager."""
    cm = MagicMock()
    cm.client.get_events = AsyncMock(return_value=events or [])
    cm.client.get_event = AsyncMock()
    cm.client.get_event_thumbnail = AsyncMock()
    cm.client.api_request = AsyncMock(return_value={"groups": []})
    cm.client.subscribe_websocket = MagicMock(return_value=MagicMock())  # unsub callable
    return cm


# ---------------------------------------------------------------------------
# EventManager construction
# ---------------------------------------------------------------------------


class TestEventManagerInit:
    def test_default_config(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        assert mgr._min_confidence == 50
        assert mgr._buffer._buffer.maxlen == 100
        assert mgr._buffer._ttl == 300

    def test_custom_config(self):
        cm = _make_connection_manager()
        mgr = EventManager(
            cm, config={"buffer_size": 50, "buffer_ttl_seconds": 60, "smart_detection_min_confidence": 70}
        )
        assert mgr._min_confidence == 70
        assert mgr._buffer._buffer.maxlen == 50
        assert mgr._buffer._ttl == 60


# ---------------------------------------------------------------------------
# Websocket message parsing
# ---------------------------------------------------------------------------


class TestEventManagerParsing:
    def test_parse_event_add(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        event = _make_event(id="evt-100", score=90)
        msg = _make_ws_message(action="add", new_obj=event)
        result = mgr._parse_ws_message(msg)
        assert result is not None
        assert result["id"] == "evt-100"
        assert result["score"] == 90
        assert result["type"] == "motion"

    def test_parse_event_update(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        event = _make_event(type=EventType.SMART_DETECT)
        msg = _make_ws_message(action="update", new_obj=event)
        result = mgr._parse_ws_message(msg)
        assert result is not None
        assert result["type"] == "smartDetectZone"

    def test_parse_ignores_remove_action(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        event = _make_event()
        msg = _make_ws_message(action="remove", new_obj=event)
        result = mgr._parse_ws_message(msg)
        assert result is None

    def test_parse_ignores_non_event_model(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        camera_obj = MagicMock()
        camera_obj.model = ModelType.CAMERA
        msg = _make_ws_message(action="add", new_obj=camera_obj)
        result = mgr._parse_ws_message(msg)
        assert result is None

    def test_parse_ignores_none_new_obj(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        msg = _make_ws_message(action="add", new_obj=None)
        result = mgr._parse_ws_message(msg)
        assert result is None

    def test_parse_with_smart_detect_types(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        event = _make_event(
            type=EventType.SMART_DETECT,
            smart_detect_types=[SmartDetectObjectType.PERSON, SmartDetectObjectType.VEHICLE],
        )
        msg = _make_ws_message(action="add", new_obj=event)
        result = mgr._parse_ws_message(msg)
        assert result is not None
        assert "person" in result["smart_detect_types"]
        assert "vehicle" in result["smart_detect_types"]


# ---------------------------------------------------------------------------
# Websocket callback -> buffer integration
# ---------------------------------------------------------------------------


class TestEventManagerWebsocketCallback:
    def test_on_ws_message_adds_to_buffer(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        event = _make_event()
        msg = _make_ws_message(action="add", new_obj=event)
        mgr._on_ws_message(msg)
        assert mgr.buffer_size == 1

    def test_on_ws_message_skips_non_events(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        camera_obj = MagicMock()
        camera_obj.model = ModelType.CAMERA
        msg = _make_ws_message(action="add", new_obj=camera_obj)
        mgr._on_ws_message(msg)
        assert mgr.buffer_size == 0

    def test_on_ws_message_handles_error_gracefully(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        # Force an error in parsing
        msg = MagicMock()
        msg.action = None  # Will cause attribute error in WSAction comparison
        # Should not raise
        mgr._on_ws_message(msg)
        assert mgr.buffer_size == 0


# ---------------------------------------------------------------------------
# Buffer access
# ---------------------------------------------------------------------------


class TestEventManagerBufferAccess:
    def test_get_recent_from_buffer(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        for i in range(5):
            event = _make_event(id=f"evt-{i}")
            msg = _make_ws_message(action="add", new_obj=event)
            mgr._on_ws_message(msg)
        results = mgr.get_recent_from_buffer()
        assert len(results) == 5

    def test_get_recent_with_filters(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        # Add a motion event
        event1 = _make_event(id="evt-1", type=EventType.MOTION, camera_id="cam-001")
        mgr._on_ws_message(_make_ws_message(action="add", new_obj=event1))
        # Add a smart detect event
        event2 = _make_event(id="evt-2", type=EventType.SMART_DETECT, camera_id="cam-002")
        mgr._on_ws_message(_make_ws_message(action="add", new_obj=event2))

        results = mgr.get_recent_from_buffer(camera_id="cam-001")
        assert len(results) == 1
        assert results[0]["id"] == "evt-1"


# ---------------------------------------------------------------------------
# Websocket lifecycle
# ---------------------------------------------------------------------------


class TestEventManagerWebsocketLifecycle:
    @pytest.mark.asyncio
    async def test_start_listening(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        await mgr.start_listening()
        cm.client.subscribe_websocket.assert_called_once_with(mgr._on_ws_message)
        assert mgr._ws_unsub is not None

    @pytest.mark.asyncio
    async def test_stop_listening(self):
        cm = _make_connection_manager()
        unsub = MagicMock()
        cm.client.subscribe_websocket = MagicMock(return_value=unsub)
        mgr = EventManager(cm)
        await mgr.start_listening()
        await mgr.stop_listening()
        unsub.assert_called_once()
        assert mgr._ws_unsub is None

    @pytest.mark.asyncio
    async def test_stop_listening_when_not_started(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        # Should not raise
        await mgr.stop_listening()
        assert mgr._ws_unsub is None

    def test_set_server(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        mock_server = MagicMock()
        mgr.set_server(mock_server)
        assert mgr._server is mock_server


# ---------------------------------------------------------------------------
# REST API: list_events
# ---------------------------------------------------------------------------


class TestEventManagerListEvents:
    @pytest.mark.asyncio
    async def test_basic_list(self):
        events = [_make_event(id="evt-1"), _make_event(id="evt-2")]
        cm = _make_connection_manager(events=events)
        mgr = EventManager(cm)
        results = await mgr.list_events()
        assert len(results) == 2
        assert results[0]["id"] == "evt-1"
        cm.client.get_events.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_with_camera_filter(self):
        events = [
            _make_event(id="evt-1", camera_id="cam-001"),
            _make_event(id="evt-2", camera_id="cam-002"),
        ]
        cm = _make_connection_manager(events=events)
        mgr = EventManager(cm)
        results = await mgr.list_events(camera_id="cam-001")
        assert len(results) == 1
        assert results[0]["camera_id"] == "cam-001"

    @pytest.mark.asyncio
    async def test_list_with_limit(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        await mgr.list_events(limit=10)
        call_kwargs = cm.client.get_events.call_args.kwargs
        assert call_kwargs["limit"] == 10

    @pytest.mark.asyncio
    async def test_list_with_time_range(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        start = datetime(2026, 3, 15, tzinfo=timezone.utc)
        end = datetime(2026, 3, 16, tzinfo=timezone.utc)
        await mgr.list_events(start=start, end=end)
        call_kwargs = cm.client.get_events.call_args.kwargs
        assert call_kwargs["start"] == start
        assert call_kwargs["end"] == end

    @pytest.mark.asyncio
    async def test_empty_results(self):
        cm = _make_connection_manager(events=[])
        mgr = EventManager(cm)
        results = await mgr.list_events()
        assert results == []


# ---------------------------------------------------------------------------
# REST API: get_event
# ---------------------------------------------------------------------------


class TestEventManagerGetEvent:
    @pytest.mark.asyncio
    async def test_success(self):
        event = _make_event(id="evt-123")
        cm = _make_connection_manager()
        cm.client.get_event = AsyncMock(return_value=event)
        mgr = EventManager(cm)
        result = await mgr.get_event("evt-123")
        assert result["id"] == "evt-123"
        cm.client.get_event.assert_awaited_once_with("evt-123")

    @pytest.mark.asyncio
    async def test_backfills_recognition_metadata_from_list_path(self):
        detail_event = _make_event(
            id="evt-123",
            type=EventType.SMART_DETECT,
            smart_detect_types=[SmartDetectObjectType.FACE],
            metadata={"detectedThumbnails": [{"type": "face", "croppedId": "detail-crop"}]},
        )
        list_event = _make_event(
            id="evt-123",
            type=EventType.SMART_DETECT,
            smart_detect_types=[SmartDetectObjectType.FACE],
            metadata={
                "detectedThumbnails": [
                    {
                        "type": "face",
                        "croppedId": "list-crop",
                        "group": {"id": "face-group-1", "matchedName": "Assigned Person", "confidence": 94},
                    }
                ]
            },
        )
        cm = _make_connection_manager()
        cm.client.get_event = AsyncMock(return_value=detail_event)
        cm.client.get_events = AsyncMock(return_value=[list_event])
        mgr = EventManager(cm)

        result = await mgr.get_event("evt-123")

        assert result["recognized_person_id"] == "face-group-1"
        assert result["recognized_person_name"] == "Assigned Person"
        assert result["recognized_person_confidence"] == 94
        assert result["detected_thumbnail_id"] == "list-crop"
        cm.client.get_events.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_found(self):
        cm = _make_connection_manager()
        cm.client.get_event = AsyncMock(side_effect=Exception("404 Not Found"))
        mgr = EventManager(cm)
        with pytest.raises(UniFiNotFoundError):
            await mgr.get_event("nonexistent")


# ---------------------------------------------------------------------------
# REST API: get_event_thumbnail
# ---------------------------------------------------------------------------


class TestEventManagerGetEventThumbnail:
    @pytest.mark.asyncio
    async def test_success(self):
        event = _make_event(id="evt-1", thumbnail_id="thumb-abc")
        cm = _make_connection_manager()
        cm.client.get_event = AsyncMock(return_value=event)
        cm.client.get_event_thumbnail = AsyncMock(return_value=b"\xff\xd8JPEG")
        mgr = EventManager(cm)
        result = await mgr.get_event_thumbnail("evt-1")
        assert result["thumbnail_available"] is True
        assert result["content_type"] == "image/jpeg"
        assert "image_base64" in result

    @pytest.mark.asyncio
    async def test_no_thumbnail_id(self):
        event = _make_event(id="evt-1", thumbnail_id=None)
        cm = _make_connection_manager()
        cm.client.get_event = AsyncMock(return_value=event)
        mgr = EventManager(cm)
        result = await mgr.get_event_thumbnail("evt-1")
        assert result["thumbnail_available"] is False

    @pytest.mark.asyncio
    async def test_thumbnail_returns_none(self):
        event = _make_event(id="evt-1", thumbnail_id="thumb-abc")
        cm = _make_connection_manager()
        cm.client.get_event = AsyncMock(return_value=event)
        cm.client.get_event_thumbnail = AsyncMock(return_value=None)
        mgr = EventManager(cm)
        result = await mgr.get_event_thumbnail("evt-1")
        assert result["thumbnail_available"] is False

    @pytest.mark.asyncio
    async def test_event_not_found(self):
        cm = _make_connection_manager()
        cm.client.get_event = AsyncMock(side_effect=Exception("404"))
        mgr = EventManager(cm)
        with pytest.raises(UniFiNotFoundError):
            await mgr.get_event_thumbnail("bad-id")

    @pytest.mark.asyncio
    async def test_with_dimensions(self):
        event = _make_event(id="evt-1", thumbnail_id="thumb-abc")
        cm = _make_connection_manager()
        cm.client.get_event = AsyncMock(return_value=event)
        cm.client.get_event_thumbnail = AsyncMock(return_value=b"\xff\xd8JPEG")
        mgr = EventManager(cm)
        await mgr.get_event_thumbnail("evt-1", width=320, height=240)
        cm.client.get_event_thumbnail.assert_awaited_once_with("thumb-abc", width=320, height=240)


# ---------------------------------------------------------------------------
# REST API: list_smart_detections
# ---------------------------------------------------------------------------


class TestEventManagerListSmartDetections:
    @pytest.mark.asyncio
    async def test_basic_list(self):
        events = [
            _make_event(id="sd-1", type=EventType.SMART_DETECT, score=90),
            _make_event(id="sd-2", type=EventType.SMART_DETECT, score=60),
        ]
        cm = _make_connection_manager(events=events)
        mgr = EventManager(cm)
        results = await mgr.list_smart_detections()
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_filters_below_min_confidence(self):
        events = [
            _make_event(id="sd-1", score=90),
            _make_event(id="sd-2", score=30),
            _make_event(id="sd-3", score=60),
        ]
        cm = _make_connection_manager(events=events)
        mgr = EventManager(cm, config={"smart_detection_min_confidence": 50})
        results = await mgr.list_smart_detections()
        assert len(results) == 2
        assert all(r["score"] >= 50 for r in results)

    @pytest.mark.asyncio
    async def test_custom_min_confidence(self):
        events = [
            _make_event(id="sd-1", score=90),
            _make_event(id="sd-2", score=70),
        ]
        cm = _make_connection_manager(events=events)
        mgr = EventManager(cm)
        results = await mgr.list_smart_detections(min_confidence=80)
        assert len(results) == 1
        assert results[0]["score"] == 90

    @pytest.mark.asyncio
    async def test_camera_filter(self):
        events = [
            _make_event(id="sd-1", camera_id="cam-001", score=90),
            _make_event(id="sd-2", camera_id="cam-002", score=80),
        ]
        cm = _make_connection_manager(events=events)
        mgr = EventManager(cm)
        results = await mgr.list_smart_detections(camera_id="cam-001")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_known_face_name_join(self):
        events = [
            _make_event(
                id="sd-1",
                type=EventType.SMART_DETECT,
                score=90,
                smart_detect_types=[SmartDetectObjectType.FACE],
                metadata={
                    "detectedThumbnails": [
                        {
                            "type": "face",
                            "croppedId": "crop-1",
                            "group": {"id": "face-group-1", "confidence": 88},
                        }
                    ]
                },
            )
        ]
        cm = _make_connection_manager(events=events)
        cm.client.api_request = AsyncMock(
            return_value={
                "groups": [
                    {
                        "id": "face-group-1",
                        "name": "Assigned Person",
                        "matchedName": "Assigned Person",
                    }
                ]
            }
        )
        mgr = EventManager(cm)

        results = await mgr.list_smart_detections(detection_type="face", min_confidence=0)

        assert results[0]["recognized_person_id"] == "face-group-1"
        assert results[0]["recognized_person_name"] == "Assigned Person"
        cm.client.api_request.assert_awaited_once()


# ---------------------------------------------------------------------------
# REST API: acknowledge_event
# ---------------------------------------------------------------------------


class TestEventManagerAcknowledgeEvent:
    @pytest.mark.asyncio
    async def test_preview(self):
        event = _make_event(id="evt-1", is_favorite=False)
        cm = _make_connection_manager()
        cm.client.get_event = AsyncMock(return_value=event)
        mgr = EventManager(cm)
        result = await mgr.acknowledge_event("evt-1")
        assert result["event_id"] == "evt-1"
        assert result["current_is_favorite"] is False
        assert result["proposed_is_favorite"] is True

    @pytest.mark.asyncio
    async def test_preview_not_found(self):
        cm = _make_connection_manager()
        cm.client.get_event = AsyncMock(side_effect=Exception("404"))
        mgr = EventManager(cm)
        with pytest.raises(UniFiNotFoundError):
            await mgr.acknowledge_event("bad-id")

    @pytest.mark.asyncio
    async def test_apply(self):
        event = _make_event(id="evt-1", is_favorite=False)
        cm = _make_connection_manager()
        cm.client.get_event = AsyncMock(return_value=event)
        mgr = EventManager(cm)
        result = await mgr.apply_acknowledge_event("evt-1")
        assert result["acknowledged"] is True
        assert result["is_favorite"] is True
        event.save_device.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_apply_not_found(self):
        cm = _make_connection_manager()
        cm.client.get_event = AsyncMock(side_effect=Exception("404"))
        mgr = EventManager(cm)
        with pytest.raises(UniFiNotFoundError):
            await mgr.apply_acknowledge_event("bad-id")


# ---------------------------------------------------------------------------
# _event_to_dict
# ---------------------------------------------------------------------------


class TestEventToDict:
    def test_full_event(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        event = _make_event(
            id="evt-42",
            type=EventType.SMART_DETECT,
            camera_id="cam-001",
            start=datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc),
            end=datetime(2026, 3, 16, 12, 1, tzinfo=timezone.utc),
            score=95,
            smart_detect_types=[SmartDetectObjectType.PERSON],
            thumbnail_id="thumb-42",
            category="smart",
            sub_category="person",
            is_favorite=True,
        )
        d = mgr._event_to_dict(event)
        assert d["id"] == "evt-42"
        assert d["type"] == "smartDetectZone"
        assert d["camera_id"] == "cam-001"
        assert d["score"] == 95
        assert d["smart_detect_types"] == ["person"]
        assert d["thumbnail_id"] == "thumb-42"
        assert d["category"] == "smart"
        assert d["is_favorite"] is True
        assert d["start"] is not None
        assert d["end"] is not None

    def test_face_recognition_metadata_from_detected_thumbnail(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        group = MagicMock()
        group.id = "face-group-1"
        group.name = "Lobby Person"
        group.matched_name = "Assigned Person"
        group.confidence = 94
        thumbnail = MagicMock()
        thumbnail.type = "face"
        thumbnail.thumbnail_id = None
        thumbnail.thumbnailId = None
        thumbnail.cropped_id = "crop-1"
        thumbnail.clock_best_wall = datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc)
        thumbnail.confidence = 88
        thumbnail.group = group
        metadata = MagicMock()
        metadata.detected_thumbnails = [thumbnail]
        event = _make_event(
            type=EventType.SMART_DETECT,
            smart_detect_types=[SmartDetectObjectType.FACE],
            metadata=metadata,
        )

        d = mgr._event_to_dict(event)

        assert d["recognized_person_id"] == "face-group-1"
        assert d["recognized_person_name"] == "Assigned Person"
        assert d["recognized_person_confidence"] == 94
        assert d["detected_thumbnail_id"] == "crop-1"

    def test_face_recognition_uses_group_id_without_name(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        metadata = {
            "detectedThumbnails": [
                {
                    "type": "face",
                    "croppedId": "crop-2",
                    "group": {"id": "face-group-2", "confidence": 81},
                }
            ]
        }
        event = _make_event(
            type=EventType.SMART_DETECT,
            smart_detect_types=[SmartDetectObjectType.FACE],
            metadata=metadata,
        )

        d = mgr._event_to_dict(event)

        assert d["recognized_person_id"] == "face-group-2"
        assert d["recognized_person_confidence"] == 81
        assert "recognized_person_name" not in d
        assert d["detected_thumbnail_id"] == "crop-2"

    def test_non_face_recognition_group_is_not_reported_as_person(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        metadata = {
            "detectedThumbnails": [
                {
                    "type": "licensePlate",
                    "croppedId": "plate-crop",
                    "group": {"id": "plate-group", "matchedName": "ABC123", "confidence": 99},
                }
            ]
        }
        event = _make_event(
            type=EventType.SMART_DETECT,
            smart_detect_types=[SmartDetectObjectType.LICENSE_PLATE],
            metadata=metadata,
        )

        d = mgr._event_to_dict(event)

        assert "recognized_person_id" not in d
        assert "recognized_person_name" not in d

    def test_event_with_no_end(self):
        cm = _make_connection_manager()
        mgr = EventManager(cm)
        event = _make_event(end=None)
        d = mgr._event_to_dict(event)
        assert d["end"] is None
