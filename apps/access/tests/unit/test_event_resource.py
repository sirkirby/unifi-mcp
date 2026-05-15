"""Tests for event stream MCP resources."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_event_manager():
    """Patch event_manager in the resources module."""
    mgr = MagicMock()
    with patch("unifi_access_mcp.resources.events.event_manager", mgr):
        yield mgr


class TestAccessEventStreamResource:
    @pytest.mark.asyncio
    async def test_returns_json_array(self, mock_event_manager):
        from unifi_access_mcp.resources.events import event_stream

        mock_event_manager.get_recent_from_buffer.return_value = [
            {"id": "evt-1", "type": "door_open", "door_id": "door-1"},
            {"id": "evt-2", "type": "access_denied", "door_id": "door-2"},
        ]

        result = await event_stream()

        data = json.loads(result)
        assert isinstance(data, list)
        assert data[0]["id"] == "evt-1"
        assert data[1]["type"] == "access_denied"

    @pytest.mark.asyncio
    async def test_registered_with_mcp_resource_metadata(self):
        import unifi_access_mcp.resources.events  # noqa: F401
        from unifi_access_mcp.runtime import server

        resources = await server.list_resources()
        stream = next(r for r in resources if str(r.uri) == "access://events/stream")

        assert stream.title == "Recent Access Events"
        assert stream.annotations is not None
        assert stream.annotations.audience == ["user", "assistant"]
        assert stream.annotations.priority == 0.8
        assert stream.meta == {
            "io.unifi.resourceKind": "event-buffer",
            "io.unifi.updateMode": "poll",
            "io.unifi.pollIntervalMs": 1000,
            "io.unifi.protocolSubscribe": False,
            "io.unifi.relatedTools": ["access_recent_events", "access_subscribe_events"],
        }

    @pytest.mark.asyncio
    async def test_server_read_resource_returns_json_content(self, mock_event_manager):
        import unifi_access_mcp.resources.events  # noqa: F401
        from unifi_access_mcp.runtime import server

        mock_event_manager.get_recent_from_buffer.return_value = [{"id": "evt-1", "type": "door_open"}]

        contents = await server.read_resource("access://events/stream")

        assert len(contents) == 1
        assert contents[0].mime_type == "application/json"
        assert json.loads(contents[0].content) == [{"id": "evt-1", "type": "door_open"}]
        assert contents[0].meta["io.unifi.resourceKind"] == "event-buffer"


class TestAccessEventStreamSummaryResource:
    @pytest.mark.asyncio
    async def test_summary_counts(self, mock_event_manager):
        from unifi_access_mcp.resources.events import event_stream_summary

        mock_event_manager.get_recent_from_buffer.return_value = [
            {"type": "door_open", "door_id": "door-1"},
            {"type": "door_open", "door_id": "door-1"},
            {"type": "access_denied", "door_id": "door-2"},
        ]
        mock_event_manager.buffer_size = 3

        result = await event_stream_summary()

        data = json.loads(result)
        assert data["total_events"] == 3
        assert data["by_type"]["door_open"] == 2
        assert data["by_door"]["door-1"] == 2
        assert data["buffer_size"] == 3

    @pytest.mark.asyncio
    async def test_summary_registered_with_mcp_resource_metadata(self):
        import unifi_access_mcp.resources.events  # noqa: F401
        from unifi_access_mcp.runtime import server

        resources = await server.list_resources()
        summary = next(r for r in resources if str(r.uri) == "access://events/stream/summary")

        assert summary.title == "Access Event Buffer Summary"
        assert summary.annotations is not None
        assert summary.annotations.audience == ["assistant"]
        assert summary.annotations.priority == 0.5
        assert summary.meta == {
            "io.unifi.resourceKind": "event-summary",
            "io.unifi.updateMode": "poll",
            "io.unifi.pollIntervalMs": 1000,
            "io.unifi.protocolSubscribe": False,
            "io.unifi.relatedTools": ["access_recent_events", "access_subscribe_events"],
        }
