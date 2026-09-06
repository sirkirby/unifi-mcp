"""``ClientManager.get_client_details`` past the ``/rest/user`` row cap.

The controller caps ``GET /rest/user`` at 3,000 rows. A client past that
window is absent from the list scan although the controller has its record,
so the manager falls back to the authoritative per-MAC ``GET /stat/user/<mac>``:
200 with the record for a known MAC, HTTP 400 ``api.err.UnknownUser`` for an
unknown one. Any other failure of that request leaves existence undetermined
and must never be reported as a not-found.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.errors import AiounifiException, RequestError, ResponseError
from unifi_core.exceptions import UniFiNotFoundError, UniFiOperationError
from unifi_core.network.managers.client_manager import ClientManager

MAC = "aa:bb:cc:dd:ee:ff"


@pytest.fixture
def mock_connection():
    conn = MagicMock()
    conn.site = "default"
    conn.get_cached = MagicMock(return_value=None)
    conn._update_cache = MagicMock()
    conn._invalidate_cache = MagicMock()
    conn.ensure_connected = AsyncMock(return_value=True)

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


def _unknown_user(mac: str) -> AiounifiException:
    return AiounifiException({"meta": {"rc": "error", "mac": mac, "msg": "api.err.UnknownUser"}, "data": []})


def _route_stat_user(mock_connection, *, record=None, error=None):
    """Answer ``/stat/user/<mac>`` and leave the list fallbacks at ``None``.

    Returns a namespace recording the ``/stat/user/`` paths issued and the
    ``(path, data)`` of every PUT, which is what the assertions look at.
    """
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
    mac = MAC
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
    mac = MAC
    mock_connection.controller.clients.values.return_value = [_client(mac, signal=-50, uptime=99)]
    _route_stat_user(mock_connection, record={"mac": mac, "_id": "u-3001", "uptime": 1})

    result = await ClientManager(mock_connection).get_client_details(mac)

    assert result.raw["_id"] == "u-3001"
    assert result.raw["signal"] == -50
    assert result.raw["uptime"] == 99


@pytest.mark.asyncio
async def test_stat_user_unknown_user_raises_not_found(mock_connection):
    mac = MAC
    _route_stat_user(mock_connection, error=_unknown_user(mac))

    with pytest.raises(UniFiNotFoundError):
        await ClientManager(mock_connection).get_client_details(mac)


@pytest.mark.asyncio
async def test_stat_user_network_error_is_not_reported_as_not_found(mock_connection):

    mac = MAC
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
    seen = _route_stat_user(mock_connection, record={"mac": MAC, "_id": "u-1"})

    with pytest.raises(UniFiNotFoundError):
        await ClientManager(mock_connection).get_client_details("5f1e2d3c4b5a697877665544")

    assert seen.stat_user == []


@pytest.mark.asyncio
async def test_stat_user_uses_canonical_colon_path(mock_connection):
    """Our convention, not a controller requirement: the controller accepts
    any spelling, and its own payloads are lowercase colon-separated."""
    seen = _route_stat_user(mock_connection, record={"mac": MAC, "_id": "u-1"})

    await ClientManager(mock_connection).get_client_details("AA-BB-CC-DD-EE-FF")

    assert seen.stat_user == ["/stat/user/aa:bb:cc:dd:ee:ff"]


@pytest.mark.asyncio
async def test_rename_client_works_for_client_only_reachable_via_stat_user(mock_connection):
    mac = MAC
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
        await ClientManager(mock_connection).get_client_details(MAC)


@pytest.mark.asyncio
async def test_existence_checks_stop_at_the_live_record(mock_connection):
    """block/unblock/kick/guest-auth only need to know the client exists; an
    online client past the cap must not cost them a per-MAC request."""
    mac = MAC
    mock_connection.controller.clients.values.return_value = [_client(mac, signal=-50)]
    seen = _route_stat_user(mock_connection, record={"mac": mac, "_id": "u-3001"})

    await ClientManager(mock_connection).block_client(mac)

    assert seen.stat_user == []


@pytest.mark.asyncio
async def test_existence_check_still_falls_back_when_both_lists_miss(mock_connection):
    mac = MAC
    seen = _route_stat_user(mock_connection, record={"mac": mac, "_id": "u-3001"})

    await ClientManager(mock_connection).block_client(mac)

    assert seen.stat_user == [f"/stat/user/{mac}"]


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [None, {}, "html", ["str"]])
async def test_unexpected_stat_user_reply_is_not_reported_as_not_found(mock_connection, reply):
    """A non-JSON or malformed reply (proxy interstitial, controller mid-restart)
    is a failed lookup, not a fact about the client."""

    mock_connection.request = AsyncMock(return_value=reply)

    with pytest.raises(UniFiOperationError):
        await ClientManager(mock_connection).get_client_details(MAC)


@pytest.mark.asyncio
async def test_empty_stat_user_reply_is_a_soft_miss(mock_connection):
    _route_stat_user(mock_connection)

    with pytest.raises(UniFiNotFoundError):
        await ClientManager(mock_connection).get_client_details(MAC)


@pytest.mark.asyncio
async def test_stat_user_404_keeps_the_list_verdict(mock_connection):
    """A controller that does not serve /stat/user answers 404 (aiounifi
    ResponseError); that is no answer, so the lists' not-found stands."""

    _route_stat_user(mock_connection, error=ResponseError("Call https://c/stat/user/x received 404 Not Found"))

    with pytest.raises(UniFiNotFoundError):
        await ClientManager(mock_connection).get_client_details(MAC)


