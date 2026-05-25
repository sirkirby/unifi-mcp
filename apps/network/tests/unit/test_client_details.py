"""Tests for ClientManager.get_client_details — prefers live /stat/sta
data over historical /rest/user snapshot, falls back when not active.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.managers.client_manager import ClientManager


@pytest.fixture
def mock_connection():
    conn = MagicMock()
    conn.site = "default"
    conn.get_cached = MagicMock(return_value=None)
    conn._update_cache = MagicMock()
    conn._invalidate_cache = MagicMock()
    conn.ensure_connected = AsyncMock(return_value=True)
    conn.controller = MagicMock()
    conn.controller.clients = MagicMock()
    conn.controller.clients.update = AsyncMock()
    conn.controller.clients.values = MagicMock(return_value=[])
    conn.controller.clients_all = MagicMock()
    conn.controller.clients_all.update = AsyncMock()
    conn.controller.clients_all.values = MagicMock(return_value=[])
    conn.request = AsyncMock(return_value=None)
    return conn


def _client(mac: str, **extra):
    obj = MagicMock()
    obj.mac = mac
    obj.raw = {"mac": mac, **extra}
    return obj


@pytest.mark.asyncio
async def test_prefers_active_stat_sta(mock_connection):
    """Active client found in /stat/sta is returned directly — no /rest/user lookup."""
    mac = "aa:bb:cc:dd:ee:ff"
    live = _client(mac, last_seen=1779732658, signal=-52, uptime=3639515)
    historical = _client(mac, last_seen=1776076601)  # stale
    mock_connection.controller.clients.values.return_value = [live]
    mock_connection.controller.clients_all.values.return_value = [historical]

    mgr = ClientManager(mock_connection)
    result = await mgr.get_client_details(mac)

    assert result.raw["last_seen"] == 1779732658
    assert result.raw["signal"] == -52
    # /rest/user collection should NOT be consulted when /stat/sta has the client
    mock_connection.controller.clients_all.update.assert_not_called()


@pytest.mark.asyncio
async def test_falls_back_to_rest_user_when_inactive(mock_connection):
    mac = "aa:bb:cc:dd:ee:ff"
    historical = _client(mac, last_seen=1776076601)
    mock_connection.controller.clients.values.return_value = []
    mock_connection.controller.clients_all.values.return_value = [historical]

    mgr = ClientManager(mock_connection)
    result = await mgr.get_client_details(mac)

    assert result.raw["mac"] == mac
    mock_connection.controller.clients_all.update.assert_called()


@pytest.mark.asyncio
async def test_raises_when_unknown_to_both_endpoints(mock_connection):
    mock_connection.controller.clients.values.return_value = []
    mock_connection.controller.clients_all.values.return_value = []

    mgr = ClientManager(mock_connection)
    with pytest.raises(UniFiNotFoundError):
        await mgr.get_client_details("zz:zz:zz:zz:zz:zz")


@pytest.mark.asyncio
async def test_active_with_raw_dict_fallback_shape(mock_connection):
    """When the active collection returns raw dicts (fallback path), still find the mac."""
    mac = "aa:bb:cc:dd:ee:ff"
    mock_connection.controller.clients.values.return_value = []

    # Simulate the get_clients() fallback that hits /stat/sta directly and
    # returns raw dicts (the existing code path when controller.clients is empty).
    async def request_returning_raw_dicts(_req):
        return [{"mac": mac, "uptime": 99}]

    mock_connection.request = AsyncMock(side_effect=request_returning_raw_dicts)
    mock_connection.controller.clients_all.values.return_value = []

    mgr = ClientManager(mock_connection)
    result = await mgr.get_client_details(mac)
    assert isinstance(result, dict) and result.get("mac") == mac
