"""Tests for unifi_subscribe_events and unifi_recent_events MCP tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_event_manager():
    """Patch the network event_manager singleton accessor."""
    mgr = MagicMock()
    with patch(
        "unifi_network_mcp.tools.events._get_event_manager",
        return_value=mgr,
    ):
        yield mgr


class TestUnifiRecentEvents:
    @pytest.mark.asyncio
    async def test_unifi_recent_events_returns_buffered(self, mock_event_manager):
        from unifi_network_mcp.tools.events import unifi_recent_events

        mock_event_manager.get_recent_from_buffer.return_value = [
            {"key": "EVT_WU_Connected", "msg": "client x connected"},
            {"key": "EVT_WU_Disconnected", "msg": "client x disconnected"},
        ]
        mock_event_manager.buffer_size = 7

        result = await unifi_recent_events()

        assert result["count"] == 2
        assert result["buffer_size"] == 7
        assert len(result["events"]) == 2

    @pytest.mark.asyncio
    async def test_unifi_recent_events_passes_filters(self, mock_event_manager):
        from unifi_network_mcp.tools.events import unifi_recent_events

        mock_event_manager.get_recent_from_buffer.return_value = []
        mock_event_manager.buffer_size = 0

        await unifi_recent_events(event_type="EVT_WU_", mac="aa:bb:cc:dd:ee:ff", limit=5)

        mock_event_manager.get_recent_from_buffer.assert_called_once_with(
            event_type="EVT_WU_",
            mac="aa:bb:cc:dd:ee:ff",
            limit=5,
        )


class TestListenerState:
    @pytest.mark.asyncio
    async def test_recent_events_reports_a_running_listener(self, mock_event_manager):
        from unifi_network_mcp.tools.events import unifi_recent_events

        mock_event_manager.get_recent_from_buffer.return_value = []
        mock_event_manager.buffer_size = 0
        mock_event_manager.buffer_capacity = 100
        mock_event_manager.is_listening = True
        mock_event_manager.attached = True
        mock_event_manager.last_error = None

        result = await unifi_recent_events()

        assert result["success"] is True
        assert result["listening"] is True
        assert result["attached"] is True
        assert result["buffer_capacity"] == 100
        assert "hint" not in result

    @pytest.mark.asyncio
    async def test_recent_events_hints_when_the_listener_is_not_running(self, mock_event_manager):
        """An empty buffer with no listener is not "no events"; say so."""
        from unifi_network_mcp.tools.events import unifi_recent_events

        mock_event_manager.get_recent_from_buffer.return_value = []
        mock_event_manager.buffer_size = 0
        mock_event_manager.buffer_capacity = 100
        mock_event_manager.is_listening = False

        result = await unifi_recent_events()

        assert result["listening"] is False
        assert "UNIFI_NETWORK_WEBSOCKET_ENABLED" in result["hint"]
        assert "unifi_list_events" in result["hint"]

    @pytest.mark.asyncio
    async def test_recent_events_hints_when_the_listener_never_attached(self, mock_event_manager):
        from unifi_network_mcp.tools.events import unifi_recent_events

        mock_event_manager.get_recent_from_buffer.return_value = []
        mock_event_manager.buffer_size = 0
        mock_event_manager.buffer_capacity = 100
        mock_event_manager.is_listening = True
        mock_event_manager.attached = False
        mock_event_manager.last_error = "WSServerHandshakeError (HTTP 404)"

        result = await unifi_recent_events()

        assert result["listening"] is True
        assert result["attached"] is False
        assert result["last_error"] == "WSServerHandshakeError (HTTP 404)"
        assert "has not attached" in result["hint"]

    def test_tools_and_main_share_one_event_manager(self):
        from unifi_network_mcp import runtime
        from unifi_network_mcp.tools import events

        assert events._get_event_manager() is runtime.event_manager

    @pytest.mark.asyncio
    async def test_subscribe_events_reports_listener_state(self, mock_event_manager):
        from unifi_network_mcp.tools.events import unifi_subscribe_events

        mock_event_manager.buffer_size = 0
        mock_event_manager.buffer_capacity = 100
        mock_event_manager.is_listening = False

        result = await unifi_subscribe_events()

        assert result["success"] is True
        assert result["listening"] is False
        assert result["buffer_capacity"] == 100
        assert "hint" in result


class TestUnifiSubscribeEvents:
    @pytest.mark.asyncio
    async def test_unifi_subscribe_events_returns_handle_dict(self, mock_event_manager):
        from unifi_network_mcp.tools.events import unifi_subscribe_events

        mock_event_manager.buffer_size = 12
        result = await unifi_subscribe_events()

        assert result["resource_uri"] == "unifi://network/events"
        assert result["summary_uri"] == "unifi://network/events/recent"
        assert result["buffer_size"] == 12
        assert "instructions" in result
