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

    # ConnectionManager.refresh_handler() is how the managers refresh a
    # handler collection now; delegate to the same ``update()`` these
    # tests already stub so their setup keeps its meaning.
    async def _refresh_handler(name, _c=conn):
        return await getattr(_c.controller, name).update()

    conn.refresh_handler = _refresh_handler
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
@pytest.mark.parametrize(
    "live, user, stat_sta_raises, rest_user_raises, key, expected",
    [
        pytest.param(
            None, {"_id": "user-123", "noted": True}, False, False, "_id", "user-123", id="user-only-when-not-active"
        ),
        pytest.param({"uptime": 99}, None, False, False, "uptime", 99, id="active-only-when-no-user-record"),
        pytest.param(None, {"_id": "user-123"}, True, False, "_id", "user-123", id="user-when-stat-sta-raises"),
        pytest.param({"uptime": 99}, None, False, True, "uptime", 99, id="active-when-rest-user-raises"),
    ],
)
async def test_single_source_lookup(mock_connection, live, user, stat_sta_raises, rest_user_raises, key, expected):
    """A client known to only one endpoint is returned as-is, and a transient
    failure on one endpoint must not break the other."""
    mac = "aa:bb:cc:dd:ee:ff"
    mock_connection.controller.clients.values.return_value = [_client(mac, **live)] if live else []
    mock_connection.controller.clients_all.values.return_value = [_client(mac, **user)] if user else []
    if stat_sta_raises:
        mock_connection.controller.clients.update.side_effect = RuntimeError("boom")
    if rest_user_raises:
        mock_connection.controller.clients_all.update.side_effect = RuntimeError("boom")

    result = await ClientManager(mock_connection).get_client_details(mac)

    assert result.raw[key] == expected


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