@pytest.mark.asyncio
async def test_unknown_user_wins_over_list_errors(mock_connection):
    mac = MAC
    mock_connection.controller.clients.update.side_effect = RuntimeError("list boom")
    mock_connection.controller.clients_all.update.side_effect = RuntimeError("list boom")
    _route_stat_user(mock_connection, error=_unknown_user(mac))

    with pytest.raises(UniFiNotFoundError):
        await ClientManager(mock_connection).get_client_details(mac)


@pytest.mark.asyncio
async def test_stat_user_resolves_when_rest_user_raised(mock_connection):
    mac = MAC
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
    mac = MAC
    mock_connection.controller.clients.values.return_value = [_client(mac, signal=-50)]
    seen = _route_stat_user(mock_connection, record={"mac": mac, "_id": "u-3001"})

    await call(ClientManager(mock_connection), mac)

    assert seen.stat_user == []


@pytest.mark.asyncio
async def test_stat_user_429_is_not_reported_as_not_found(mock_connection):
    """aiounifi raises the same ResponseError for HTTP 429; only a 404 is
    "no such endpoint"."""

    _route_stat_user(mock_connection, error=ResponseError("Call https://c/stat/user/x received 429: b''"))

    with pytest.raises(UniFiOperationError):
        await ClientManager(mock_connection).get_client_details(MAC)


# --- the HTTP status of a ResponseError -------------------------------------
# aiounifi raises one ResponseError class for HTTP 404 and 429 and carries no
# status attribute; its message is ``Call <url> received <status>[: <body>]``.
# Only that status segment may decide; the URL and the body can contain 404.


@pytest.mark.asyncio
async def test_stat_user_429_from_a_host_named_404_is_not_reported_as_not_found(mock_connection):
    """The maintainer's reproduction: a 429 whose URL host carries the digits
    404 must not become a not-found."""
    url = f"https://controller404.example/proxy/network/api/s/default/stat/user/{MAC}"
    _route_stat_user(mock_connection, error=ResponseError(f"Call {url} received 429: b''"))

    with pytest.raises(UniFiOperationError):
        await ClientManager(mock_connection).get_client_details(MAC)


@pytest.mark.asyncio
async def test_stat_user_429_whose_body_mentions_404_is_not_reported_as_not_found(mock_connection):
    url = f"https://c/proxy/network/api/s/default/stat/user/{MAC}"
    body = b'{"code":"RATE_LIMITED","message":"see error 404 docs"}'
    _route_stat_user(mock_connection, error=ResponseError(f"Call {url} received 429: {body!r}"))

    with pytest.raises(UniFiOperationError):
        await ClientManager(mock_connection).get_client_details(MAC)


@pytest.mark.asyncio
async def test_stat_user_404_from_a_host_named_429_keeps_the_list_verdict(mock_connection):
    url = f"https://controller429.example/proxy/network/api/s/default/stat/user/{MAC}"
    _route_stat_user(mock_connection, error=ResponseError(f"Call {url} received 404 Not Found"))

    with pytest.raises(UniFiNotFoundError):
        await ClientManager(mock_connection).get_client_details(MAC)


@pytest.mark.asyncio
async def test_stat_user_response_error_without_a_status_is_undetermined(mock_connection):
    """A ResponseError that carries no status segment is not a 404."""
    _route_stat_user(mock_connection, error=ResponseError("invalid response, expected 404 or json"))

    with pytest.raises(UniFiOperationError):
        await ClientManager(mock_connection).get_client_details(MAC)


@pytest.mark.asyncio
async def test_stat_user_transport_error_with_404_in_the_url_is_undetermined(mock_connection):
    """aiounifi's transport error quotes the URL too; it is never a not-found."""
    url = f"https://controller404.example/proxy/network/api/s/default/stat/user/{MAC}"
    cause = RequestError(f"Error requesting data from {url}: Cannot connect to host")
    _route_stat_user(mock_connection, error=cause)

    with pytest.raises(UniFiOperationError) as excinfo:
        await ClientManager(mock_connection).get_client_details(MAC)

    assert excinfo.value.__cause__ is cause


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Call https://c/api/s/default/stat/user/x received 404 Not Found", 404),
        ("Call https://controller404.example/stat/user/x received 429: b''", 429),
        ("Call https://c/stat/user/x received 429: b'received 404'", 429),
        ("Call https://c/stat/user/x received 503 service unavailable", 503),
        ("received 404", None),
        ("Call https://c/stat/user/x received 4040", None),
        ("plain text 404", None),
        ("", None),
    ],
)
def test_response_status_reads_only_the_status_segment(message, expected):
    from unifi_core.network.managers.connection_manager import response_status

    assert response_status(ResponseError(message)) == expected


def test_response_status_ignores_other_exception_types():
    from unifi_core.network.managers.connection_manager import response_status

    assert response_status(RequestError("Call https://c/x received 404 Not Found")) is None
    assert response_status(RuntimeError("Call https://c/x received 404 Not Found")) is None
