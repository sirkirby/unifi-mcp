"""Network credential negotiation keeps reads, sessions and public APIs distinct."""

import asyncio
import json
from contextlib import contextmanager
from unittest.mock import AsyncMock, Mock, patch

import pytest
from unifi_core.auth import UniFiAuth
from unifi_core.exceptions import UniFiAuthError
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.network_manager import NetworkManager
from yarl import URL


@contextmanager
def responses():
    """Fake the HTTP boundary without depending on aiohttp response internals."""
    routes = {}

    class Routes:
        def get(self, url, *, payload=None, status=200, body=None):
            parsed = URL(url)
            routes[(parsed.path, tuple(sorted(parsed.query.items())))] = (status, payload, body)

    async def request(session, method, url, **kwargs):
        parsed = URL(url)
        query = kwargs.get("params") or parsed.query
        key = (parsed.path, tuple(sorted((k, str(v)) for k, v in query.items())))
        assert method.upper() == "GET"
        assert key in routes, f"Unexpected synthetic request: {key}"
        status, payload, body = routes.pop(key)
        response = AsyncMock()
        response.status = status
        response.content_type = "application/json"
        response.json.return_value = payload
        response.read.return_value = (body or json.dumps(payload)).encode()
        response.__aenter__.return_value = response
        response.__aexit__.return_value = None
        return response

    with patch("aiohttp.ClientSession._request", new=request):
        yield Routes()


def connection(username="", password=""):
    return ConnectionManager("controller.test", username, password, auth=UniFiAuth(api_key="synthetic-key"))


@pytest.mark.asyncio
async def test_key_only_legacy_inventory_preserves_ids_without_login(monkeypatch):
    monkeypatch.setenv("UNIFI_CONTROLLER_TYPE", "proxy")
    cm = connection()
    with responses() as http, patch("aiounifi.controller.Controller.login", new_callable=AsyncMock) as login:
        http.get("https://controller.test:443/proxy/network/api/self/sites", payload={"meta": {"rc": "ok"}, "data": []})
        http.get(
            "https://controller.test:443/proxy/network/api/s/default/rest/networkconf",
            payload={"meta": {"rc": "ok"}, "data": [{"_id": "legacy-id", "name": "synthetic"}]},
        )
        try:
            assert await cm.initialize()
            assert (await NetworkManager(cm).get_networks())[0]["_id"] == "legacy-id"
            assert cm.authentication_status.api_key_available is True
            assert not cm.authentication_status.session_available
            assert not cm.integration_inventory_only
            assert cm._aiohttp_session.headers["X-API-Key"] == "synthetic-key"
            assert len(cm._aiohttp_session.cookie_jar) == 0
            assert not cm.controller.connectivity.can_retry_login
            login.assert_not_awaited()
        finally:
            await cm.close()


@pytest.mark.asyncio
async def test_public_only_key_survives_rejected_legacy_and_failed_session(monkeypatch):
    monkeypatch.setenv("UNIFI_CONTROLLER_TYPE", "direct")
    cm = connection("user", "password")
    with responses() as http, patch.object(cm, "_initialize_session", new=AsyncMock(return_value=False)):
        http.get("https://controller.test:443/api/self/sites", status=403)
        http.get(
            "https://controller.test:443/integration/v1/sites?limit=1&offset=0", payload={"data": [], "totalCount": 0}
        )
        try:
            assert await cm.initialize()
            assert cm.integration_inventory_only
            assert cm.authentication_status.api_key_available
        finally:
            await cm.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("session_succeeds", [True, False])
async def test_post_construction_auth_preserves_legacy_session_contract(session_succeeds):
    cm = ConnectionManager("controller.test", "user", "password")
    cm.unifi_auth = UniFiAuth(api_key="synthetic-key")
    with (
        patch.object(cm, "_initialize_session", new=AsyncMock(return_value=session_succeeds)) as session,
        patch.object(cm, "_initialize_key", new_callable=AsyncMock) as key,
    ):
        assert cm.has_api_key
        assert await cm.initialize() is session_succeeds
        session.assert_awaited_once()
        key.assert_not_awaited()


