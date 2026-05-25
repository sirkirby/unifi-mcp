"""Tests for ClientManager.get_client_details — merges live /stat/sta
data with the /rest/user user-table snapshot, and tolerates a transient
failure on either endpoint.
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
async def test_merges_active_and_user_records(mock_connection):
    """For currently-connected clients, get_client_details merges
    /stat/sta (live data) with /rest/user (stable user-table fields).
    """
    mac = "aa:bb:cc:dd:ee:ff"
    live = _client(mac, last_seen=1779732658, signal=-52, uptime=3639515)
    user = _client(mac, _id="user-123", noted=True, use_fixedip=True, fixed_ip="10.0.0.5")
    mock_connection.controller.clients.values.return_value = [live]
    mock_connection.controller.clients_all.values.return_value = [user]

    mgr = ClientManager(mock_connection)
    result = await mgr.get_client_details(mac)

    # Live data wins for overlapping keys; user-table fields fill in
    assert result.raw["last_seen"] == 1779732658
    assert result.raw["signal"] == -52
    assert result.raw["_id"] == "user-123"
    assert result.raw["noted"] is True
    assert result.raw["use_fixedip"] is True
    assert result.raw["fixed_ip"] == "10.0.0.5"


@pytest.mark.asyncio
async def test_returns_user_only_when_not_active(mock_connection):
    """Offline client present only in /rest/user — returned as-is."""
    mac = "aa:bb:cc:dd:ee:ff"
    user = _client(mac, _id="user-123", noted=True, last_seen=1776076601)
    mock_connection.controller.clients.values.return_value = []
    mock_connection.controller.clients_all.values.return_value = [user]

    mgr = ClientManager(mock_connection)
    result = await mgr.get_client_details(mac)
    assert result.raw["_id"] == "user-123"


@pytest.mark.asyncio
async def test_returns_active_only_when_no_user_record(mock_connection):
    """Transient client present only in /stat/sta — returned as-is."""
    mac = "aa:bb:cc:dd:ee:ff"
    live = _client(mac, uptime=99, signal=-50)
    mock_connection.controller.clients.values.return_value = [live]
    mock_connection.controller.clients_all.values.return_value = []

    mgr = ClientManager(mock_connection)
    result = await mgr.get_client_details(mac)
    assert result.raw["uptime"] == 99


@pytest.mark.asyncio
async def test_falls_back_to_user_when_stat_sta_raises(mock_connection):
    """If /stat/sta fetch raises, /rest/user still resolves the lookup —
    a transient failure on one endpoint must not break the other.
    """
    mac = "aa:bb:cc:dd:ee:ff"
    user = _client(mac, _id="user-123", last_seen=1776076601)
    mock_connection.controller.clients.update.side_effect = RuntimeError("boom")
    mock_connection.controller.clients_all.values.return_value = [user]

    mgr = ClientManager(mock_connection)
    result = await mgr.get_client_details(mac)
    assert result.raw["_id"] == "user-123"


@pytest.mark.asyncio
async def test_falls_back_to_active_when_rest_user_raises(mock_connection):
    """And vice versa — /rest/user failure doesn't block lookup of active clients."""
    mac = "aa:bb:cc:dd:ee:ff"
    live = _client(mac, uptime=99, signal=-50)
    mock_connection.controller.clients.values.return_value = [live]
    mock_connection.controller.clients_all.update.side_effect = RuntimeError("boom")

    mgr = ClientManager(mock_connection)
    result = await mgr.get_client_details(mac)
    assert result.raw["uptime"] == 99


@pytest.mark.asyncio
async def test_raises_when_unknown_to_both_endpoints(mock_connection):
    mock_connection.controller.clients.values.return_value = []
    mock_connection.controller.clients_all.values.return_value = []

    mgr = ClientManager(mock_connection)
    with pytest.raises(UniFiNotFoundError):
        await mgr.get_client_details("zz:zz:zz:zz:zz:zz")


@pytest.mark.asyncio
async def test_reraises_underlying_error_when_both_endpoints_raise(mock_connection):
    """Both endpoints failing is an outage, not a not-found — surface the
    underlying connectivity error so callers see the real cause instead
    of a misleading UniFiNotFoundError.
    """
    mock_connection.controller.clients.update.side_effect = RuntimeError("boom")
    mock_connection.controller.clients_all.update.side_effect = RuntimeError("boom")

    mgr = ClientManager(mock_connection)
    with pytest.raises(RuntimeError, match="boom"):
        await mgr.get_client_details("zz:zz:zz:zz:zz:zz")


@pytest.mark.asyncio
async def test_returns_object_with_raw_for_dict_only_source(mock_connection):
    """Even when only one endpoint returns the client AND that endpoint
    returned a raw dict (the /stat/sta fallback path), get_client_details
    normalizes the return shape to an object with .mac and .raw so
    downstream mutation tools can rely on attribute access.
    """
    mac = "aa:bb:cc:dd:ee:ff"
    mock_connection.controller.clients.values.return_value = []

    async def request_returning_raw_dicts(_req):
        return [{"mac": mac, "_id": "u1", "uptime": 99}]

    mock_connection.request = AsyncMock(side_effect=request_returning_raw_dicts)
    mock_connection.controller.clients_all.values.return_value = []

    mgr = ClientManager(mock_connection)
    result = await mgr.get_client_details(mac)
    # Caller contract: .mac and .raw always available, regardless of source.
    assert result.mac == mac
    assert result.raw["_id"] == "u1"
    assert result.raw["uptime"] == 99
