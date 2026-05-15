"""Tests for event stream MCP resources."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_event_manager():
    """Patch event_manager in the resources module."""
    mgr = MagicMock()
    with patch("unifi_protect_mcp.resources.events.event_manager", mgr):
        yield mgr


# ---------------------------------------------------------------------------
# protect://events/stream
# ---------------------------------------------------------------------------


class TestEventStreamResource:
    @pytest.mark.asyncio
    async def test_returns_json_array(self, mock_event_manager):
        from unifi_protect_mcp.resources.events import event_stream

        mock_event_manager.get_recent_from_buffer.return_value = [
            {"id": "evt-1", "type": "motion", "camera_id": "cam-001", "score": 85},
            {"id": "evt-2", "type": "smartDetectZone", "camera_id": "cam-002", "score": 92},
        ]
        result = await event_stream()
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["id"] == "evt-1"
        assert data[1]["id"] == "evt-2"

    @pytest.mark.asyncio
    async def test_empty_buffer(self, mock_event_manager):
        from unifi_protect_mcp.resources.events import event_stream

        mock_event_manager.get_recent_from_buffer.return_value = []
        result = await event_stream()
        data = json.loads(result)
        assert data == []

    @pytest.mark.asyncio
    async def test_error_returns_json_error(self, mock_event_manager):
        from unifi_protect_mcp.resources.events import event_stream

        mock_event_manager.get_recent_from_buffer.side_effect = RuntimeError("buffer broken")
        result = await event_stream()
        data = json.loads(result)
        assert "error" in data
        assert "buffer broken" in data["error"]

    @pytest.mark.asyncio
    async def test_registered_with_mcp_resource_metadata(self):
        import unifi_protect_mcp.resources.events  # noqa: F401
        from unifi_protect_mcp.runtime import server

        resources = await server.list_resources()
        stream = next(r for r in resources if str(r.uri) == "protect://events/stream")

        assert stream.title == "Recent Protect Events"
        assert stream.annotations is not None
        assert stream.annotations.audience == ["user", "assistant"]
        assert stream.annotations.priority == 0.8
        assert stream.meta == {
            "io.unifi.resourceKind": "event-buffer",
            "io.unifi.updateMode": "poll",
            "io.unifi.pollIntervalMs": 1000,
            "io.unifi.protocolSubscribe": False,
            "io.unifi.relatedTools": ["protect_recent_events", "protect_subscribe_events"],
        }

    @pytest.mark.asyncio
    async def test_server_read_resource_returns_json_content(self, mock_event_manager):
        import unifi_protect_mcp.resources.events  # noqa: F401
        from unifi_protect_mcp.runtime import server

        mock_event_manager.get_recent_from_buffer.return_value = [{"id": "evt-1", "type": "motion"}]

        contents = await server.read_resource("protect://events/stream")

        assert len(contents) == 1
        assert contents[0].mime_type == "application/json"
        assert json.loads(contents[0].content) == [{"id": "evt-1", "type": "motion"}]
        assert contents[0].meta["io.unifi.resourceKind"] == "event-buffer"


# ---------------------------------------------------------------------------
# protect://events/stream/summary
# ---------------------------------------------------------------------------


class TestEventStreamSummaryResource:
    @pytest.mark.asyncio
    async def test_summary_counts(self, mock_event_manager):
        from unifi_protect_mcp.resources.events import event_stream_summary

        mock_event_manager.get_recent_from_buffer.return_value = [
            {"type": "motion", "camera_id": "cam-001"},
            {"type": "motion", "camera_id": "cam-001"},
            {"type": "smartDetectZone", "camera_id": "cam-002"},
        ]
        mock_event_manager.buffer_size = 3
        result = await event_stream_summary()
        data = json.loads(result)
        assert data["total_events"] == 3
        assert data["by_type"]["motion"] == 2
        assert data["by_type"]["smartDetectZone"] == 1
        assert data["by_camera"]["cam-001"] == 2
        assert data["by_camera"]["cam-002"] == 1
        assert data["buffer_size"] == 3

    @pytest.mark.asyncio
    async def test_empty_summary(self, mock_event_manager):
        from unifi_protect_mcp.resources.events import event_stream_summary

        mock_event_manager.get_recent_from_buffer.return_value = []
        mock_event_manager.buffer_size = 0
        result = await event_stream_summary()
        data = json.loads(result)
        assert data["total_events"] == 0
        assert data["by_type"] == {}
        assert data["by_camera"] == {}

    @pytest.mark.asyncio
    async def test_summary_error(self, mock_event_manager):
        from unifi_protect_mcp.resources.events import event_stream_summary

        mock_event_manager.get_recent_from_buffer.side_effect = RuntimeError("fail")
        result = await event_stream_summary()
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_missing_fields_handled(self, mock_event_manager):
        from unifi_protect_mcp.resources.events import event_stream_summary

        mock_event_manager.get_recent_from_buffer.return_value = [
            {"type": "motion"},  # no camera_id
            {},  # no type, no camera_id
        ]
        mock_event_manager.buffer_size = 2
        result = await event_stream_summary()
        data = json.loads(result)
        assert data["total_events"] == 2
        assert data["by_type"]["motion"] == 1
        assert data["by_type"]["unknown"] == 1
        assert data["by_camera"]["unknown"] == 2

    @pytest.mark.asyncio
    async def test_summary_registered_with_mcp_resource_metadata(self):
        import unifi_protect_mcp.resources.events  # noqa: F401
        from unifi_protect_mcp.runtime import server

        resources = await server.list_resources()
        summary = next(r for r in resources if str(r.uri) == "protect://events/stream/summary")

        assert summary.title == "Protect Event Buffer Summary"
        assert summary.annotations is not None
        assert summary.annotations.audience == ["assistant"]
        assert summary.annotations.priority == 0.5
        assert summary.meta == {
            "io.unifi.resourceKind": "event-summary",
            "io.unifi.updateMode": "poll",
            "io.unifi.pollIntervalMs": 1000,
            "io.unifi.protocolSubscribe": False,
            "io.unifi.relatedTools": ["protect_recent_events", "protect_subscribe_events"],
        }