@pytest.mark.asyncio
async def test_working_session_is_preserved_when_both_credentials_configured():
    cm = connection("user", "password")
    with (
        patch.object(cm, "_initialize_session", new=AsyncMock(return_value=True)),
        patch.object(cm, "_initialize_key", new_callable=AsyncMock) as key,
    ):
        assert await cm.initialize()
        key.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/proxy/network/api/s/default/cmd/devmgr"),
        ("PUT", "/proxy/network/api/s/default/rest/networkconf"),
        ("GET", "/proxy/network/api/s/default/get/setting"),
        ("GET", "/proxy/network/api/s/other/stat/device"),
    ],
)
async def test_direct_sdk_transport_rejects_unvalidated_operations(method, path):
    cm = connection()
    request = Mock(method=method, url=URL("https://controller.test" + path))
    handler = AsyncMock()
    with pytest.raises(UniFiAuthError, match="requires Network session"):
        await cm._key_read_transport(request, handler)
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_key_transport_cannot_forward_credentials_to_other_origin():
    cm = connection()
    handler = AsyncMock()
    with pytest.raises(UniFiAuthError, match="cannot leave"):
        await cm._key_read_transport(Mock(method="GET", url=URL("https://other.test/api/self/sites")), handler)
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_key_rejection_never_attempts_session_reauthentication():
    cm = connection()
    cm._key_mode = True
    assert not await cm._reauthenticate(0)
    assert "API-key request rejected" in cm.last_connection_error


@pytest.mark.asyncio
async def test_public_error_does_not_expose_controller_secrets():
    cm = connection()
    with responses() as http:
        http.get("https://controller.test:443/proxy/network/integration/v1/sites", status=403, body="controller-secret")
        with pytest.raises(UniFiAuthError) as error:
            await cm.request_integration("/v1/sites")
        assert "HTTP 403" in str(error.value)
        assert "controller-secret" not in str(error.value)


@pytest.mark.asyncio
async def test_failed_key_probe_is_cooled_down_independently():
    cm = connection()
    with patch.object(cm, "_initialize_key", new=AsyncMock(return_value=False)) as probe:
        assert not await cm.initialize()
        assert not await cm.initialize()
        assert probe.await_count == 1
        assert not cm.reconnect_blocked


@pytest.mark.asyncio
async def test_closed_key_session_is_not_reported_as_usable(monkeypatch):
    monkeypatch.setenv("UNIFI_CONTROLLER_TYPE", "direct")
    cm = connection()
    with responses() as http:
        http.get("https://controller.test/api/self/sites", payload={"meta": {"rc": "ok"}, "data": []})
        assert await cm.initialize()
        await cm._aiohttp_session.close()
        with patch.object(cm, "_initialize_key", new=AsyncMock(return_value=False)) as probe:
            assert not await cm.initialize()
            probe.assert_awaited_once()
        await cm.close()


@pytest.mark.asyncio
async def test_cancelled_key_probe_closes_unowned_session(monkeypatch):
    monkeypatch.setenv("UNIFI_CONTROLLER_TYPE", "direct")
    cm = connection()
    session = Mock()
    session.get.side_effect = asyncio.CancelledError
    session.close = AsyncMock()
    with patch.object(cm.unifi_auth, "get_api_key_session", new=AsyncMock(return_value=session)):
        with pytest.raises(asyncio.CancelledError):
            await cm.initialize()
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_public_error_envelope_does_not_authenticate(monkeypatch):
    monkeypatch.setenv("UNIFI_CONTROLLER_TYPE", "direct")
    cm = connection()
    with responses() as http:
        http.get("https://controller.test/api/self/sites", status=403)
        http.get("https://controller.test/integration/v1/sites?limit=1&offset=0", payload={"error": "synthetic"})
        assert not await cm.initialize()
        assert not cm.integration_inventory_only


@pytest.mark.asyncio
@pytest.mark.parametrize("public", [False, True])
async def test_rate_limit_stops_capability_negotiation(monkeypatch, public):
    monkeypatch.setenv("UNIFI_CONTROLLER_TYPE", "direct")
    cm = connection()
    with responses() as http:
        http.get("https://controller.test/api/self/sites", status=403 if public else 429)
        if public:
            http.get("https://controller.test/integration/v1/sites?limit=1&offset=0", status=429)
        assert not await cm.initialize()
        assert "rate limited" in cm.last_connection_error
        assert not await cm.initialize()
