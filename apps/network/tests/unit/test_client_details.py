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


# --- per-MAC fallback via GET /stat/user/<mac> --------------------------------
# Authoritative for one client: 200 with the record for a known MAC, HTTP 400
# ``api.err.UnknownUser`` for an unknown one. See client_manager.REST_USER_ROW_CAP.


def _unknown_user(mac: str):
    from aiounifi.errors import AiounifiException

    return AiounifiException({"meta": {"rc": "error", "mac": mac, "msg": "api.err.UnknownUser"}, "data": []})


def _route_stat_user(mock_connection, *, record=None, error=None):
    """Answer ``/stat/user/<mac>`` and leave the list fallbacks at ``None``.

    Returns a namespace recording the ``/stat/user/`` paths issued and the
    ``(path, data)`` of every PUT, which is what the assertions look at.
    """
    from types import SimpleNamespace

    seen = SimpleNamespace(stat_user=[], puts=[])

    async def _request(req):
        if req.method == "put":
            seen.puts.append((req.path, req.data))
        if req.path.startswith("/stat/user/"):
            seen.stat_user.append(req.path)
            if error is not None:
                raise error
            return [record] if record is not None else []
        return None

    mock_connection.request = AsyncMock(side_effect=_request)
    return seen


@pytest.mark.asyncio
async def test_resolves_via_stat_user_when_both_lists_miss(mock_connection):
    mac = "aa:bb:cc:dd:ee:ff"
    seen = _route_stat_user(mock_connection, record={"mac": mac, "_id": "u-3001", "noted": True})

    result = await ClientManager(mock_connection).get_client_details(mac)

    assert result.mac == mac
    assert result.raw["_id"] == "u-3001"
    assert seen.stat_user == [f"/stat/user/{mac}"]


@pytest.mark.asyncio
async def test_stat_user_supplies_id_for_active_client_missing_from_rest_user(mock_connection):
    """An online client past the cap is in /stat/sta but not /rest/user; the
    per-MAC record supplies the ``_id`` that rename and set_ip need, and the
    live fields still win on overlap."""
    mac = "aa:bb:cc:dd:ee:ff"
    mock_connection.controller.clients.values.return_value = [_client(mac, signal=-50, uptime=99)]
    _route_stat_user(mock_connection, record={"mac": mac, "_id": "u-3001", "uptime": 1})

    result = await ClientManager(mock_connection).get_client_details(mac)

    assert result.raw["_id"] == "u-3001"
    assert result.raw["signal"] == -50
    assert result.raw["uptime"] == 99


@pytest.mark.asyncio
async def test_stat_user_unknown_user_raises_not_found(mock_connection):
    mac = "aa:bb:cc:dd:ee:ff"
    _route_stat_user(mock_connection, error=_unknown_user(mac))

    with pytest.raises(UniFiNotFoundError):
        await ClientManager(mock_connection).get_client_details(mac)


@pytest.mark.asyncio
async def test_stat_user_network_error_is_not_reported_as_not_found(mock_connection):
    from unifi_core.exceptions import UniFiOperationError

    mac = "aa:bb:cc:dd:ee:ff"
    cause = RuntimeError("boom")
    _route_stat_user(mock_connection, error=cause)

    with pytest.raises(UniFiOperationError) as excinfo:
        await ClientManager(mock_connection).get_client_details(mac)

    assert "could not be determined" in str(excinfo.value)
    assert "3000" in str(excinfo.value)
    assert excinfo.value.__cause__ is cause


@pytest.mark.asyncio
async def test_stat_user_skipped_for_non_mac_identifier(mock_connection):
    """stats_manager passes a client ``_id`` through this path; an opaque id
    must not be sent to /stat/user/."""
    seen = _route_stat_user(mock_connection, record={"mac": "aa:bb:cc:dd:ee:ff", "_id": "u-1"})

    with pytest.raises(UniFiNotFoundError):
        await ClientManager(mock_connection).get_client_details("5f1e2d3c4b5a697877665544")

    assert seen.stat_user == []


@pytest.mark.asyncio
async def test_stat_user_uses_canonical_colon_path(mock_connection):
    """Our convention, not a controller requirement: the controller accepts
    any spelling, and its own payloads are lowercase colon-separated."""
    seen = _route_stat_user(mock_connection, record={"mac": "aa:bb:cc:dd:ee:ff", "_id": "u-1"})

    await ClientManager(mock_connection).get_client_details("AA-BB-CC-DD-EE-FF")

    assert seen.stat_user == ["/stat/user/aa:bb:cc:dd:ee:ff"]


@pytest.mark.asyncio
async def test_rename_client_works_for_client_only_reachable_via_stat_user(mock_connection):
    mac = "aa:bb:cc:dd:ee:ff"
    seen = _route_stat_user(mock_connection, record={"mac": mac, "_id": "u-3001"})

    assert await ClientManager(mock_connection).rename_client(mac, "printer") is True

    assert seen.puts == [("/rest/user/u-3001", {"name": "printer"})]


