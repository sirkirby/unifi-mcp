"""Tests for EventManager and event tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unifi_core.access.managers.connection_manager import AccessConnectionManager
from unifi_core.access.managers.event_manager import EventBuffer, EventManager
from unifi_core.exceptions import UniFiConnectionError, UniFiNotFoundError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cm_proxy():
    """ConnectionManager with proxy available."""
    cm = AccessConnectionManager(host="192.168.1.1", username="admin", password="secret")
    cm._proxy_available = True
    cm._proxy_session = MagicMock()
    return cm


@pytest.fixture
def cm_api():
    """ConnectionManager with API client available."""
    cm = AccessConnectionManager(host="192.168.1.1", username="", password="", api_key="test-key")
    cm._api_client_available = True
    cm._api_client = AsyncMock()
    return cm


@pytest.fixture
def cm_none():
    """ConnectionManager with no auth paths."""
    return AccessConnectionManager(host="192.168.1.1", username="", password="")


@pytest.fixture
def event_mgr_proxy(cm_proxy):
    return EventManager(cm_proxy)


@pytest.fixture
def event_mgr_api(cm_api):
    return EventManager(cm_api)


@pytest.fixture
def event_mgr_none(cm_none):
    return EventManager(cm_none)


# ---------------------------------------------------------------------------
# EventBuffer tests (extending existing scaffold tests)
# ---------------------------------------------------------------------------


class TestEventBufferExtended:
    def test_buffer_max_size(self):
        """Buffer respects max_size limit."""
        buf = EventBuffer(max_size=3, ttl_seconds=300)
        for i in range(5):
            buf.add({"type": "test", "seq": i})
        assert len(buf) == 3
        # Newest events should be kept
        events = buf.get_recent()
        assert events[0]["seq"] == 4
        assert events[-1]["seq"] == 2

    def test_buffer_ttl_expiration(self):
        """Buffer skips events older than TTL."""
        buf = EventBuffer(max_size=10, ttl_seconds=1)
        buf.add({"type": "old"})
        # Manually age the event
        buf._buffer[0]["_buffered_at"] = 0
        events = buf.get_recent()
        assert len(events) == 0


# ---------------------------------------------------------------------------
# EventManager buffer access
# ---------------------------------------------------------------------------


class TestEventManagerBuffer:
    def test_get_recent_from_buffer(self, event_mgr_proxy):
        """get_recent_from_buffer delegates to EventBuffer."""
        event_mgr_proxy._buffer.add({"type": "door_open", "door_id": "d1"})
        event_mgr_proxy._buffer.add({"type": "access_denied", "door_id": "d2"})

        events = event_mgr_proxy.get_recent_from_buffer()
        assert len(events) == 2

    def test_get_recent_from_buffer_with_filters(self, event_mgr_proxy):
        """get_recent_from_buffer supports filters."""
        event_mgr_proxy._buffer.add({"type": "door_open", "door_id": "d1"})
        event_mgr_proxy._buffer.add({"type": "access_denied", "door_id": "d2"})

        events = event_mgr_proxy.get_recent_from_buffer(event_type="door_open")
        assert len(events) == 1
        assert events[0]["type"] == "door_open"

    def test_buffer_size_property(self, event_mgr_proxy):
        """buffer_size returns count of buffered events."""
        assert event_mgr_proxy.buffer_size == 0
        event_mgr_proxy._buffer.add({"type": "test"})
        assert event_mgr_proxy.buffer_size == 1

    def test_set_server(self, event_mgr_proxy):
        """set_server stores server reference."""
        mock_server = MagicMock()
        event_mgr_proxy.set_server(mock_server)
        assert event_mgr_proxy._server is mock_server


# ---------------------------------------------------------------------------
# EventManager websocket lifecycle
# ---------------------------------------------------------------------------


class TestEventManagerWebsocket:
    @pytest.mark.asyncio
    async def test_start_listening_with_api_client(self, event_mgr_api, cm_api):
        """start_listening starts websocket via API client."""
        cm_api.start_websocket = MagicMock()
        await event_mgr_api.start_listening()
        cm_api.start_websocket.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_listening_without_api_client(self, event_mgr_proxy):
        """start_listening logs warning when no API client."""
        # Should not raise
        await event_mgr_proxy.start_listening()

    def test_on_event_dict(self, event_mgr_proxy):
        """_on_event buffers dict events."""
        event_mgr_proxy._on_event({"type": "door_open", "door_id": "d1"})
        assert event_mgr_proxy.buffer_size == 1

    def test_on_event_object(self, event_mgr_proxy):
        """_on_event converts object events to dict."""
        obj = MagicMock()
        obj.id = "evt-1"
        obj.type = "door_open"
        obj.door_id = "d1"
        obj.user_id = "u1"
        obj.timestamp = "2026-03-17T12:00:00Z"

        event_mgr_proxy._on_event(obj)
        assert event_mgr_proxy.buffer_size == 1
        events = event_mgr_proxy.get_recent_from_buffer()
        assert events[0]["id"] == "evt-1"


# ---------------------------------------------------------------------------
# EventManager REST queries
# ---------------------------------------------------------------------------


class TestEventManagerREST:
    @pytest.mark.asyncio
    async def test_list_events_proxy(self, event_mgr_proxy, cm_proxy):
        """list_events queries via proxy using POST to system_log/search with topic."""
        expected = [{"id": "evt-1", "type": "door_open"}]

        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": {"events": expected}}
            events = await event_mgr_proxy.list_events()

        assert events == expected
        mock_req.assert_awaited_once()
        call_args = mock_req.call_args
        assert call_args[0][0] == "POST"
        assert "insights/system_log/search" in call_args[0][1]
        assert "page_size=30" in call_args[0][1]
        assert "isAccess" in call_args[0][1]
        # Verify topic is included in request body
        assert call_args[1]["json"]["topic"] == "admin"

    @pytest.mark.asyncio
    async def test_list_events_with_filters(self, event_mgr_proxy, cm_proxy):
        """list_events passes filters and topic in the POST body."""
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": {"events": []}}
            await event_mgr_proxy.list_events(
                topic="admin_activity",
                door_id="d1",
                user_id="u1",
                start="2026-03-01",
                end="2026-03-17",
                limit=10,
            )

        call_args = mock_req.call_args
        body = call_args[1]["json"]
        assert body["topic"] == "admin_activity"
        assert body["door_id"] == "d1"
        assert body["user_id"] == "u1"
        assert body["start"] == "2026-03-01"
        assert body["end"] == "2026-03-17"
        assert "page_size=10" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_list_events_no_proxy(self, event_mgr_none):
        """list_events raises when no proxy available."""
        with pytest.raises(UniFiConnectionError, match="No proxy session"):
            await event_mgr_none.list_events()

    @pytest.mark.asyncio
    async def test_get_event_proxy(self, event_mgr_proxy, cm_proxy):
        """get_event searches across topics for a single event."""
        expected = {"id": "evt-1", "type": "door_open", "door_id": "d1"}

        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            # First topic returns the event
            mock_req.return_value = {"data": {"events": [expected]}}
            event = await event_mgr_proxy.get_event("evt-1")

        assert event == expected
        # Verify it uses POST to system_log/search with topic
        call_args = mock_req.call_args_list[0]
        assert call_args[0][0] == "POST"
        assert "insights/system_log/search" in call_args[0][1]
        assert call_args[1]["json"]["topic"] == "admin"

    @pytest.mark.asyncio
    async def test_get_event_not_found(self, event_mgr_proxy, cm_proxy):
        """get_event raises ValueError when event not found across all topics."""
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": {"events": []}}
            with pytest.raises(UniFiNotFoundError):
                await event_mgr_proxy.get_event("missing-evt")

    @pytest.mark.asyncio
    async def test_get_event_empty_id(self, event_mgr_proxy):
        """get_event raises ValueError for empty event_id."""
        with pytest.raises(ValueError, match="event_id is required"):
            await event_mgr_proxy.get_event("")

    @pytest.mark.asyncio
    async def test_get_event_no_proxy(self, event_mgr_none):
        """get_event raises when no proxy available."""
        with pytest.raises(UniFiConnectionError, match="No proxy session"):
            await event_mgr_none.get_event("evt-1")

    @pytest.mark.asyncio
    async def test_get_activity_summary(self, event_mgr_proxy, cm_proxy):
        """get_activity_summary queries the activities/histogram endpoint."""
        expected = {"total_events": 42, "by_type": {"door_open": 20, "access_denied": 22}}

        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": expected}
            summary = await event_mgr_proxy.get_activity_summary(door_id="d1", days=3)

        assert summary == expected
        call_args = mock_req.call_args
        # Verify it uses GET to activities/histogram
        assert call_args[0][0] == "GET"
        path = call_args[0][1]
        assert "activities/histogram" in path
        assert "since=" in path
        assert "until=" in path
        assert "interval=3600" in path
        assert "door_id=d1" in path

    @pytest.mark.asyncio
    async def test_get_activity_summary_default_days(self, event_mgr_proxy, cm_proxy):
        """get_activity_summary uses correct time range for default 7 days."""
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": {}}
            await event_mgr_proxy.get_activity_summary()

        path = mock_req.call_args[0][1]
        # The 'since' parameter should be approximately 7 days ago
        assert "since=" in path
        assert "until=" in path

    @pytest.mark.asyncio
    async def test_get_activity_summary_no_proxy(self, event_mgr_none):
        """get_activity_summary raises when no proxy available."""
        with pytest.raises(UniFiConnectionError, match="No proxy session"):
            await event_mgr_none.get_activity_summary()
