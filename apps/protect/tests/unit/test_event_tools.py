"""Tests for event tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_event_manager():
    """Patch event_manager in the tools module."""
    mgr = MagicMock()
    with patch("unifi_protect_mcp.tools.events.event_manager", mgr):
        yield mgr


# ---------------------------------------------------------------------------
# protect_list_events
# ---------------------------------------------------------------------------


class TestProtectListEvents:
    @pytest.mark.asyncio
    async def test_success(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_list_events

        mock_event_manager.list_events = AsyncMock(
            return_value=[
                {"id": "evt-1", "type": "motion", "camera_id": "cam-001"},
                {"id": "evt-2", "type": "ring", "camera_id": "cam-002"},
            ]
        )
        result = await protect_list_events()
        assert result["success"] is True
        assert result["data"]["count"] == 2
        assert len(result["data"]["events"]) == 2

    @pytest.mark.asyncio
    async def test_with_filters(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_list_events

        mock_event_manager.list_events = AsyncMock(return_value=[])
        result = await protect_list_events(
            start="2026-03-16T00:00:00Z",
            end="2026-03-17T00:00:00Z",
            event_type="motion",
            camera_id="cam-001",
            limit=10,
        )
        assert result["success"] is True
        # Verify the manager was called with parsed datetime objects
        call_kwargs = mock_event_manager.list_events.call_args.kwargs
        assert call_kwargs["start"] is not None
        assert call_kwargs["end"] is not None
        assert call_kwargs["event_type"] == "motion"
        assert call_kwargs["camera_id"] == "cam-001"
        assert call_kwargs["limit"] == 10

    @pytest.mark.asyncio
    async def test_empty_results(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_list_events

        mock_event_manager.list_events = AsyncMock(return_value=[])
        result = await protect_list_events()
        assert result["success"] is True
        assert result["data"]["count"] == 0

    @pytest.mark.asyncio
    async def test_error(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_list_events

        mock_event_manager.list_events = AsyncMock(side_effect=RuntimeError("connection lost"))
        result = await protect_list_events()
        assert result["success"] is False
        assert "connection lost" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_datetime_passes_none(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_list_events

        mock_event_manager.list_events = AsyncMock(return_value=[])
        result = await protect_list_events(start="not-a-date")
        assert result["success"] is True
        # Invalid date should be passed as None
        call_kwargs = mock_event_manager.list_events.call_args.kwargs
        assert call_kwargs["start"] is None


# ---------------------------------------------------------------------------
# protect_get_event
# ---------------------------------------------------------------------------


class TestProtectGetEvent:
    @pytest.mark.asyncio
    async def test_success(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_get_event

        mock_event_manager.get_event = AsyncMock(
            return_value={
                "id": "evt-123",
                "type": "smartDetectZone",
                "score": 85,
                "recognized_person_id": "face-group-1",
                "recognized_person_name": "Assigned Person",
                "recognized_person_confidence": 94,
                "detected_thumbnail_id": "crop-1",
            }
        )
        result = await protect_get_event("evt-123")
        assert result["success"] is True
        assert result["data"]["id"] == "evt-123"
        assert result["data"]["recognized_person_name"] == "Assigned Person"

    @pytest.mark.asyncio
    async def test_not_found(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_get_event

        mock_event_manager.get_event = AsyncMock(side_effect=ValueError("Event not found: bad-id"))
        result = await protect_get_event("bad-id")
        assert result["success"] is False
        assert "Event not found" in result["error"]

    @pytest.mark.asyncio
    async def test_error(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_get_event

        mock_event_manager.get_event = AsyncMock(side_effect=RuntimeError("api error"))
        result = await protect_get_event("evt-123")
        assert result["success"] is False
        assert "api error" in result["error"]


# ---------------------------------------------------------------------------
# protect_get_event_thumbnail
# ---------------------------------------------------------------------------


class TestProtectGetEventThumbnail:
    @pytest.mark.asyncio
    async def test_success(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_get_event_thumbnail

        mock_event_manager.get_event_thumbnail = AsyncMock(
            return_value={
                "event_id": "evt-1",
                "thumbnail_available": True,
                "image_base64": "base64data",
                "content_type": "image/jpeg",
            }
        )
        result = await protect_get_event_thumbnail("evt-1")
        assert result["success"] is True
        assert result["data"]["thumbnail_available"] is True

    @pytest.mark.asyncio
    async def test_with_dimensions(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_get_event_thumbnail

        mock_event_manager.get_event_thumbnail = AsyncMock(
            return_value={"event_id": "evt-1", "thumbnail_available": True}
        )
        await protect_get_event_thumbnail("evt-1", width=320, height=240)
        mock_event_manager.get_event_thumbnail.assert_awaited_once_with("evt-1", width=320, height=240)

    @pytest.mark.asyncio
    async def test_not_found(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_get_event_thumbnail

        mock_event_manager.get_event_thumbnail = AsyncMock(side_effect=ValueError("Event not found"))
        result = await protect_get_event_thumbnail("bad-id")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_error(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_get_event_thumbnail

        mock_event_manager.get_event_thumbnail = AsyncMock(side_effect=RuntimeError("fail"))
        result = await protect_get_event_thumbnail("evt-1")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# protect_list_smart_detections
# ---------------------------------------------------------------------------


class TestProtectListSmartDetections:
    @pytest.mark.asyncio
    async def test_success(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_list_smart_detections

        mock_event_manager.list_smart_detections = AsyncMock(
            return_value=[
                {
                    "id": "sd-1",
                    "type": "smartDetectZone",
                    "score": 90,
                    "smart_detect_types": ["face"],
                    "recognized_person_id": "face-group-1",
                    "recognized_person_name": "Assigned Person",
                },
            ]
        )
        result = await protect_list_smart_detections()
        assert result["success"] is True
        assert result["data"]["count"] == 1
        assert result["data"]["detections"][0]["recognized_person_id"] == "face-group-1"

    @pytest.mark.asyncio
    async def test_with_filters(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_list_smart_detections

        mock_event_manager.list_smart_detections = AsyncMock(return_value=[])
        result = await protect_list_smart_detections(
            detection_type="person",
            camera_id="cam-001",
            min_confidence=80,
            limit=5,
        )
        assert result["success"] is True
        call_kwargs = mock_event_manager.list_smart_detections.call_args.kwargs
        assert call_kwargs["detection_type"] == "person"
        assert call_kwargs["camera_id"] == "cam-001"
        assert call_kwargs["min_confidence"] == 80
        assert call_kwargs["limit"] == 5

    @pytest.mark.asyncio
    async def test_error(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_list_smart_detections

        mock_event_manager.list_smart_detections = AsyncMock(side_effect=RuntimeError("fail"))
        result = await protect_list_smart_detections()
        assert result["success"] is False


# ---------------------------------------------------------------------------
# protect_recent_events
# ---------------------------------------------------------------------------


class TestProtectRecentEvents:
    @pytest.mark.asyncio
    async def test_success(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_recent_events

        mock_event_manager.get_recent_from_buffer.return_value = [
            {"id": "evt-1", "type": "motion", "recognized_person_name": "Assigned Person"},
            {"id": "evt-2", "type": "ring"},
        ]
        mock_event_manager.buffer_size = 10
        result = await protect_recent_events()
        assert result["success"] is True
        assert result["data"]["count"] == 2
        assert result["data"]["source"] == "websocket_buffer"
        assert result["data"]["buffer_size"] == 10
        assert result["data"]["events"][0]["recognized_person_name"] == "Assigned Person"

    @pytest.mark.asyncio
    async def test_with_filters(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_recent_events

        mock_event_manager.get_recent_from_buffer.return_value = []
        mock_event_manager.buffer_size = 0
        result = await protect_recent_events(event_type="motion", camera_id="cam-001", min_confidence=60, limit=5)
        assert result["success"] is True
        mock_event_manager.get_recent_from_buffer.assert_called_once_with(
            event_type="motion",
            camera_id="cam-001",
            min_confidence=60,
            limit=5,
        )

    @pytest.mark.asyncio
    async def test_empty_buffer(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_recent_events

        mock_event_manager.get_recent_from_buffer.return_value = []
        mock_event_manager.buffer_size = 0
        result = await protect_recent_events()
        assert result["success"] is True
        assert result["data"]["count"] == 0

    @pytest.mark.asyncio
    async def test_error(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_recent_events

        mock_event_manager.get_recent_from_buffer.side_effect = RuntimeError("buffer error")
        result = await protect_recent_events()
        assert result["success"] is False
        assert "buffer error" in result["error"]


# ---------------------------------------------------------------------------
# protect_subscribe_events
# ---------------------------------------------------------------------------


class TestProtectSubscribeEvents:
    @pytest.mark.asyncio
    async def test_returns_instructions(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_subscribe_events

        mock_event_manager.buffer_size = 5
        result = await protect_subscribe_events()
        assert result["success"] is True
        assert "protect://events/stream" in result["data"]["resource_uri"]
        assert "protect://events/stream/summary" in result["data"]["summary_uri"]
        assert "instructions" in result["data"]
        assert result["data"]["buffer_size"] == 5


# ---------------------------------------------------------------------------
# protect_acknowledge_event
# ---------------------------------------------------------------------------


class TestProtectAcknowledgeEvent:
    @pytest.mark.asyncio
    async def test_preview(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_acknowledge_event

        mock_event_manager.acknowledge_event = AsyncMock(
            return_value={
                "event_id": "evt-1",
                "type": "motion",
                "camera_id": "cam-001",
                "current_is_favorite": False,
                "proposed_is_favorite": True,
            }
        )
        result = await protect_acknowledge_event("evt-1", confirm=False)
        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["action"] == "acknowledge"
        assert result["preview"]["current"]["is_favorite"] is False
        assert result["preview"]["proposed"]["is_favorite"] is True

    @pytest.mark.asyncio
    async def test_confirm(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_acknowledge_event

        mock_event_manager.acknowledge_event = AsyncMock(
            return_value={
                "event_id": "evt-1",
                "type": "motion",
                "camera_id": "cam-001",
                "current_is_favorite": False,
                "proposed_is_favorite": True,
            }
        )
        mock_event_manager.apply_acknowledge_event = AsyncMock(
            return_value={"event_id": "evt-1", "acknowledged": True, "is_favorite": True}
        )
        result = await protect_acknowledge_event("evt-1", confirm=True)
        assert result["success"] is True
        assert result["data"]["acknowledged"] is True

    @pytest.mark.asyncio
    async def test_not_found(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_acknowledge_event

        mock_event_manager.acknowledge_event = AsyncMock(side_effect=ValueError("Event not found: bad-id"))
        result = await protect_acknowledge_event("bad-id", confirm=False)
        assert result["success"] is False
        assert "Event not found" in result["error"]

    @pytest.mark.asyncio
    async def test_error(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_acknowledge_event

        mock_event_manager.acknowledge_event = AsyncMock(side_effect=RuntimeError("api error"))
        result = await protect_acknowledge_event("evt-1", confirm=False)
        assert result["success"] is False
        assert "api error" in result["error"]


# ---------------------------------------------------------------------------
# _parse_datetime helper
# ---------------------------------------------------------------------------


class TestParseDatetime:
    def test_valid_iso(self):
        from unifi_protect_mcp.tools.events import _parse_datetime

        dt = _parse_datetime("2026-03-16T12:00:00Z")
        assert dt is not None
        assert dt.year == 2026
        assert dt.tzinfo is not None

    def test_valid_iso_with_offset(self):
        from unifi_protect_mcp.tools.events import _parse_datetime

        dt = _parse_datetime("2026-03-16T12:00:00+05:00")
        assert dt is not None

    def test_naive_datetime_gets_utc(self):
        from unifi_protect_mcp.tools.events import _parse_datetime

        dt = _parse_datetime("2026-03-16T12:00:00")
        assert dt is not None
        assert dt.tzinfo is not None  # UTC added

    def test_none_returns_none(self):
        from unifi_protect_mcp.tools.events import _parse_datetime

        assert _parse_datetime(None) is None

    def test_empty_string_returns_none(self):
        from unifi_protect_mcp.tools.events import _parse_datetime

        assert _parse_datetime("") is None

    def test_invalid_returns_none(self):
        from unifi_protect_mcp.tools.events import _parse_datetime

        assert _parse_datetime("not-a-date") is None
