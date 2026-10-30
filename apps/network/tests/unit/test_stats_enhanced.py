"""Tests for enhanced stats manager methods.

Tests granularity support, new report endpoints, live stat endpoints,
and device command methods (speedtest).
"""

from unittest.mock import ANY, AsyncMock, MagicMock

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

    # ---- Report/stat endpoint request shapes ----

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method,args,kwargs,path,data",
        [
            ("get_network_stats", (), {}, "/stat/report/hourly.site", {}),
            ("get_network_stats", (), {"granularity": "5minutes"}, "/stat/report/5minutes.site", {}),
            ("get_network_stats", (), {"granularity": "daily"}, "/stat/report/daily.site", {}),
            ("get_network_stats", (), {"granularity": "monthly"}, "/stat/report/monthly.site", {}),
            ("get_client_stats", ("aa:bb:cc:dd:ee:ff",), {}, "/stat/report/hourly.user", {}),
            (
                "get_client_stats",
                ("aa:bb:cc:dd:ee:ff",),
                {"granularity": "5minutes"},
                "/stat/report/5minutes.user",
                {},
            ),
            ("get_device_stats", ("aa:bb:cc:dd:ee:ff",), {"device_type": "ap"}, "/stat/report/hourly.ap", {}),
            ("get_device_stats", ("aa:bb:cc:dd:ee:ff",), {"device_type": "gw"}, "/stat/report/hourly.gw", {}),
            ("get_device_stats", ("aa:bb:cc:dd:ee:ff",), {}, "/stat/report/hourly.dev", {}),
            ("get_gateway_stats", (), {}, "/stat/report/hourly.gw", {}),
            ("get_gateway_stats", (), {"granularity": "5minutes"}, "/stat/report/5minutes.gw", {}),
            ("get_speedtest_results", (), {}, "/stat/report/archive.speedtest", {}),
            ("get_site_dpi_traffic", (), {}, "/stat/sitedpi", {"type": "by_app"}),
            ("get_site_dpi_traffic", (), {"by": "by_cat"}, "/stat/sitedpi", {"type": "by_cat"}),
            ("get_client_dpi_traffic", ("aa:bb:cc:dd:ee:ff",), {}, "/stat/stadpi", {"macs": ["aa:bb:cc:dd:ee:ff"]}),
            ("get_ips_events", (), {}, "/stat/ips/event", {"_limit": 50}),
            ("get_ips_events", (), {"limit": 10}, "/stat/ips/event", {"_limit": 10}),
            ("get_client_sessions", (), {}, "/stat/session", {"type": "all"}),
            (
                "get_client_sessions",
                (),
                {"client_mac": "aa:bb:cc:dd:ee:ff"},
                "/stat/session",
                {"mac": "aa:bb:cc:dd:ee:ff"},
            ),
            ("get_anomalies", (), {}, "/stat/anomalies", {"start": ANY, "end": ANY}),
        ],
    )
    async def test_request_shape(self, stats_manager, mock_connection, method, args, kwargs, path, data):
        """Each stats method hits its endpoint with the expected query payload."""
        mock_connection.request.return_value = []

        await getattr(stats_manager, method)(*args, **kwargs)

        # Empty answers can trigger a fallback request, so pick the request for this endpoint.
        api_request = next((c[0][0] for c in mock_connection.request.call_args_list if c[0][0].path == path), None)
        assert api_request is not None, [c[0][0].path for c in mock_connection.request.call_args_list]
        for key, value in data.items():
            assert api_request.data[key] == value

    @pytest.mark.asyncio
    async def test_get_network_stats_invalid_granularity(self, stats_manager):
        """Test get_network_stats rejects invalid granularity."""
        with pytest.raises(ValueError, match="Invalid granularity"):
            await stats_manager.get_network_stats(granularity="invalid")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method,args,kwargs,attrs",
        [
            ("get_network_stats", (), {}, {"wan-rx_bytes", "wan-tx_bytes"}),
            ("get_client_stats", ("aa:bb:cc:dd:ee:ff",), {}, {"signal", "satisfaction", "tx_retries"}),
            ("get_device_stats", ("aa:bb:cc:dd:ee:ff",), {"device_type": "ap"}, {"satisfaction"}),
            ("get_device_stats", ("aa:bb:cc:dd:ee:ff",), {"device_type": "gw"}, {"cpu"}),
        ],
    )
    async def test_report_requests_include_breakdown_attrs(
        self, stats_manager, mock_connection, method, args, kwargs, attrs
    ):
        mock_connection.request.return_value = []

        await getattr(stats_manager, method)(*args, **kwargs)

        assert attrs <= set(mock_connection.request.call_args[0][0].data["attrs"])

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method,payload",
        [("get_gateway_stats", [{"wan-rx_bytes": 1000}]), ("get_speedtest_results", [{"xput_download": 100}])],
    )
    async def test_report_results_are_returned(self, stats_manager, mock_connection, method, payload):
        mock_connection.request.return_value = payload

        assert await getattr(stats_manager, method)() == payload

    @pytest.mark.asyncio
    async def test_get_client_sessions_without_mac(self, stats_manager, mock_connection):
        """Test get_client_sessions omits mac field when not provided."""
        mock_connection.request.return_value = []

        await stats_manager.get_client_sessions()

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert "mac" not in api_request.data

    # ---- IPS events ----

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "legacy_answer",
        [
            # Controllers that moved IPS events to the v2 system log answer /stat/ips/event
            # with 200 and an empty list rather than failing, so an exception-only fallback never runs.
            [],
            # A malformed legacy answer must reach v2 rather than be coerced to [].
            {"unexpected": "envelope"},
        ],
    )
    async def test_get_ips_events_unusable_legacy_falls_back_to_v2(self, stats_manager, mock_connection, legacy_answer):
        v2_events = [{"key": "THREAT_DETECTED", "subcategory": "SECURITY_INTRUSION_PREVENTION"}]
        mock_connection.request.side_effect = [legacy_answer, v2_events]

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
    async def test_get_ips_events_v2_failure_after_empty_legacy_raises(self, stats_manager, mock_connection):
        """An empty legacy feed cannot establish that a failed v2 read contained no threats."""
        mock_connection.request.side_effect = [[], Exception("v2 unavailable")]

        with pytest.raises(Exception, match="IPS events"):
            await stats_manager.get_ips_events()

        assert mock_connection.request.call_count == 2

    @pytest.mark.asyncio
    async def test_get_ips_events_v2_failure_is_not_cached(self, stats_manager, mock_connection):
        """A degraded empty result must not be cached as a confirmed quiet period."""
        mock_connection.request.side_effect = [[], Exception("v2 unavailable")]

        with pytest.raises(Exception, match="IPS events"):
            await stats_manager.get_ips_events()

        mock_connection._update_cache.assert_not_called()

    # ---- Dashboard ----

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kwargs,seconds", [({}, 86400), ({"history_seconds": 3600}, 3600)])
    async def test_get_dashboard(self, stats_manager, mock_connection, kwargs, seconds):
        """Dashboard hits the V2 aggregated endpoint with the caller's historySeconds window."""
        sample = [{"gateway": {}, "wifi_activity": {}, "isp_metrics": {}}]
        mock_connection.request.return_value = sample

        result = await stats_manager.get_dashboard(**kwargs)

        api_request = mock_connection.request.call_args[0][0]
        assert api_request.path == f"/aggregated-dashboard?historySeconds={seconds}"
        assert api_request.method == "get"
        assert result == sample

    # ---- Client WiFi details ----

    @pytest.mark.asyncio
    async def test_get_client_wifi_details_uses_get_stat_sta(self, stats_manager, mock_connection):
        """/stat/sta ignores MAC in POST body — must use GET."""
        mock_connection.request.return_value = []

        await stats_manager.get_client_wifi_details("aa:bb:cc:dd:ee:ff")

        api_request = mock_connection.request.call_args[0][0]
        assert api_request.method == "get"
        assert api_request.path == "/stat/sta"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "rows,query,expected",
        [
            (
                [
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
                ],
                "aa:bb:cc:dd:ee:ff",
                {"mac": "aa:bb:cc:dd:ee:ff", "signal": -65, "satisfaction": 100, "channel": 100},
            ),
            # Must filter the list by MAC, not return clients[0].
            (
                [
                    {"mac": "11:11:11:11:11:11", "signal": -57, "channel": 132, "radio": "na"},
                    {"mac": "aa:bb:cc:dd:ee:ff", "signal": -34, "channel": 1, "radio": "ng"},
                    {"mac": "22:22:22:22:22:22", "signal": -79, "channel": 11, "radio": "ng"},
                ],
                "aa:bb:cc:dd:ee:ff",
                {"mac": "aa:bb:cc:dd:ee:ff", "signal": -34, "channel": 1},
            ),
            # Unknown MAC returns None, not clients[0].
            (
                [
                    {"mac": "11:11:11:11:11:11", "signal": -57, "channel": 132},
                    {"mac": "22:22:22:22:22:22", "signal": -60, "channel": 36},
                ],
                "00:00:00:00:00:00",
                None,
            ),
            # MAC matching ignores case so callers aren't forced to normalize.
            (
                [{"mac": "AA:BB:CC:DD:EE:FF", "signal": -50, "channel": 36}],
                "aa:bb:cc:dd:ee:ff",
                {"mac": "AA:BB:CC:DD:EE:FF", "signal": -50},
            ),
            ([], "ff:ff:ff:ff:ff:ff", None),
        ],
    )
    async def test_get_client_wifi_details_lookup(self, stats_manager, mock_connection, rows, query, expected):
        mock_connection.request.return_value = rows

        result = await stats_manager.get_client_wifi_details(query)

        if expected is None:
            assert result is None
        else:
            assert {key: result[key] for key in expected} == expected

    # ---- Error handling ----

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method,args",
        [
            ("get_gateway_stats", ()),
            ("get_ips_events", ()),
            ("get_dashboard", ()),
            ("get_client_wifi_details", ("aa:bb:cc:dd:ee:ff",)),
        ],
    )
    async def test_request_errors_propagate(self, stats_manager, mock_connection, method, args):
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await getattr(stats_manager, method)(*args)

    # ---- Cache tests ----

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["get_network_stats", "get_site_dpi_traffic"])
    async def test_uses_cache(self, stats_manager, mock_connection, method):
        """Cached data is returned without a controller request."""
        mock_connection.get_cached.return_value = [{"cached": True}]

        result = await getattr(stats_manager, method)()

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
    @pytest.mark.parametrize(
        "method,response,expected,cmd",
        [
            ("trigger_speedtest", {}, True, "speedtest"),
            ("get_speedtest_status", {"status": "running"}, {"status": "running"}, "speedtest-status"),
        ],
    )
    async def test_speedtest_commands(self, device_manager, mock_connection, method, response, expected, cmd):
        """Speedtest methods send the right devmgr command for the device."""
        mock_connection.request.return_value = response

        result = await getattr(device_manager, method)("aa:bb:cc:dd:ee:ff")

        assert result == expected
        api_request = mock_connection.request.call_args[0][0]
        assert api_request.path == "/cmd/devmgr"
        assert api_request.data["cmd"] == cmd
        assert api_request.data["mac"] == "aa:bb:cc:dd:ee:ff"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["trigger_speedtest", "get_speedtest_status"])
    async def test_speedtest_errors_propagate(self, device_manager, mock_connection, method):
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await getattr(device_manager, method)("aa:bb:cc:dd:ee:ff")


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
        ],
    )
    def test_epoch_ms_parsing(self, value, expected):
        from unifi_network_mcp.tools.stats import _epoch_ms

        assert _epoch_ms(value) == expected

    def test_epoch_ms_rejects_garbage(self):
        from unifi_network_mcp.tools.stats import _epoch_ms

        with pytest.raises(ValueError):
            _epoch_ms("last tuesday")

    @pytest.mark.parametrize("value", ["", "   "])
    def test_epoch_ms_rejects_blank(self, value):
        """An empty bound is an error, not "omitted": None is the only way to omit it."""
        from unifi_network_mcp.tools.stats import _epoch_ms

        with pytest.raises(ValueError, match="Empty time bound"):
            _epoch_ms(value)

    def test_epoch_ms_rejects_naive_iso(self):
        from unifi_network_mcp.tools.stats import _epoch_ms

        with pytest.raises(ValueError, match="UTC offset"):
            _epoch_ms("2026-10-02T06:35:00")


@pytest.mark.asyncio
async def test_speedtest_report_asks_which_wan_ran_each_test():
    """Dual-WAN results are only distinguishable when the WAN fields are requested."""
    from unifi_core.network.managers.stats_manager import StatsManager

    conn = MagicMock()
    conn.site = "default"
    conn.get_cached = MagicMock(return_value=None)
    conn.request = AsyncMock(return_value=[])
    await StatsManager(conn, MagicMock()).get_speedtest_results(duration_hours=24)

    attrs = conn.request.call_args[0][0].data["attrs"]
    assert {"time", "wan_networkgroup", "interface_name"} <= set(attrs)
