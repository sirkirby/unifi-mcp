"""Tests for the SystemManager class.

This module tests system info, controller status, firmware update,
and network health operations.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestGetSystemInfo:
    """Tests for SystemManager.get_system_info()."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock ConnectionManager."""
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        conn.get_cached = MagicMock(return_value=None)
        conn._update_cache = MagicMock()
        conn._invalidate_cache = MagicMock()
        return conn

    @pytest.fixture
    def system_manager(self, mock_connection):
        """Create a SystemManager with mocked connection."""
        from unifi_core.network.managers.system_manager import SystemManager

        return SystemManager(mock_connection)

    @pytest.mark.asyncio
    async def test_list_response(self, system_manager, mock_connection):
        """Test that a list response is unwrapped to its first element."""
        mock_connection.request.return_value = [{"version": "8.6.9", "uptime": 12345}]

        result = await system_manager.get_system_info()

        assert result == {"version": "8.6.9", "uptime": 12345}
        mock_connection._update_cache.assert_called_once()
        cached_value = mock_connection._update_cache.call_args[0][1]
        assert cached_value == {"version": "8.6.9", "uptime": 12345}

    @pytest.mark.asyncio
    async def test_dict_response(self, system_manager, mock_connection):
        """Test that a dict response is returned as-is."""
        mock_connection.request.return_value = {"version": "8.6.9"}

        result = await system_manager.get_system_info()

        assert result == {"version": "8.6.9"}

    @pytest.mark.asyncio
    async def test_empty_list(self, system_manager, mock_connection):
        """Test that an empty list returns an empty dict."""
        mock_connection.request.return_value = []

        result = await system_manager.get_system_info()

        assert result == {}

    @pytest.mark.asyncio
    async def test_none_response(self, system_manager, mock_connection):
        """Test that a None response returns an empty dict."""
        mock_connection.request.return_value = None

        result = await system_manager.get_system_info()

        assert result == {}

    @pytest.mark.asyncio
    async def test_exception(self, system_manager, mock_connection):
        """Test that an exception returns an empty dict."""
        mock_connection.request.side_effect = Exception("Network error")

        with pytest.raises(Exception):
            await system_manager.get_system_info()

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


class TestGetControllerStatus:
    """Tests for SystemManager.get_controller_status()."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock ConnectionManager."""
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        conn.get_cached = MagicMock(return_value=None)
        conn._update_cache = MagicMock()
        conn._invalidate_cache = MagicMock()
        return conn

    @pytest.fixture
    def system_manager(self, mock_connection):
        """Create a SystemManager with mocked connection."""
        from unifi_core.network.managers.system_manager import SystemManager

        return SystemManager(mock_connection)

    @pytest.mark.asyncio
    async def test_list_response(self, system_manager, mock_connection):
        """Test that a list response is unwrapped to its first element."""
        mock_connection.request.return_value = [{"status": "ok"}]

        result = await system_manager.get_controller_status()

        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_dict_response(self, system_manager, mock_connection):
        """Test that a dict response is returned as-is."""
        mock_connection.request.return_value = {"status": "ok"}

        result = await system_manager.get_controller_status()

        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_empty_list(self, system_manager, mock_connection):
        """Test that an empty list returns an empty dict."""
        mock_connection.request.return_value = []

        result = await system_manager.get_controller_status()

        assert result == {}

    @pytest.mark.asyncio
    async def test_none_response(self, system_manager, mock_connection):
        """Test that a None response returns an empty dict."""
        mock_connection.request.return_value = None

        result = await system_manager.get_controller_status()

        assert result == {}

    @pytest.mark.asyncio
    async def test_exception(self, system_manager, mock_connection):
        """Test that an exception returns an empty dict."""
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await system_manager.get_controller_status()


