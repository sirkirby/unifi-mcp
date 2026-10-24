"""Tests for the SystemManager class.

This module tests system info, controller status, firmware update,
and network health operations.
"""

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