@pytest.mark.asyncio
async def test_reraises_list_error_when_both_lists_and_stat_user_raise(mock_connection):
    """Outage semantics are unchanged: when every endpoint fails, callers see
    the list error, not a not-found and not the per-MAC error."""
    mock_connection.controller.clients.update.side_effect = RuntimeError("list boom")
    mock_connection.controller.clients_all.update.side_effect = RuntimeError("list boom")
    _route_stat_user(mock_connection, error=RuntimeError("per-mac boom"))

    with pytest.raises(RuntimeError, match="list boom"):
        await ClientManager(mock_connection).get_client_details("aa:bb:cc:dd:ee:ff")


@pytest.mark.asyncio
async def test_existence_checks_stop_at_the_live_record(mock_connection):
    """block/unblock/kick/guest-auth only need to know the client exists; an
    online client past the cap must not cost them a per-MAC request."""
    mac = "aa:bb:cc:dd:ee:ff"
    mock_connection.controller.clients.values.return_value = [_client(mac, signal=-50)]
    seen = _route_stat_user(mock_connection, record={"mac": mac, "_id": "u-3001"})

    await ClientManager(mock_connection).block_client(mac)

    assert seen.stat_user == []


@pytest.mark.asyncio
async def test_existence_check_still_falls_back_when_both_lists_miss(mock_connection):
    mac = "aa:bb:cc:dd:ee:ff"
    seen = _route_stat_user(mock_connection, record={"mac": mac, "_id": "u-3001"})

    await ClientManager(mock_connection).block_client(mac)

    assert seen.stat_user == [f"/stat/user/{mac}"]


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [None, {}, "html", ["str"]])
async def test_unexpected_stat_user_reply_is_not_reported_as_not_found(mock_connection, reply):
    """A non-JSON or malformed reply (proxy interstitial, controller mid-restart)
    is a failed lookup, not a fact about the client."""
    from unifi_core.exceptions import UniFiOperationError

    mock_connection.request = AsyncMock(return_value=reply)

    with pytest.raises(UniFiOperationError):
        await ClientManager(mock_connection).get_client_details("aa:bb:cc:dd:ee:ff")


@pytest.mark.asyncio
async def test_empty_stat_user_reply_is_a_soft_miss(mock_connection):
    _route_stat_user(mock_connection)

    with pytest.raises(UniFiNotFoundError):
        await ClientManager(mock_connection).get_client_details("aa:bb:cc:dd:ee:ff")


@pytest.mark.asyncio
async def test_stat_user_404_keeps_the_list_verdict(mock_connection):
    """A controller that does not serve /stat/user answers 404 (aiounifi
    ResponseError); that is no answer, so the lists' not-found stands."""
    from aiounifi.errors import ResponseError

    _route_stat_user(mock_connection, error=ResponseError("Call https://c/stat/user/x received 404 Not Found"))

    with pytest.raises(UniFiNotFoundError):
        await ClientManager(mock_connection).get_client_details("aa:bb:cc:dd:ee:ff")


@pytest.mark.asyncio
async def test_unknown_user_wins_over_list_errors(mock_connection):
    mac = "aa:bb:cc:dd:ee:ff"
    mock_connection.controller.clients.update.side_effect = RuntimeError("list boom")
    mock_connection.controller.clients_all.update.side_effect = RuntimeError("list boom")
    _route_stat_user(mock_connection, error=_unknown_user(mac))

    with pytest.raises(UniFiNotFoundError):
        await ClientManager(mock_connection).get_client_details(mac)


@pytest.mark.asyncio
async def test_stat_user_resolves_when_rest_user_raised(mock_connection):
    mac = "aa:bb:cc:dd:ee:ff"
    mock_connection.controller.clients_all.update.side_effect = RuntimeError("boom")
    _route_stat_user(mock_connection, record={"mac": mac, "_id": "u-3001"})

    result = await ClientManager(mock_connection).get_client_details(mac)

    assert result.raw["_id"] == "u-3001"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call",
    [
        lambda mgr, mac: mgr.block_client(mac),
        lambda mgr, mac: mgr.unblock_client(mac),
        lambda mgr, mac: mgr.force_reconnect_client(mac),
        lambda mgr, mac: mgr.authorize_guest(mac, 60),
        lambda mgr, mac: mgr.unauthorize_guest(mac),
    ],
    ids=["block", "unblock", "kick", "authorize", "unauthorize"],
)
async def test_every_existence_only_caller_skips_the_per_mac_request(mock_connection, call):
    mac = "aa:bb:cc:dd:ee:ff"
    mock_connection.controller.clients.values.return_value = [_client(mac, signal=-50)]
    seen = _route_stat_user(mock_connection, record={"mac": mac, "_id": "u-3001"})

    await call(ClientManager(mock_connection), mac)

    assert seen.stat_user == []


@pytest.mark.asyncio
async def test_stat_user_429_is_not_reported_as_not_found(mock_connection):
    """aiounifi raises the same ResponseError for HTTP 429; only a 404 is
    "no such endpoint"."""
    from aiounifi.errors import ResponseError

    from unifi_core.exceptions import UniFiOperationError

    _route_stat_user(mock_connection, error=ResponseError("Call https://c/stat/user/x received 429: b''"))

    with pytest.raises(UniFiOperationError):
        await ClientManager(mock_connection).get_client_details("aa:bb:cc:dd:ee:ff")
