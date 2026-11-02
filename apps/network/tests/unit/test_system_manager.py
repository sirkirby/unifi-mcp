"""Tests for the SystemManager class.

This module tests system info, controller status, firmware update,
and network health operations.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_connection():
    """Create a mock ConnectionManager."""
    conn = MagicMock()
    conn.site = "default"
    conn.request = AsyncMock()
    conn.get_cached = MagicMock(return_value=None)
    conn._update_cache = MagicMock()
    conn._invalidate_cache = MagicMock()
    return conn


@pytest.fixture
def system_manager(mock_connection):
    """Create a SystemManager with mocked connection."""
    from unifi_core.network.managers.system_manager import SystemManager

    return SystemManager(mock_connection)


SINGLE_DOC_METHODS = ["get_system_info", "get_controller_status", "check_firmware_updates"]


class TestSingleDocumentEndpoints:
    """get_system_info / get_controller_status / check_firmware_updates normalise to one dict."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", SINGLE_DOC_METHODS)
    async def test_list_response_is_unwrapped(self, system_manager, mock_connection, method):
        mock_connection.request.return_value = [{"version": "8.6.9", "uptime": 12345}]

        assert await getattr(system_manager, method)() == {"version": "8.6.9", "uptime": 12345}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", SINGLE_DOC_METHODS)
    async def test_dict_response_is_returned_as_is(self, system_manager, mock_connection, method):
        mock_connection.request.return_value = {"version": "8.6.9"}

        assert await getattr(system_manager, method)() == {"version": "8.6.9"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", SINGLE_DOC_METHODS)
    @pytest.mark.parametrize("raw", [[], None], ids=["empty-list", "none"])
    async def test_empty_response_returns_empty_dict(self, system_manager, mock_connection, method, raw):
        mock_connection.request.return_value = raw

        assert await getattr(system_manager, method)() == {}


class TestGetSystemInfo:
    """Tests for SystemManager.get_system_info() caching."""

    @pytest.mark.asyncio
    async def test_cache_hit(self, system_manager, mock_connection):
        """Test that cached data is returned without making a request."""
        cached_data = {"version": "8.6.9", "uptime": 99999}
        mock_connection.get_cached.return_value = cached_data

        result = await system_manager.get_system_info()

        assert result == cached_data
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss_populates(self, system_manager, mock_connection):
        """Test that a cache miss fetches data and populates the cache."""
        mock_connection.request.return_value = [{"version": "8.6.9"}]

        result = await system_manager.get_system_info()

        assert result == {"version": "8.6.9"}
        mock_connection._update_cache.assert_called_once_with("system_info_default", {"version": "8.6.9"}, timeout=15)


CONSOLE_IP = "192.0.2.1"


def _record(**raw):
    return SimpleNamespace(raw=raw)


CONSOLE_MODEL = "UDMPROSE"


def _console(cpu="12.5", mem="40.25"):
    return _record(
        mac="02:00:00:00:00:01",
        type="udm",
        model=CONSOLE_MODEL,
        network_table=[{"name": "LAN", "ip": CONSOLE_IP}],
        **{"system-stats": {"cpu": cpu, "mem": mem, "uptime": "100"}},
    )


def _other_gateway(ip="192.0.2.254", model="UGW3"):
    return _record(
        mac="02:00:00:00:00:02",
        type="ugw",
        model=model,
        network_table=[{"name": "LAN", "ip": ip}],
        **{"system-stats": {"cpu": "99", "mem": "99"}},
    )


def _switch():
    return _record(mac="02:00:00:00:00:03", type="usw", **{"system-stats": {"cpu": "1", "mem": "1"}})


class TestGetSystemInfoLiveFields:
    """Counts come from the device and client lists, and CPU and memory from the console's own device record."""

    @pytest.fixture
    def connection(self, mock_connection):
        mock_connection.integration_inventory_only = False
        mock_connection.refresh_handler = AsyncMock()
        mock_connection.request.return_value = [
            {"version": "8.6.9", "ubnt_device_type": CONSOLE_MODEL, "ip_addrs": [CONSOLE_IP, "198.51.100.1"]}
        ]
        mock_connection.controller = SimpleNamespace(
            devices={"a": _console(), "b": _switch()},
            clients={"c": _record(mac="02:00:00:00:01:01"), "d": _record(mac="02:00:00:00:01:02")},
        )
        return mock_connection

    @pytest.mark.asyncio
    async def test_counts_and_console_usage_are_filled(self, system_manager, connection):
        info = await system_manager.get_system_info()

        assert info["num_devices"] == 2
        assert info["num_clients"] == 2
        assert info["cpu_percent"] == 12.5
        assert info["memory_percent"] == 40.25
        assert info["version"] == "8.6.9"

    @pytest.mark.asyncio
    async def test_the_cache_holds_the_filled_fields(self, system_manager, connection):
        info = await system_manager.get_system_info()

        connection._update_cache.assert_called_once_with("system_info_default", info, timeout=15)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "gateway",
        [
            pytest.param(_other_gateway(), id="different address and model"),
            pytest.param(_other_gateway(ip=CONSOLE_IP), id="overlapping address, different model"),
            pytest.param(_other_gateway(model=CONSOLE_MODEL), id="same model, different address"),
        ],
    )
    async def test_a_device_that_is_not_the_console_gives_no_usage(self, system_manager, connection, gateway):
        """A USG beside a self-hosted controller has its own CPU, even on an overlapping address range."""
        connection.controller.devices = {"a": gateway, "b": _switch()}

        info = await system_manager.get_system_info()

        assert info["num_devices"] == 2
        assert "cpu_percent" not in info
        assert "memory_percent" not in info

    @pytest.mark.asyncio
    async def test_a_controller_that_names_no_console_model_gives_no_usage(self, system_manager, connection):
        connection.request.return_value = [{"version": "8.6.9", "ip_addrs": [CONSOLE_IP]}]

        info = await system_manager.get_system_info()

        assert info["num_devices"] == 2
        assert "cpu_percent" not in info

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "cpu",
        ["", "n/a", None, "NaN", "Infinity", "-Infinity", "1e1000"],
        ids=["blank", "text", "missing", "nan", "infinity", "negative-infinity", "overflow"],
    )
    async def test_an_unreadable_reading_is_left_out(self, system_manager, connection, cpu):
        connection.controller.devices = {"a": _console(cpu=cpu)}

        info = await system_manager.get_system_info()

        assert "cpu_percent" not in info
        assert info["memory_percent"] == 40.25

    @pytest.mark.asyncio
    async def test_a_failed_list_leaves_only_its_own_fields_out(self, system_manager, connection):
        async def refresh(name):
            if name == "devices":
                raise RuntimeError("devices unavailable")

        connection.refresh_handler = AsyncMock(side_effect=refresh)

        info = await system_manager.get_system_info()

        assert info["version"] == "8.6.9"
        assert info["num_clients"] == 2
        assert "num_devices" not in info
        assert "cpu_percent" not in info

    @pytest.mark.asyncio
    async def test_an_empty_sysinfo_reads_no_lists(self, system_manager, connection):
        connection.request.return_value = []

        assert await system_manager.get_system_info() == {}
        connection.refresh_handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_integration_only_connection_reads_no_lists(self, system_manager, connection):
        connection.integration_inventory_only = True

        info = await system_manager.get_system_info()

        assert "num_devices" not in info
        connection.refresh_handler.assert_not_called()


