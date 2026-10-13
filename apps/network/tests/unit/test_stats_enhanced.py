"""Tests for enhanced stats manager methods.

Tests granularity support, new report endpoints, live stat endpoints,
and device command methods (speedtest).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestStatsManagerEnhanced:
    """Tests for enhanced StatsManager methods."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock ConnectionManager."""
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        conn.get_cached = MagicMock(return_value=None)
        conn._update_cache = MagicMock()
        conn.ensure_connected = AsyncMock(return_value=True)
        conn.controller = MagicMock()
        return conn

    @pytest.fixture
    def mock_client_manager(self):
        """Create a mock ClientManager."""
        return MagicMock()

    @pytest.fixture
    def stats_manager(self, mock_connection, mock_client_manager):
        """Create a StatsManager with mocked dependencies."""
        from unifi_core.network.managers.stats_manager import StatsManager

        return StatsManager(mock_connection, mock_client_manager)

    # ---- Granularity on existing methods ----

    @pytest.mark.asyncio
    async def test_get_network_stats_default_granularity(self, stats_manager, mock_connection):
        """Test get_network_stats uses hourly.site by default."""
        mock_connection.request.return_value = []

        await stats_manager.get_network_stats()

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/stat/report/hourly.site"

    @pytest.mark.asyncio
    async def test_get_network_stats_5min_granularity(self, stats_manager, mock_connection):
        """Test get_network_stats uses 5minutes.site endpoint."""
        mock_connection.request.return_value = []

        await stats_manager.get_network_stats(granularity="5minutes")

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/stat/report/5minutes.site"

    @pytest.mark.asyncio
    async def test_get_network_stats_daily_granularity(self, stats_manager, mock_connection):
        """Test get_network_stats uses daily.site endpoint."""
        mock_connection.request.return_value = []

        await stats_manager.get_network_stats(granularity="daily")

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/stat/report/daily.site"

    @pytest.mark.asyncio
    async def test_get_network_stats_monthly_granularity(self, stats_manager, mock_connection):
        """Test get_network_stats uses monthly.site endpoint."""
        mock_connection.request.return_value = []

        await stats_manager.get_network_stats(granularity="monthly")

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/stat/report/monthly.site"

    @pytest.mark.asyncio
    async def test_get_network_stats_invalid_granularity(self, stats_manager):
        """Test get_network_stats rejects invalid granularity."""
        with pytest.raises(ValueError, match="Invalid granularity"):
            await stats_manager.get_network_stats(granularity="invalid")

    @pytest.mark.asyncio
    async def test_get_network_stats_includes_wan_attrs(self, stats_manager, mock_connection):
        """Test get_network_stats requests WAN breakdown attrs."""
        mock_connection.request.return_value = []

        await stats_manager.get_network_stats()

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        attrs = api_request.data["attrs"]
        assert "wan-rx_bytes" in attrs
        assert "wan-tx_bytes" in attrs

    @pytest.mark.asyncio
    async def test_get_client_stats_uses_user_endpoint(self, stats_manager, mock_connection):
        """Test get_client_stats uses .user endpoint (not .sta)."""
        mock_connection.request.return_value = []

        await stats_manager.get_client_stats("aa:bb:cc:dd:ee:ff")

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/stat/report/hourly.user"

    @pytest.mark.asyncio
    async def test_get_client_stats_includes_wifi_attrs(self, stats_manager, mock_connection):
        """Test get_client_stats requests WiFi quality attrs."""
        mock_connection.request.return_value = []

        await stats_manager.get_client_stats("aa:bb:cc:dd:ee:ff")

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        attrs = api_request.data["attrs"]
        assert "signal" in attrs
        assert "satisfaction" in attrs
        assert "tx_retries" in attrs

    @pytest.mark.asyncio
    async def test_get_client_stats_5min_granularity(self, stats_manager, mock_connection):
        """Test get_client_stats with 5-minute granularity."""
        mock_connection.request.return_value = []

        await stats_manager.get_client_stats("aa:bb:cc:dd:ee:ff", granularity="5minutes")

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/stat/report/5minutes.user"

    @pytest.mark.asyncio
    async def test_get_device_stats_routes_ap(self, stats_manager, mock_connection):
        """Test get_device_stats uses .ap endpoint for APs."""
        mock_connection.request.return_value = []

        await stats_manager.get_device_stats("aa:bb:cc:dd:ee:ff", device_type="ap")

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/stat/report/hourly.ap"
        assert "satisfaction" in api_request.data["attrs"]

    @pytest.mark.asyncio
    async def test_get_device_stats_routes_gw(self, stats_manager, mock_connection):
        """Test get_device_stats uses .gw endpoint for gateways."""
        mock_connection.request.return_value = []

        await stats_manager.get_device_stats("aa:bb:cc:dd:ee:ff", device_type="gw")

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/stat/report/hourly.gw"
        assert "cpu" in api_request.data["attrs"]

    @pytest.mark.asyncio
    async def test_get_device_stats_defaults_to_dev(self, stats_manager, mock_connection):
        """Test get_device_stats defaults to .dev endpoint."""
        mock_connection.request.return_value = []

        await stats_manager.get_device_stats("aa:bb:cc:dd:ee:ff")

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/stat/report/hourly.dev"

    # ---- New report endpoints ----

    @pytest.mark.asyncio
    async def test_get_gateway_stats(self, stats_manager, mock_connection):
        """Test get_gateway_stats uses .gw endpoint."""
        mock_connection.request.return_value = [{"wan-rx_bytes": 1000}]

        result = await stats_manager.get_gateway_stats()

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/stat/report/hourly.gw"
        assert result == [{"wan-rx_bytes": 1000}]

    @pytest.mark.asyncio
    async def test_get_gateway_stats_5min(self, stats_manager, mock_connection):
        """Test get_gateway_stats with 5-minute granularity."""
        mock_connection.request.return_value = []

        await stats_manager.get_gateway_stats(granularity="5minutes")

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/stat/report/5minutes.gw"

    @pytest.mark.asyncio
    async def test_get_speedtest_results(self, stats_manager, mock_connection):
        """Test get_speedtest_results uses archive.speedtest endpoint."""
        mock_connection.request.return_value = [{"xput_download": 100}]

        result = await stats_manager.get_speedtest_results()

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/stat/report/archive.speedtest"
        assert result == [{"xput_download": 100}]

    # ---- Live stat endpoints ----

    @pytest.mark.asyncio
    async def test_get_site_dpi_traffic(self, stats_manager, mock_connection):
        """Test get_site_dpi_traffic uses /stat/sitedpi."""
        mock_connection.request.return_value = [{"app": 1, "rx_bytes": 500}]

        await stats_manager.get_site_dpi_traffic()

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/stat/sitedpi"
        assert api_request.data["type"] == "by_app"

    @pytest.mark.asyncio
    async def test_get_site_dpi_traffic_by_cat(self, stats_manager, mock_connection):
        """Test get_site_dpi_traffic with by_cat grouping."""
        mock_connection.request.return_value = []

        await stats_manager.get_site_dpi_traffic(by="by_cat")

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.data["type"] == "by_cat"

    @pytest.mark.asyncio
    async def test_get_client_dpi_traffic(self, stats_manager, mock_connection):
        """Test get_client_dpi_traffic uses /stat/stadpi with mac filter."""
        mock_connection.request.return_value = [{"app": 2, "tx_bytes": 300}]

        await stats_manager.get_client_dpi_traffic("aa:bb:cc:dd:ee:ff")

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/stat/stadpi"
        assert api_request.data["macs"] == ["aa:bb:cc:dd:ee:ff"]

    @pytest.mark.asyncio
    async def test_get_ips_events(self, stats_manager, mock_connection):
        """Test get_ips_events uses /stat/ips/event."""
        mock_connection.request.return_value = [{"event_type": "alert"}]

        await stats_manager.get_ips_events()

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/stat/ips/event"
        assert api_request.data["_limit"] == 50

    @pytest.mark.asyncio
    async def test_get_ips_events_custom_limit(self, stats_manager, mock_connection):
        """Test get_ips_events with custom limit."""
        mock_connection.request.return_value = []

        await stats_manager.get_ips_events(limit=10)

        # An empty legacy answer now triggers the v2 fallback, so the legacy
        # request is the first call rather than the last one.
        api_request = mock_connection.request.call_args_list[0][0][0]
        assert api_request.path == "/stat/ips/event"
        assert api_request.data["_limit"] == 10

    @pytest.mark.asyncio
    async def test_get_ips_events_empty_legacy_falls_back_to_v2(self, stats_manager, mock_connection):
        """An empty legacy response must still reach the v2 security log.

        Controllers that moved IPS events to the v2 system log answer
        /stat/ips/event with 200 and an empty list rather than failing, so a
        fallback guarded only by an exception never runs for them.
        """
        v2_events = [{"key": "THREAT_DETECTED", "subcategory": "SECURITY_INTRUSION_PREVENTION"}]
        mock_connection.request.side_effect = [[], v2_events]

        result = await stats_manager.get_ips_events()

        assert result == v2_events
        assert mock_connection.request.call_count == 2
        assert mock_connection.request.call_args_list[0][0][0].path == "/stat/ips/event"
        v2_request = mock_connection.request.call_args_list[1][0][0]
        # Threat blocks are not dashboard events, so /system-log/critical never has them.
        assert v2_request.path == "/system-log/all"
        assert v2_request.data["categories"] == ["SECURITY"]
        assert "type" not in v2_request.data

    @pytest.mark.asyncio
    async def test_get_ips_events_non_empty_legacy_skips_v2(self, stats_manager, mock_connection):
        """A controller still populating the legacy endpoint must not be double-queried."""
        legacy_events = [{"event_type": "alert"}]
        mock_connection.request.return_value = legacy_events

        result = await stats_manager.get_ips_events()

        assert result == legacy_events
        assert mock_connection.request.call_count == 1

    @pytest.mark.asyncio
    async def test_get_ips_events_v2_failure_after_empty_legacy_returns_empty(self, stats_manager, mock_connection):
        """A failing v2 fallback must not turn an empty result into an exception.

        A controller old enough to have no v2 endpoint answers exactly this way,
        so raising here would break setups the legacy endpoint still serves.
        """
        mock_connection.request.side_effect = [[], Exception("v2 unavailable")]

        result = await stats_manager.get_ips_events()

        assert result == []
        assert mock_connection.request.call_count == 2

    @pytest.mark.asyncio
    async def test_get_ips_events_v2_failure_is_not_cached(self, stats_manager, mock_connection):
        """A degraded empty result must not be cached as a confirmed quiet period."""
        mock_connection.request.side_effect = [[], Exception("v2 unavailable")]

        await stats_manager.get_ips_events()

        mock_connection._update_cache.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_ips_events_non_list_legacy_falls_back_to_v2(self, stats_manager, mock_connection):
        """A malformed legacy answer must reach v2 rather than be coerced to []."""
        v2_events = [{"key": "THREAT_DETECTED", "subcategory": "SECURITY_INTRUSION_PREVENTION"}]
        mock_connection.request.side_effect = [{"unexpected": "envelope"}, v2_events]

        result = await stats_manager.get_ips_events()

        assert result == v2_events
        assert mock_connection.request.call_count == 2

    @pytest.mark.asyncio
    async def test_get_client_sessions(self, stats_manager, mock_connection):
        """Test get_client_sessions uses /stat/session."""
        mock_connection.request.return_value = [{"mac": "aa:bb:cc:dd:ee:ff"}]

        await stats_manager.get_client_sessions()

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/stat/session"
        assert api_request.data["type"] == "all"

    @pytest.mark.asyncio
    async def test_get_client_sessions_with_mac(self, stats_manager, mock_connection):
        """Test get_client_sessions filters by MAC when provided."""
        mock_connection.request.return_value = []

        await stats_manager.get_client_sessions(client_mac="aa:bb:cc:dd:ee:ff")

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.data["mac"] == "aa:bb:cc:dd:ee:ff"

    @pytest.mark.asyncio
    async def test_get_client_sessions_without_mac(self, stats_manager, mock_connection):
        """Test get_client_sessions omits mac field when not provided."""
        mock_connection.request.return_value = []

        await stats_manager.get_client_sessions()

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert "mac" not in api_request.data

    @pytest.mark.asyncio
    async def test_get_dashboard(self, stats_manager, mock_connection):
        """Dashboard hits the V2 aggregated endpoint with the historySeconds knob."""
        sample = [{"gateway": {}, "wifi_activity": {}, "isp_metrics": {}}]
        mock_connection.request.return_value = sample

        result = await stats_manager.get_dashboard()

        api_request = mock_connection.request.call_args[0][0]
        assert api_request.path == "/aggregated-dashboard?historySeconds=86400"
        assert api_request.method == "get"
        assert result == sample

    @pytest.mark.asyncio
    async def test_get_dashboard_custom_history_window(self, stats_manager, mock_connection):
        """historySeconds query param reflects the caller's window."""
        mock_connection.request.return_value = []

        await stats_manager.get_dashboard(history_seconds=3600)

        api_request = mock_connection.request.call_args[0][0]
        assert api_request.path == "/aggregated-dashboard?historySeconds=3600"

    @pytest.mark.asyncio
    async def test_get_anomalies(self, stats_manager, mock_connection):
        """Test get_anomalies uses /stat/anomalies."""
        mock_connection.request.return_value = [{"type": "dns_anomaly"}]

        await stats_manager.get_anomalies()

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/stat/anomalies"
        assert "start" in api_request.data
        assert "end" in api_request.data

    # ---- Client WiFi details ----

    @pytest.mark.asyncio
    async def test_get_client_wifi_details_found(self, stats_manager, mock_connection):
        """Test get_client_wifi_details returns WiFi fields."""
        mock_connection.request.return_value = [
            {
                "mac": "aa:bb:cc:dd:ee:ff",
                "signal": -65,
                "noise": -95,
                "satisfaction": 100,
                "tx_rate": 867000,
                "rx_rate": 780000,
                "tx_retries": 42,
                "channel": 100,
                "radio": "na",
                "essid": "endpoint",
            }
        ]

        result = await stats_manager.get_client_wifi_details("aa:bb:cc:dd:ee:ff")

        assert result is not None
        assert result["mac"] == "aa:bb:cc:dd:ee:ff"
        assert result["signal"] == -65
        assert result["satisfaction"] == 100
        assert result["channel"] == 100

    @pytest.mark.asyncio
    async def test_get_client_wifi_details_uses_get_stat_sta(self, stats_manager, mock_connection):
        """/stat/sta ignores MAC in POST body — must use GET."""
        mock_connection.request.return_value = []

        await stats_manager.get_client_wifi_details("aa:bb:cc:dd:ee:ff")

        api_request = mock_connection.request.call_args[0][0]
        assert api_request.method == "get"
        assert api_request.path == "/stat/sta"

    @pytest.mark.asyncio
    async def test_get_client_wifi_details_filters_by_mac(self, stats_manager, mock_connection):
        """Must filter list by MAC, not return clients[0]."""
        mock_connection.request.return_value = [
            {"mac": "11:11:11:11:11:11", "signal": -57, "channel": 132, "radio": "na"},
            {"mac": "aa:bb:cc:dd:ee:ff", "signal": -34, "channel": 1, "radio": "ng"},
            {"mac": "22:22:22:22:22:22", "signal": -79, "channel": 11, "radio": "ng"},
        ]

        result = await stats_manager.get_client_wifi_details("aa:bb:cc:dd:ee:ff")

        assert result is not None
        assert result["mac"] == "aa:bb:cc:dd:ee:ff"
        assert result["signal"] == -34
        assert result["channel"] == 1

    @pytest.mark.asyncio
    async def test_get_client_wifi_details_no_match_returns_none(self, stats_manager, mock_connection):
        """Unknown MAC must return None, not clients[0]."""
        mock_connection.request.return_value = [
            {"mac": "11:11:11:11:11:11", "signal": -57, "channel": 132},
            {"mac": "22:22:22:22:22:22", "signal": -60, "channel": 36},
        ]

        result = await stats_manager.get_client_wifi_details("00:00:00:00:00:00")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_client_wifi_details_mac_case_insensitive(self, stats_manager, mock_connection):
        """MAC matching must ignore case so callers aren't forced to normalize."""
        mock_connection.request.return_value = [
            {"mac": "AA:BB:CC:DD:EE:FF", "signal": -50, "channel": 36},
        ]

        result = await stats_manager.get_client_wifi_details("aa:bb:cc:dd:ee:ff")

        assert result is not None
        assert result["mac"] == "AA:BB:CC:DD:EE:FF"
        assert result["signal"] == -50

    @pytest.mark.asyncio
    async def test_get_client_wifi_details_not_found(self, stats_manager, mock_connection):
        """Test get_client_wifi_details returns None for unknown client."""
        mock_connection.request.return_value = []

        result = await stats_manager.get_client_wifi_details("ff:ff:ff:ff:ff:ff")

        assert result is None

    # ---- Error handling ----

    @pytest.mark.asyncio
    async def test_get_gateway_stats_handles_error(self, stats_manager, mock_connection):
        """Test get_gateway_stats returns empty list on error."""
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await stats_manager.get_gateway_stats()

    @pytest.mark.asyncio
    async def test_get_ips_events_handles_error(self, stats_manager, mock_connection):
        """Test get_ips_events returns empty list on error."""
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await stats_manager.get_ips_events()

    @pytest.mark.asyncio
    async def test_get_dashboard_handles_error(self, stats_manager, mock_connection):
        """Test get_dashboard returns empty list on error."""
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await stats_manager.get_dashboard()

    @pytest.mark.asyncio
    async def test_get_client_wifi_details_handles_error(self, stats_manager, mock_connection):
        """Test get_client_wifi_details returns None on error."""
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await stats_manager.get_client_wifi_details("aa:bb:cc:dd:ee:ff")

    # ---- Cache tests ----

    @pytest.mark.asyncio
    async def test_get_network_stats_uses_cache(self, stats_manager, mock_connection):
        """Test get_network_stats returns cached data."""
        mock_connection.get_cached.return_value = [{"cached": True}]

        result = await stats_manager.get_network_stats()

        assert result == [{"cached": True}]
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_site_dpi_traffic_uses_cache(self, stats_manager, mock_connection):
        """Test get_site_dpi_traffic returns cached data."""
        mock_connection.get_cached.return_value = [{"cached": True}]

        result = await stats_manager.get_site_dpi_traffic()

        assert result == [{"cached": True}]
        mock_connection.request.assert_not_called()


