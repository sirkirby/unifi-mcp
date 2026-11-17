"""Access errors must not carry the console's address.

The connection manager built its own proxy and Developer-API errors around the
absolute request URL and named the host in its connection failures, and
py-unifi-access quotes the URL or aiohttp's "Cannot connect to host <host>".
Access tools return that text. The origin goes, the request path and the
error class stay, and a 403 gains a fixed permission hint.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from unifi_access_api import ApiConnectionError, ApiForbiddenError, UnifiAccessApiClient
from unifi_core.access.managers.connection_manager import AccessConnectionManager
from unifi_core.exceptions import UniFiAuthError, UniFiConnectionError

HOST = "access-host-sentinel.example"
PROXY_HINT = "The Access account lacks permission for this operation"
TOKEN_HINT = "The UniFi Access API token lacks the permission"


def _assert_no_origin(text: str) -> None:
    assert HOST not in text
    assert "://" not in text


def _manager(**kwargs) -> AccessConnectionManager:
    return AccessConnectionManager(host=HOST, username="admin", password="pw", **kwargs)


def _response(status: int, *, text: str = "", payload=None) -> AsyncMock:
    response = AsyncMock()
    response.status = status
    response.text = AsyncMock(return_value=text)
    response.json = AsyncMock(return_value=payload)
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    return response


def _proxy(cm: AccessConnectionManager, *responses) -> None:
    session = MagicMock()
    session.request = MagicMock(side_effect=list(responses))
    cm._proxy_session = session
    cm._proxy_available = True
    cm._csrf_token = "csrf"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("request_method", "path", "expected_path"),
    [
        ("proxy_request", "doors", "/proxy/access/api/v2/doors"),
        ("proxy_request_ulp", "users/search", "/proxy/access/ulp-go/api/v2/users/search"),
        ("proxy_request_users", "users", "/proxy/users/api/v2/users"),
    ],
)
async def test_proxy_403_keeps_the_path_and_explains_the_permission(request_method, path, expected_path):
    cm = _manager()
    _proxy(cm, _response(403, text=f"forbidden for https://{HOST}/x"))

    with pytest.raises(UniFiConnectionError) as excinfo:
        await getattr(cm, request_method)("GET", path)

    text = str(excinfo.value)
    assert f"HTTP 403 GET {expected_path}" in text
    assert PROXY_HINT in text and "Full Management" in text
    _assert_no_origin(text)


@pytest.mark.asyncio
async def test_proxy_other_status_has_no_hint():
    cm = _manager()
    _proxy(cm, _response(500, text="boom"))

    with pytest.raises(UniFiConnectionError) as excinfo:
        await cm.proxy_request("GET", "doors")

    assert str(excinfo.value) == "Proxy request failed: HTTP 500 GET /proxy/access/api/v2/doors — boom"


@pytest.mark.asyncio
async def test_proxy_status_after_reauthentication_drops_the_origin():
    cm = _manager()
    _proxy(cm, _response(401), _response(403))
    cm._proxy_login = AsyncMock()

    with pytest.raises(UniFiConnectionError) as excinfo:
        await cm.proxy_request("GET", "doors")

    assert "after re-auth: HTTP 403 GET /proxy/access/api/v2/doors" in str(excinfo.value)
    assert PROXY_HINT in str(excinfo.value)
    _assert_no_origin(str(excinfo.value))


@pytest.mark.asyncio
async def test_proxy_application_error_drops_the_origin():
    cm = _manager()
    _proxy(cm, _response(200, payload={"code": -1, "codeS": "BAD", "msg": "nope"}))

    with pytest.raises(UniFiConnectionError) as excinfo:
        await cm.proxy_request("GET", "doors")

    assert str(excinfo.value) == "Proxy request failed: API code -1 BAD GET /proxy/access/api/v2/doors — nope"


def _developer(cm: AccessConnectionManager, behaviour) -> None:
    session = MagicMock()
    session.request = MagicMock(side_effect=behaviour)
    cm._api_session = session
    cm._api_client = MagicMock()
    cm._api_client_available = True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("behaviour", "expected"),
    [
        (
            [_response(500, payload={"msg": "server sad"})],
            "List visitors failed: HTTP 500 GET /api/v1/developer/visitors — server sad",
        ),
        (TimeoutError(), "List visitors failed: timed out after 10s GET /api/v1/developer/visitors"),
        (
            aiohttp.ClientConnectionError(f"Cannot connect to host {HOST}:12445 ssl:default"),
            "List visitors failed: Cannot connect to host <controller>:12445 ssl:default",
        ),
    ],
    ids=["status", "timeout", "transport"],
)
async def test_developer_request_errors_drop_the_origin(behaviour, expected):
    cm = _manager(api_key="key")
    _developer(cm, behaviour)

    with pytest.raises(UniFiConnectionError) as excinfo:
        await cm.developer_request("GET", "visitors", operation="List visitors")

    assert str(excinfo.value) == expected
    _assert_no_origin(str(excinfo.value))
    if excinfo.value.__cause__ is not None:
        _assert_no_origin(" ".join(str(arg) for arg in excinfo.value.__cause__.args))


@pytest.mark.asyncio
async def test_developer_request_auth_failure_is_unchanged():
    cm = _manager(api_key="key")
    _developer(cm, [_response(403, payload={"msg": "no"})])

    with pytest.raises(UniFiAuthError, match="requires a valid UniFi Access API token with visitor access: HTTP 403"):
        await cm.developer_request("GET", "visitors", operation="List visitors")


def test_connection_failure_messages_do_not_name_the_host():
    cm = _manager(api_key="key")
    cm._path_failures = [UniFiConnectionError("x")]

    for message in (cm._unreachable_message(), cm._rejected_message(), str(cm.unavailable_error("Doors"))):
        assert HOST not in message
    assert cm._unreachable_message().startswith("Could not connect to UniFi Access (tried ")
    assert cm._rejected_message().startswith("UniFi Access rejected the configured credentials (tried ")


@pytest.mark.asyncio
async def test_connect_timeout_message_does_not_name_the_host(monkeypatch):
    cm = _manager()

    async def _hang():
        raise TimeoutError

    monkeypatch.setattr(cm, "_try_api_client", _hang)

    with pytest.raises(UniFiConnectionError) as excinfo:
        await cm._connect_once()

    assert str(excinfo.value).startswith("Timed out after 15s connecting to UniFi Access.")
    _assert_no_origin(str(excinfo.value))


class _SdkSession:
    """An aiohttp-shaped session whose every request fails with ``error`` or answers ``status``."""

    closed = False

    def __init__(self, *, error: BaseException | None = None, status: int = 200) -> None:
        self._error = error
        self._status = status

    def request(self, *args, **kwargs):
        if self._error is not None:
            raise self._error
        return _response(self._status, text="Forbidden", payload={"code": "SUCCESS", "data": []})

    async def close(self):
        return None


async def _sdk_manager(monkeypatch, session: _SdkSession) -> AccessConnectionManager:
    cm = _manager(api_key="key", api_port=12445)
    monkeypatch.setattr(aiohttp, "ClientSession", lambda *args, **kwargs: session)
    monkeypatch.setattr(UnifiAccessApiClient, "authenticate", AsyncMock())
    await cm._try_api_client()
    assert cm.has_api_client
    return cm


@pytest.mark.asyncio
async def test_sdk_transport_error_drops_the_url_and_host(monkeypatch):
    cm = await _sdk_manager(
        monkeypatch, _SdkSession(error=aiohttp.ClientConnectionError(f"Cannot connect to host {HOST}:12445"))
    )

    with pytest.raises(ApiConnectionError) as excinfo:
        await cm.api_client.get_doors()

    _assert_no_origin(str(excinfo.value))
    assert "<controller>" in str(excinfo.value)


@pytest.mark.asyncio
async def test_sdk_timeout_keeps_the_path(monkeypatch):
    cm = await _sdk_manager(monkeypatch, _SdkSession(error=TimeoutError()))

    with pytest.raises(ApiConnectionError) as excinfo:
        await cm.api_client.get_doors()

    assert str(excinfo.value) == "Timeout connecting to /api/v1/developer/doors"


@pytest.mark.asyncio
async def test_sdk_forbidden_keeps_its_class_and_explains_the_token(monkeypatch):
    cm = await _sdk_manager(monkeypatch, _SdkSession(status=403))

    with pytest.raises(ApiForbiddenError) as excinfo:
        await cm.api_client.get_doors()

    assert TOKEN_HINT in str(excinfo.value)
    assert str(excinfo.value).count(TOKEN_HINT) == 1
    assert cm._is_rejected_login(excinfo.value)
