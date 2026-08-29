"""Tests for the EventManager class.

Tests both the v2 system-log API (modern controllers) and the legacy
/stat/event API (older controllers).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestEventManagerV2:
    """Tests for the EventManager using the v2 system-log API."""

    @pytest.fixture
    def mock_connection(self):
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        return conn

    @pytest.fixture
    def event_manager(self, mock_connection):
        from unifi_core.network.managers.event_manager import EventManager

        mgr = EventManager(mock_connection)
        mgr._use_v2 = True  # Force v2 mode
        return mgr

    @pytest.mark.asyncio
    async def test_get_events_returns_list(self, event_manager, mock_connection):
        mock_connection.request.return_value = [
            {
                "data": [
                    {"id": "evt1", "event": "CLIENT_CONNECTED_WIRED", "category": "CLIENT_DEVICES"},
                    {"id": "evt2", "event": "CLIENT_DISCONNECTED_WIRELESS", "category": "CLIENT_DEVICES"},
                ],
                "total_element_count": 2,
            }
        ]
        events = await event_manager.get_events(within=24, limit=100)
        assert len(events) == 2
        assert events[0]["id"] == "evt1"

    @pytest.mark.asyncio
    async def test_get_events_with_exact_event_key(self, event_manager, mock_connection):
        mock_connection.request.return_value = [{"data": [], "total_element_count": 0}]
        await event_manager.get_events(event_type="CLIENT_CONNECTED_WIRELESS_2")
        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.data["keys"] == ["CLIENT_CONNECTED_WIRELESS_2"]
        assert api_request.data["searchText"] == ""

    @pytest.mark.asyncio
    async def test_get_events_paginates_past_v2_page_size_cap(self, event_manager, mock_connection):
        first_page = [{"id": f"evt{i}"} for i in range(100)]
        second_page = [{"id": f"evt{i}"} for i in range(100, 150)]
        mock_connection.request.side_effect = [
            [{"data": first_page, "total_page_count": 2}],
            [{"data": second_page, "total_page_count": 2}],
        ]

        events = await event_manager.get_events(limit=150)

        assert len(events) == 150
        requests = [call.args[0] for call in mock_connection.request.call_args_list]
        assert [request.data["pageNumber"] for request in requests] == [0, 1]
        assert all(request.data["pageSize"] == 100 for request in requests)

    @pytest.mark.asyncio
    async def test_get_events_applies_arbitrary_start_across_pages(self, event_manager, mock_connection):
        mock_connection.request.side_effect = [
            [{"data": [{"id": f"evt{i}"} for i in range(100, 110)], "total_page_count": 12}],
            [{"data": [{"id": f"evt{i}"} for i in range(110, 120)], "total_page_count": 12}],
        ]

        events = await event_manager.get_events(limit=10, start=105)

        assert [event["id"] for event in events] == [f"evt{i}" for i in range(105, 115)]
        requests = [call.args[0] for call in mock_connection.request.call_args_list]
        assert [request.data["pageNumber"] for request in requests] == [10, 11]

    @pytest.mark.asyncio
    async def test_get_events_zero_limit_makes_no_request(self, event_manager, mock_connection):
        assert await event_manager.get_events(limit=0) == []
        mock_connection.request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_events_uses_timestamp_range(self, event_manager, mock_connection):
        mock_connection.request.return_value = [{"data": [], "total_element_count": 0}]
        await event_manager.get_events(within=48)
        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert "timestampFrom" in api_request.data
        assert "timestampTo" in api_request.data
        assert api_request.data["timestampTo"] > api_request.data["timestampFrom"]

    @pytest.mark.asyncio
    async def test_get_events_handles_error(self, event_manager, mock_connection):
        mock_connection.request.side_effect = Exception("Network error")

        with pytest.raises(Exception):
            await event_manager.get_events()

    @pytest.mark.asyncio
    async def test_get_alarms_v2(self, event_manager, mock_connection):
        mock_connection.request.return_value = [
            {
                "data": [
                    {"id": "alm1", "event": "THREAT_DETECTED", "severity": "VERY_HIGH"},
                ],
                "total_element_count": 1,
            }
        ]
        alarms = await event_manager.get_alarms()
        assert len(alarms) == 1
        assert alarms[0]["severity"] == "VERY_HIGH"

    @pytest.mark.asyncio
    async def test_get_alarms_v2_limit(self, event_manager, mock_connection):
        mock_data = [{"id": f"alm{i}"} for i in range(200)]
        mock_connection.request.return_value = [{"data": mock_data, "total_element_count": 200}]
        alarms = await event_manager.get_alarms(limit=50)
        assert len(alarms) == 50


class TestEventManagerLegacy:
    """Tests for the EventManager using the legacy /stat/event API."""

    @pytest.fixture
    def mock_connection(self):
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        return conn

    @pytest.fixture
    def event_manager(self, mock_connection):
        from unifi_core.network.managers.event_manager import EventManager

        mgr = EventManager(mock_connection)
        mgr._use_v2 = False  # Force legacy mode
        return mgr

    @pytest.mark.asyncio
    async def test_get_events_returns_list(self, event_manager, mock_connection):
        mock_events = [
            {"_id": "evt1", "msg": "Client connected", "time": 1700000000},
            {"_id": "evt2", "msg": "Client disconnected", "time": 1700000100},
        ]
        mock_connection.request.return_value = mock_events
        events = await event_manager.get_events(within=24, limit=100)
        assert len(events) == 2
        assert events[0]["_id"] == "evt1"

    @pytest.mark.asyncio
    async def test_get_events_with_type_filter(self, event_manager, mock_connection):
        mock_connection.request.return_value = []
        await event_manager.get_events(event_type="EVT_SW_Connected")
        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.data["type"] == "EVT_SW_Connected"

    @pytest.mark.asyncio
    async def test_get_events_respects_limit(self, event_manager, mock_connection):
        mock_connection.request.return_value = []
        await event_manager.get_events(limit=5000)
        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.data["_limit"] == 3000

    @pytest.mark.asyncio
    async def test_get_events_handles_dict_response(self, event_manager, mock_connection):
        mock_connection.request.return_value = {"data": [{"_id": "evt1"}], "meta": {"rc": "ok"}}
        events = await event_manager.get_events()
        assert len(events) == 1
        assert events[0]["_id"] == "evt1"

    @pytest.mark.asyncio
    async def test_get_events_handles_error(self, event_manager, mock_connection):
        mock_connection.request.side_effect = Exception("Network error")

        with pytest.raises(Exception):
            await event_manager.get_events()

    @pytest.mark.asyncio
    async def test_get_alarms_returns_list(self, event_manager, mock_connection):
        mock_alarms = [
            {"_id": "alm1", "msg": "High CPU usage", "severity": "warning"},
            {"_id": "alm2", "msg": "Device offline", "severity": "critical"},
        ]
        mock_connection.request.return_value = mock_alarms
        alarms = await event_manager.get_alarms()
        assert len(alarms) == 2

    @pytest.mark.asyncio
    async def test_get_alarms_archived_parameter(self, event_manager, mock_connection):
        mock_connection.request.return_value = []
        await event_manager.get_alarms(archived=True)
        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert "archived=true" in api_request.path

    @pytest.mark.asyncio
    async def test_get_alarms_limit(self, event_manager, mock_connection):
        mock_alarms = [{"_id": f"alm{i}"} for i in range(200)]
        mock_connection.request.return_value = mock_alarms
        alarms = await event_manager.get_alarms(limit=50)
        assert len(alarms) == 50


class TestEventManagerCommon:
    """Tests for shared EventManager functionality."""

    @pytest.fixture
    def mock_connection(self):
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        return conn

    @pytest.fixture
    def event_manager(self, mock_connection):
        from unifi_core.network.managers.event_manager import EventManager

        return EventManager(mock_connection)

    @pytest.mark.asyncio
    async def test_get_event_type_prefixes_returns_observed_exact_keys(self, event_manager, mock_connection):
        event_manager._use_v2 = True
        mock_connection.request.return_value = [
            {
                "data": [
                    {"key": "CLIENT_DISCONNECTED_WIRELESS_2"},
                    {"key": "CLIENT_CONNECTED_WIRELESS_2"},
                    {"key": "CLIENT_DISCONNECTED_WIRELESS_2"},
                    {"key": None},
                ]
            }
        ]

        event_types = await event_manager.get_event_type_prefixes()

        assert [event_type["key"] for event_type in event_types] == [
            "CLIENT_CONNECTED_WIRELESS_2",
            "CLIENT_DISCONNECTED_WIRELESS_2",
        ]
        assert event_types[1]["prefix"] == "CLIENT_DISCONNECTED_WIRELESS_2"
        assert event_types[1]["observed_count"] == 2
        assert all("description" in event_type for event_type in event_types)

    def test_get_event_categories(self, event_manager):
        categories = event_manager.get_event_categories()
        assert len(categories) > 0
        assert any(c["category"] == "SECURITY" for c in categories)
        assert all("description" in c for c in categories)

    @pytest.mark.asyncio
    async def test_archive_alarm_success(self, event_manager, mock_connection):
        mock_connection.request.return_value = {}
        result = await event_manager.archive_alarm("alarm123")
        assert result is True
        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.data["cmd"] == "archive-alarm"

    @pytest.mark.asyncio
    async def test_archive_alarm_failure(self, event_manager, mock_connection):
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await event_manager.archive_alarm("alarm123")

    @pytest.mark.asyncio
    async def test_archive_all_alarms_success(self, event_manager, mock_connection):
        mock_connection.request.return_value = {}
        result = await event_manager.archive_all_alarms()
        assert result is True

    @pytest.mark.asyncio
    async def test_archive_all_alarms_failure(self, event_manager, mock_connection):
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await event_manager.archive_all_alarms()

    @pytest.mark.asyncio
    async def test_auto_detect_v2(self, event_manager, mock_connection):
        """Test that v2 API is detected when system-log/count succeeds."""
        mock_connection.request.return_value = {"count": 100}
        await event_manager._ensure_api_version()
        assert event_manager._use_v2 is True

    @pytest.mark.asyncio
    async def test_auto_detect_legacy(self, event_manager, mock_connection):
        """Test that legacy API is used when system-log/count fails."""
        mock_connection.request.side_effect = Exception("404")
        await event_manager._ensure_api_version()
        assert event_manager._use_v2 is False

    @pytest.mark.asyncio
    async def test_failed_probe_is_logged_with_the_actual_error(self, event_manager, mock_connection, caplog):
        """The probe error must reach the log, or a later 404 is undiagnosable."""
        mock_connection.request.side_effect = Exception("Bad Request: unknown severity LOW")

        with caplog.at_level("WARNING"):
            await event_manager._ensure_api_version()

        assert event_manager._use_v2 is False
        assert "unknown severity LOW" in caplog.text

    @pytest.mark.asyncio
    async def test_failed_probe_is_recorded_for_later_diagnosis(self, event_manager, mock_connection):
        mock_connection.request.side_effect = Exception("Bad Request: unknown severity LOW")
        await event_manager._ensure_api_version()
        assert "unknown severity LOW" in event_manager._v2_probe_error

    @pytest.mark.asyncio
    async def test_successful_probe_records_no_error(self, event_manager, mock_connection):
        mock_connection.request.return_value = {"count": 1}
        await event_manager._ensure_api_version()
        assert event_manager._v2_probe_error is None

    @pytest.mark.asyncio
    async def test_legacy_events_404_after_failed_probe_explains_both(self, event_manager, mock_connection):
        """A 404 from a legacy path we only chose because v2 probing failed is not a bare 404."""
        mock_connection.request.side_effect = [
            Exception("Bad Request: unknown severity LOW"),  # v2 probe
            Exception("received 404 Not Found"),  # legacy /stat/event
        ]

        with pytest.raises(Exception) as exc:
            await event_manager.get_events()

        message = str(exc.value)
        assert "404" in message
        assert "unknown severity LOW" in message, "the v2 probe failure must be surfaced, not swallowed"

    @pytest.mark.asyncio
    async def test_legacy_alarms_404_after_failed_probe_explains_both(self, event_manager, mock_connection):
        mock_connection.request.side_effect = [
            Exception("Bad Request: unknown severity LOW"),  # v2 probe
            Exception("received 404 Not Found"),  # legacy /stat/alarm
        ]

        with pytest.raises(Exception) as exc:
            await event_manager.get_alarms()

        assert "unknown severity LOW" in str(exc.value)

    @pytest.mark.asyncio
    async def test_legacy_failure_on_a_genuinely_old_controller_is_left_alone(self, event_manager, mock_connection):
        """No probe error recorded means legacy was a real choice — do not editorialise."""
        event_manager._use_v2 = False
        event_manager._v2_probe_error = None
        mock_connection.request.side_effect = Exception("connection reset")

        with pytest.raises(Exception) as exc:
            await event_manager.get_events()

        assert "connection reset" in str(exc.value)
        assert "v2 system-log probe" not in str(exc.value)