class TestCheckFirmwareUpdates:
    """Tests for SystemManager.check_firmware_updates()."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock ConnectionManager."""
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        conn.get_cached = MagicMock(return_value=None)
        conn._update_cache = MagicMock()
        conn._invalidate_cache = MagicMock()
        return conn

    @pytest.fixture
    def system_manager(self, mock_connection):
        """Create a SystemManager with mocked connection."""
        from unifi_core.network.managers.system_manager import SystemManager

        return SystemManager(mock_connection)

    @pytest.mark.asyncio
    async def test_list_response(self, system_manager, mock_connection):
        """Test that a list response is unwrapped to its first element."""
        mock_connection.request.return_value = [{"firmware_version": "7.1.68", "device_type": "U7PG2"}]

        result = await system_manager.check_firmware_updates()

        assert result == {"firmware_version": "7.1.68", "device_type": "U7PG2"}

    @pytest.mark.asyncio
    async def test_dict_response(self, system_manager, mock_connection):
        """Test that a dict response is returned as-is."""
        mock_connection.request.return_value = {"firmware_version": "7.1.68"}

        result = await system_manager.check_firmware_updates()

        assert result == {"firmware_version": "7.1.68"}

    @pytest.mark.asyncio
    async def test_empty_list(self, system_manager, mock_connection):
        """Test that an empty list returns an empty dict."""
        mock_connection.request.return_value = []

        result = await system_manager.check_firmware_updates()

        assert result == {}

    @pytest.mark.asyncio
    async def test_none_response(self, system_manager, mock_connection):
        """Test that a None response returns an empty dict."""
        mock_connection.request.return_value = None

        result = await system_manager.check_firmware_updates()

        assert result == {}

    @pytest.mark.asyncio
    async def test_exception(self, system_manager, mock_connection):
        """Test that an exception returns an empty dict."""
        mock_connection.request.side_effect = Exception("Timeout")

        with pytest.raises(Exception):
            await system_manager.check_firmware_updates()


class TestGetNetworkHealth:
    """Tests for SystemManager.get_network_health().

    Unlike other /stat/* endpoints that wrap a single dict in a list,
    /stat/health returns a multi-element list (one dict per subsystem).
    """

    @pytest.fixture
    def mock_connection(self):
        """Create a mock ConnectionManager."""
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        conn.get_cached = MagicMock(return_value=None)
        conn._update_cache = MagicMock()
        return conn

    @pytest.fixture
    def system_manager(self, mock_connection):
        """Create a SystemManager with mocked connection."""
        from unifi_core.network.managers.system_manager import SystemManager

        return SystemManager(mock_connection)

    @pytest.mark.asyncio
    async def test_multi_element_list(self, system_manager, mock_connection):
        """Test that a multi-element list is returned in full (no truncation)."""
        health_data = [
            {"subsystem": "wan", "status": "ok", "num_gw": 1},
            {"subsystem": "wlan", "status": "ok", "num_ap": 3},
            {"subsystem": "lan", "status": "ok", "num_sw": 2},
        ]
        mock_connection.request.return_value = health_data

        result = await system_manager.get_network_health()

        assert result == health_data
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_single_element_list(self, system_manager, mock_connection):
        """Test that a single-element list is returned as-is (not unwrapped)."""
        mock_connection.request.return_value = [{"subsystem": "wan", "status": "ok"}]

        result = await system_manager.get_network_health()

        assert result == [{"subsystem": "wan", "status": "ok"}]
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_dict_response_wrapped(self, system_manager, mock_connection):
        """Test that a dict response is normalized to a single-element list."""
        mock_connection.request.return_value = {"subsystem": "wan", "status": "ok"}

        result = await system_manager.get_network_health()

        assert result == [{"subsystem": "wan", "status": "ok"}]
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_empty_list(self, system_manager, mock_connection):
        """Test that an empty list returns an empty list."""
        mock_connection.request.return_value = []

        result = await system_manager.get_network_health()

        assert result == []

    @pytest.mark.asyncio
    async def test_none_response(self, system_manager, mock_connection):
        """Test that a None response returns an empty list."""
        mock_connection.request.return_value = None

        result = await system_manager.get_network_health()

        assert result == []

    @pytest.mark.asyncio
    async def test_exception(self, system_manager, mock_connection):
        """Test that an exception returns an empty list."""
        mock_connection.request.side_effect = Exception("Network error")

        with pytest.raises(Exception):
            await system_manager.get_network_health()
        mock_connection.request.assert_called_once()

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
async def test_update_settings_logs_class_name_only_on_failure(caplog):
    """The settings document can carry secrets (SNMPv3 password, SSH password);
    a controller error that quotes it must not reach the log."""
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
        with pytest.raises(RuntimeError):
            await manager.update_settings("snmp", {"x_password": "hunter2"})

    assert "hunter2" not in caplog.text
    assert "RuntimeError" in caplog.text