class TestDeviceManagerSpeedtest:
    """Tests for speedtest methods in DeviceManager."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock ConnectionManager."""
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        conn.ensure_connected = AsyncMock(return_value=True)
        return conn

    @pytest.fixture
    def device_manager(self, mock_connection):
        """Create a DeviceManager with mocked connection."""
        from unifi_core.network.managers.device_manager import DeviceManager

        return DeviceManager(mock_connection)

    @pytest.mark.asyncio
    async def test_trigger_speedtest(self, device_manager, mock_connection):
        """Test trigger_speedtest sends correct command."""
        mock_connection.request.return_value = {}

        result = await device_manager.trigger_speedtest("aa:bb:cc:dd:ee:ff")

        assert result is True
        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/cmd/devmgr"
        assert api_request.data["cmd"] == "speedtest"
        assert api_request.data["mac"] == "aa:bb:cc:dd:ee:ff"

    @pytest.mark.asyncio
    async def test_trigger_speedtest_handles_error(self, device_manager, mock_connection):
        """Test trigger_speedtest returns False on error."""
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await device_manager.trigger_speedtest("aa:bb:cc:dd:ee:ff")

    @pytest.mark.asyncio
    async def test_get_speedtest_status(self, device_manager, mock_connection):
        """Test get_speedtest_status sends correct command."""
        mock_connection.request.return_value = {"status": "running"}

        result = await device_manager.get_speedtest_status("aa:bb:cc:dd:ee:ff")

        assert result == {"status": "running"}
        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.data["cmd"] == "speedtest-status"

    @pytest.mark.asyncio
    async def test_get_speedtest_status_handles_error(self, device_manager, mock_connection):
        """Test get_speedtest_status returns empty dict on error."""
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await device_manager.get_speedtest_status("aa:bb:cc:dd:ee:ff")


