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

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.data["_limit"] == 10

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
        """Regression for #148: /stat/sta ignores MAC in POST body — must use GET."""
        mock_connection.request.return_value = []

        await stats_manager.get_client_wifi_details("aa:bb:cc:dd:ee:ff")

        api_request = mock_connection.request.call_args[0][0]
        assert api_request.method == "get"
        assert api_request.path == "/stat/sta"

    @pytest.mark.asyncio
    async def test_get_client_wifi_details_filters_by_mac(self, stats_manager, mock_connection):
        """Regression for #148: must filter list by MAC, not return clients[0]."""
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
        """Regression for #148: unknown MAC must return None, not clients[0]."""
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
