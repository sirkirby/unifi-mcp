"""Protect errors must not carry the controller's address.

uiprotect quotes the absolute request URL in its status errors ("Request
failed: <url> - Status: …") and names the host in transport errors ("Error
requesting data from <host>: …"). Protect tools return that text, so the
connection manager wraps the SDK client's request methods: the origin goes,
the path, status and class stay, and a 403 gains a fixed permission hint.
"""

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from uiprotect import ProtectApiClient
from uiprotect.exceptions import BadRequest, NotAuthorized, NvrError
from unifi_core.protect.errors import nvr_status, safe_protect_error
from unifi_core.protect.managers import connection_manager as module
from yarl import URL

HOST = "protect-host-sentinel.example"
HINT = "The Protect account lacks permission for this operation"


class _Client(ProtectApiClient):
    """The real SDK client, with the bootstrap fetch and the session stubbed."""

    async def update(self):  # noqa: D102 - stub
        return None

    async def close_session(self):  # noqa: D102 - stub
        return None

    async def async_disconnect_ws(self):  # noqa: D102 - stub
        return None


class _FailingSession:
    closed = False

    def request(self, *args, **kwargs):
        raise aiohttp.ClientConnectionError(f"Cannot connect to host {HOST}:443 ssl:default [Connection refused]")

    async def close(self):
        return None


def _response(status: int, reason: str = "Forbidden") -> MagicMock:
    response = MagicMock()
    response.status = status
    response.url = URL(f"https://{HOST}:443/proxy/protect/api/cameras/abc")
    response.reason = reason
    response.json = AsyncMock(side_effect=ValueError("not json"))
    response.text = AsyncMock(return_value=reason)
    return response


@pytest.fixture
async def manager(monkeypatch):
    monkeypatch.setattr(module, "ProtectApiClient", _Client)
    cm = module.ProtectConnectionManager(host=HOST, username="u", password="p", verify_ssl=False)
    assert await cm.initialize()
    yield cm
    await cm.close()


def _assert_no_origin(text: str) -> None:
    assert HOST not in text
    assert "://" not in text


@pytest.mark.asyncio
async def test_forbidden_status_keeps_the_path_status_and_class_and_explains_the_403(manager):
    with pytest.raises(NotAuthorized) as excinfo:
        await manager.client._raise_for_status(_response(403))

    text = str(excinfo.value)
    assert text.startswith("Request failed: /proxy/protect/api/cameras/abc - Status: 403 - Reason: Forbidden. ")
    assert HINT in text and "Full Management" in text
    _assert_no_origin(text)
    assert nvr_status(excinfo.value) == 403
    # The translation the read tools use keeps classifying it as a permission failure.
    assert type(safe_protect_error("Listing cameras", excinfo.value)).__name__ == "UniFiPermissionError"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error_type"),
    [(401, NotAuthorized), (404, BadRequest), (429, NvrError), (500, NvrError)],
)
async def test_other_statuses_drop_the_origin_without_a_hint(manager, status, error_type):
    with pytest.raises(error_type) as excinfo:
        await manager.client._raise_for_status(_response(status, reason="nope"))

    text = str(excinfo.value)
    assert text.startswith(f"Request failed: /proxy/protect/api/cameras/abc - Status: {status} - Reason: nope")
    assert HINT not in text
    _assert_no_origin(text)
    assert nvr_status(excinfo.value) == status
    # Login rate-limit and rejection detection read the same text.
    assert module._is_terminal_auth_error(excinfo.value) is (status in (401, 429))


@pytest.mark.asyncio
async def test_transport_error_drops_the_host_from_the_error_and_its_cause(manager, monkeypatch):
    monkeypatch.setattr(manager.client, "get_session", AsyncMock(return_value=_FailingSession()))

    with pytest.raises(NvrError) as excinfo:
        await manager.client.request("get", "/proxy/protect/api/cameras")

    assert str(excinfo.value).startswith("Error requesting data from <controller>: ")
    _assert_no_origin(str(excinfo.value))
    _assert_no_origin(str(excinfo.value.__cause__))


@pytest.mark.asyncio
async def test_a_model_save_reaches_the_wrapped_methods(manager):
    """Model methods call the client they hold, so the wrapper must live on that instance."""
    client = manager.client

    async def _request(*args, **kwargs):
        return _response(403)

    # ``api_request_raw`` reads ``self.request`` and ``self._raise_for_status``;
    # stub the transport and let the wrapped status check raise.
    original_request = client.request
    client.request = AsyncMock(side_effect=_request)
    try:
        with pytest.raises(NotAuthorized) as excinfo:
            await client.api_request_raw("cameras/abc", method="patch")
    finally:
        client.request = original_request

    assert HINT in str(excinfo.value)
    _assert_no_origin(str(excinfo.value))


@pytest.mark.asyncio
async def test_mock_clients_are_left_alone(monkeypatch):
    client = MagicMock()
    client.update = AsyncMock()
    client.close_session = AsyncMock()
    client.async_disconnect_ws = AsyncMock()
    monkeypatch.setattr(module, "ProtectApiClient", MagicMock(return_value=client))
    cm = module.ProtectConnectionManager(host=HOST, username="u", password="p", verify_ssl=False)

    assert await cm.initialize()
    assert cm.client is client
    await cm.close()


def test_hint_is_added_once():
    error = NotAuthorized("Request failed: /x - Status: 403 - Reason: Forbidden")
    module._hint_forbidden(error)
    module._hint_forbidden(error)
    assert str(error).count(HINT) == 1
    assert isinstance(error, NotAuthorized)