class TestGetAlertsFallbackDiagnostics:
    """Both alert paths failing must explain both, not just the legacy 404."""

    @pytest.fixture
    def mock_connection(self):
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        conn.get_cached = MagicMock(return_value=None)
        conn._update_cache = MagicMock()
        conn.ensure_connected = AsyncMock(return_value=True)
        conn.controller = MagicMock()
        return conn

    @pytest.fixture
    def stats_manager(self, mock_connection):
        from unifi_core.network.managers.stats_manager import StatsManager

        return StatsManager(mock_connection, MagicMock())

    @pytest.mark.asyncio
    async def test_both_paths_failing_surfaces_the_v2_error_too(self, stats_manager, mock_connection):
        mock_connection.request.side_effect = [
            Exception("Bad Request: unknown severity LOW"),  # v2 /system-log/critical
            Exception("received 404 Not Found"),  # legacy /stat/alarm
        ]

        with pytest.raises(Exception) as exc:
            await stats_manager.get_alerts()

        message = str(exc.value)
        assert "404" in message
        assert "unknown severity LOW" in message, "the v2 failure must not be swallowed"

    @pytest.mark.asyncio
    async def test_legacy_success_after_v2_failure_still_returns(self, stats_manager, mock_connection):
        """The fallback still works — this only changes the both-failed case."""
        mock_connection.request.side_effect = [
            Exception("v2 unavailable"),
            [{"_id": "a1", "archived": False}],
        ]

        result = await stats_manager.get_alerts()
        assert result == [{"_id": "a1", "archived": False}]