class TestGetNetworkHealth:
    """Tests for SystemManager.get_network_health().

    Unlike other /stat/* endpoints that wrap a single dict in a list,
    /stat/health returns a multi-element list (one dict per subsystem).
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (
                [
                    {"subsystem": "wan", "status": "ok", "num_gw": 1},
                    {"subsystem": "wlan", "status": "ok", "num_ap": 3},
                    {"subsystem": "lan", "status": "ok", "num_sw": 2},
                ],
                [
                    {"subsystem": "wan", "status": "ok", "num_gw": 1},
                    {"subsystem": "wlan", "status": "ok", "num_ap": 3},
                    {"subsystem": "lan", "status": "ok", "num_sw": 2},
                ],
            ),
            ([{"subsystem": "wan", "status": "ok"}], [{"subsystem": "wan", "status": "ok"}]),
            ({"subsystem": "wan", "status": "ok"}, [{"subsystem": "wan", "status": "ok"}]),
            ([], []),
            (None, []),
        ],
        ids=["multi-element", "single-element-not-unwrapped", "dict-wrapped", "empty-list", "none"],
    )
    async def test_response_normalised_to_list(self, system_manager, mock_connection, raw, expected):
        mock_connection.request.return_value = raw

        result = await system_manager.get_network_health()

        assert result == expected
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_cache_hit(self, system_manager, mock_connection):
        """Test that cached data is returned without making a request."""
        cached_data = [{"subsystem": "wan", "status": "ok"}]
        mock_connection.get_cached.return_value = cached_data

        result = await system_manager.get_network_health()

        assert result == cached_data
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss_populates(self, system_manager, mock_connection):
        """Test that a cache miss fetches data and populates the cache."""
        health_data = [{"subsystem": "wan"}, {"subsystem": "wlan"}]
        mock_connection.request.return_value = health_data

        result = await system_manager.get_network_health()

        assert result == health_data
        mock_connection._update_cache.assert_called_once_with("health_default", health_data, timeout=10)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", [*SINGLE_DOC_METHODS, "get_network_health"])
async def test_controller_errors_propagate(system_manager, mock_connection, method):
    mock_connection.request.side_effect = Exception("Network error")

    with pytest.raises(Exception):
        await getattr(system_manager, method)()
    mock_connection.request.assert_called_once()


@pytest.mark.asyncio
async def test_update_settings_omits_submitted_secret_from_failure_log(caplog):
    """The settings document can carry secrets (SNMPv3 password, SSH password);
    a controller error that quotes it must log only operation and exception class."""
    import logging
    from unittest.mock import AsyncMock, MagicMock

    from unifi_core.network.managers.system_manager import SystemManager

    conn = MagicMock()
    conn.site = "default"
    conn.get_cached = MagicMock(return_value=None)
    conn._update_cache = MagicMock()
    conn._invalidate_cache = MagicMock()
    conn.ensure_connected = AsyncMock(return_value=True)
    conn.request = AsyncMock(side_effect=[[{"_id": "s1", "key": "snmp"}], RuntimeError("rejected: x_password=hunter2")])
    manager = SystemManager(conn)

    with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
        with pytest.raises(RuntimeError) as excinfo:
            await manager.update_settings("snmp", {"x_password": "hunter2"})

    assert "hunter2" not in caplog.text
    assert "Error updating snmp settings: RuntimeError" in caplog.text
    assert "rejected: x_password" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    assert str(excinfo.value) == "rejected: x_password=***REDACTED***"