class TestEgressForensics:
    """Window-scoped stats used to attribute an upload spike to a client."""

    @pytest.fixture
    def mock_connection(self):
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        conn.get_cached = MagicMock(return_value=None)
        conn._update_cache = MagicMock()
        return conn

    @pytest.fixture
    def stats_manager(self, mock_connection):
        from unifi_core.network.managers.stats_manager import StatsManager

        client_manager = MagicMock()
        client_manager.get_clients = AsyncMock(return_value=[])
        return StatsManager(mock_connection, client_manager)

    @pytest.mark.asyncio
    async def test_top_clients_sums_report_over_window(self, stats_manager, mock_connection):
        """Ranking comes from the per-client report inside the window, rx counted as upload."""
        mock_connection.request.return_value = [
            {"user": "AA:BB:CC:00:00:01", "rx_bytes": 40, "tx_bytes": 1, "time": 1},
            {"user": "aa:bb:cc:00:00:01", "rx_bytes": 60, "tx_bytes": 1, "time": 2},
            {"user": "aa:bb:cc:00:00:02", "rx_bytes": 5, "tx_bytes": 500, "time": 1},
        ]

        result = await stats_manager.get_top_clients(start_ms=1_000, end_ms=2_000, granularity="5minutes")

        request = mock_connection.request.call_args[0][0]
        assert request.path == "/stat/report/5minutes.user"
        assert request.data["start"] == 1_000 and request.data["end"] == 2_000
        assert "mac" not in request.data and "macs" not in request.data
        assert [r["mac"] for r in result] == ["aa:bb:cc:00:00:02", "aa:bb:cc:00:00:01"]
        uploader = result[1]
        assert uploader["upload_bytes"] == 100 and uploader["download_bytes"] == 2
        assert uploader["total_bytes"] == 102 and uploader["source"] == "report"

    @pytest.mark.asyncio
    async def test_top_clients_sort_by_upload(self, stats_manager, mock_connection):
        mock_connection.request.return_value = [
            {"user": "aa:bb:cc:00:00:01", "rx_bytes": 100, "tx_bytes": 0},
            {"user": "aa:bb:cc:00:00:02", "rx_bytes": 5, "tx_bytes": 500},
        ]

        result = await stats_manager.get_top_clients(start_ms=1_000, end_ms=2_000, sort_by="upload")

        assert result[0]["mac"] == "aa:bb:cc:00:00:01"

    @pytest.mark.asyncio
    async def test_top_clients_rejects_unknown_sort(self, stats_manager):
        with pytest.raises(ValueError):
            await stats_manager.get_top_clients(sort_by="bytes")

    @pytest.mark.asyncio
    async def test_top_clients_rejects_inverted_window(self, stats_manager):
        with pytest.raises(ValueError):
            await stats_manager.get_top_clients(start_ms=2_000, end_ms=1_000)

    @pytest.mark.asyncio
    async def test_top_clients_falls_back_to_live_counters_marked_as_such(self, stats_manager, mock_connection):
        """A controller without the report still answers, but says the numbers are not windowed."""
        mock_connection.request.return_value = []
        stats_manager._client_manager.get_clients = AsyncMock(
            return_value=[{"mac": "aa:bb:cc:00:00:03", "name": "nas", "wired-rx_bytes": 9, "wired-tx_bytes": 1}]
        )

        result = await stats_manager.get_top_clients()

        assert result[0]["source"] == "live_counters"
        assert result[0]["upload_bytes"] == 9

    @pytest.mark.asyncio
    async def test_top_clients_auto_granularity_follows_window_age(self, stats_manager, mock_connection):
        import time

        mock_connection.request.return_value = []
        now = int(time.time() * 1000)
        await stats_manager.get_top_clients(start_ms=now - 3_600_000, end_ms=now)
        assert mock_connection.request.call_args_list[0][0][0].path == "/stat/report/5minutes.user"
        await stats_manager.get_top_clients(start_ms=now - 3 * 86_400_000, end_ms=now)
        assert mock_connection.request.call_args_list[-1][0][0].path == "/stat/report/hourly.user"
        await stats_manager.get_top_clients(start_ms=now - 30 * 86_400_000, end_ms=now)
        assert mock_connection.request.call_args_list[-1][0][0].path == "/stat/report/daily.user"

    @pytest.mark.asyncio
    async def test_client_stats_absolute_window(self, stats_manager, mock_connection):
        mock_connection.request.return_value = []

        await stats_manager.get_client_stats("aa:bb:cc:00:00:01", start_ms=1_000, end_ms=5_000)

        request = mock_connection.request.call_args[0][0]
        assert request.data["start"] == 1_000 and request.data["end"] == 5_000

    @pytest.mark.asyncio
    async def test_client_dpi_uses_v2_window_and_filters_client(self, stats_manager, mock_connection):
        mock_connection.request.return_value = {
            "client_usage_by_app": [
                {
                    "client": {"mac": "AA:BB:CC:00:00:01"},
                    "usage_by_app": [
                        {
                            "application": 234,
                            "category": 13,
                            "bytes_transmitted": 70,
                            "bytes_received": 1,
                            "total_bytes": 71,
                        },
                        {
                            "application": 10,
                            "category": 4,
                            "bytes_transmitted": 1,
                            "bytes_received": 200,
                            "total_bytes": 201,
                        },
                    ],
                },
                {"client": {"mac": "aa:bb:cc:00:00:02"}, "usage_by_app": [{"application": 1, "total_bytes": 999}]},
            ],
            "total_usage_by_app": [],
        }

        result = await stats_manager.get_client_dpi_traffic("aa:bb:cc:00:00:01", start_ms=1_000, end_ms=2_000)

        request = mock_connection.request.call_args[0][0]
        assert request.path.startswith("/traffic?start=1000&end=2000")
        assert [r["application"] for r in result] == [10, 234]
        assert result[1]["upload_bytes"] == 70 and result[1]["download_bytes"] == 1
        assert mock_connection.request.await_count == 1

    @pytest.mark.asyncio
    async def test_client_dpi_by_category_folds_apps(self, stats_manager, mock_connection):
        mock_connection.request.return_value = {
            "client_usage_by_app": [
                {
                    "client": {"mac": "aa:bb:cc:00:00:01"},
                    "usage_by_app": [
                        {
                            "application": 1,
                            "category": 13,
                            "bytes_transmitted": 5,
                            "bytes_received": 1,
                            "total_bytes": 6,
                        },
                        {
                            "application": 2,
                            "category": 13,
                            "bytes_transmitted": 5,
                            "bytes_received": 1,
                            "total_bytes": 6,
                        },
                    ],
                }
            ]
        }

        result = await stats_manager.get_client_dpi_traffic("aa:bb:cc:00:00:01", by="by_cat")

        assert result == [
            {
                "category": 13,
                "bytes_transmitted": 10,
                "bytes_received": 2,
                "total_bytes": 12,
                "upload_bytes": 10,
                "download_bytes": 2,
            }
        ]

    @pytest.mark.asyncio
    async def test_client_dpi_falls_back_to_legacy_when_v2_missing(self, stats_manager, mock_connection):
        mock_connection.request.side_effect = [RuntimeError("404"), [{"app": 2}]]

        result = await stats_manager.get_client_dpi_traffic("aa:bb:cc:00:00:01")

        assert result == [{"app": 2}]
        assert mock_connection.request.call_args_list[1][0][0].path == "/stat/stadpi"

    @pytest.mark.asyncio
    async def test_site_dpi_uses_v2_totals(self, stats_manager, mock_connection):
        mock_connection.request.return_value = {
            "total_usage_by_app": [{"application": 65535, "category": 255, "bytes_transmitted": 9, "total_bytes": 9}]
        }

        result = await stats_manager.get_site_dpi_traffic(start_ms=1_000, end_ms=2_000)

        assert result[0]["application"] == 65535 and result[0]["upload_bytes"] == 9


class TestStatsToolArguments:
    """Tool-level argument handling: no silent fallbacks."""

    def test_unknown_duration_is_rejected(self):
        from unifi_network_mcp.tools.stats import _duration_hours

        assert _duration_hours("daily") == 24
        with pytest.raises(ValueError, match="start/end"):
            _duration_hours("8h")

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("1790930100", 1790930100000),
            ("1790930100000", 1790930100000),
            ("2026-10-02T06:35:00Z", 1790922900000),
            ("2026-10-02T02:35:00-04:00", 1790922900000),
            (None, None),
            ("", None),
        ],
    )
    def test_epoch_ms_parsing(self, value, expected):
        from unifi_network_mcp.tools.stats import _epoch_ms

        assert _epoch_ms(value) == expected

    def test_epoch_ms_rejects_garbage(self):
        from unifi_network_mcp.tools.stats import _epoch_ms

        with pytest.raises(ValueError):
            _epoch_ms("last tuesday")
