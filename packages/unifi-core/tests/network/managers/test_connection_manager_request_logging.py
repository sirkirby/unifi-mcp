"""``ConnectionManager.request`` failure logging.

Two rules meet here. Operators need permission denials, login lockouts and
transport failures at ERROR with diagnostics. The privacy rule for the Network
client and device paths says a MAC address never reaches a log line, and
``/stat/user/<mac>`` puts the address in the request path itself.
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.errors import (
    AiounifiException,
    AuthenticationRateLimitError,
    Forbidden,
    LoginRequired,
    NoPermission,
    RequestError,
    ResponseError,
    Unauthorized,
)
from aiounifi.models.api import ApiRequest
from unifi_core.network.managers.connection_manager import ConnectionManager

MAC = "aa:bb:cc:dd:ee:ff"


class _Session:
    closed = False

    async def close(self):
        return None


def _manager(error: BaseException) -> ConnectionManager:
    manager = ConnectionManager("192.168.1.1", "admin", "secret")
    controller = MagicMock()
    controller.connectivity.config.session = _Session()

    async def _request(_req):
        raise error

    controller.request = _request
    manager.controller = controller
    manager._aiohttp_session = controller.connectivity.config.session
    manager._initialized = True
    return manager


def _unknown_user() -> AiounifiException:
    return AiounifiException({"meta": {"rc": "error", "mac": MAC, "msg": "api.err.UnknownUser"}, "data": []})


@pytest.fixture
def diagnostics_on(monkeypatch):
    monkeypatch.setattr("unifi_core.diagnostics.diagnostics_enabled", lambda: True)
    log_api_request = MagicMock()
    monkeypatch.setattr("unifi_core.diagnostics.log_api_request", log_api_request)
    return log_api_request


@pytest.mark.asyncio
async def test_controller_reported_error_logs_the_code_only(caplog, diagnostics_on):
    """A controller ``api.err.*`` answer is a normal negative reply, not an
    operator event: no ERROR, no traceback, and the body (which echoes the
    requested MAC) never reaches the log. The error code alone is logged."""
    manager = _manager(_unknown_user())

    with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
        with pytest.raises(AiounifiException):
            await manager.request(ApiRequest(method="get", path=f"/stat/user/{MAC}"))

    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert all(r.exc_info is None for r in caplog.records)
    assert MAC not in caplog.text and "aabbccddeeff" not in caplog.text
    assert "api.err.UnknownUser" in caplog.text
    assert "'data'" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [Forbidden, NoPermission, AuthenticationRateLimitError, Unauthorized])
async def test_other_aiounifi_errors_keep_error_logging_and_diagnostics(caplog, diagnostics_on, error_type):
    manager = _manager(error_type("denied"))

    with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
        with pytest.raises(error_type):
            await manager.request(ApiRequest(method="put", path="/rest/firewallpolicy/abc"))

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors
    assert "Traceback (most recent call last)" in caplog.text
    diagnostics_on.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        RequestError("timeout"),
        RuntimeError("boom"),
        ResponseError(f"Call https://c/proxy/network/api/s/default/stat/user/{MAC} received 429: b''"),
        RequestError(f"Error requesting data from https://c/api/s/default/stat/user/{MAC}: Cannot connect to host"),
        Forbidden(f"Call https://c/proxy/network/api/s/default/stat/user/{MAC} received 403 Forbidden"),
        AiounifiException({"meta": {"rc": "error", "msg": f"bad station {MAC}"}, "data": []}),
    ],
)
async def test_failed_request_never_logs_a_mac_bearing_path(caplog, error):
    """Transport and unexpected failures stay at ERROR, with the address
    masked in the path and in the exception message (aiounifi quotes the URL)."""
    manager = _manager(error)

    with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
        with pytest.raises(type(error)):
            await manager.request(ApiRequest(method="get", path=f"/stat/user/{MAC}"))

    assert [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert MAC not in caplog.text and "aabbccddeeff" not in caplog.text
    assert "/stat/user/[redacted]" in caplog.text


@pytest.mark.asyncio
async def test_a_404_answer_on_a_read_is_not_an_operator_event(caplog):
    """A controller that does not serve a path answers 404; the caller decides
    what that means, so the log line is INFO, masked, without a traceback."""
    url = f"https://c/proxy/network/api/s/default/stat/user/{MAC}"
    manager = _manager(ResponseError(f"Call {url} received 404 Not Found"))

    with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
        with pytest.raises(ResponseError):
            await manager.request(ApiRequest(method="get", path=f"/stat/user/{MAC}"))

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert "Controller answered 404" in caplog.text
    assert MAC not in caplog.text and "/stat/user/[redacted]" in caplog.text


@pytest.mark.asyncio
async def test_failure_logs_mask_the_configured_credentials(caplog):
    """The same sanitizer that guards the stored connection error guards the
    request failure lines: a credential echoed by the library never lands."""
    manager = _manager(RequestError("Error requesting data: login for admin with secret rejected"))

    with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
        with pytest.raises(RequestError):
            await manager.request(ApiRequest(method="get", path="/stat/sta"))

    assert "secret" not in caplog.text
    assert "<redacted>" in caplog.text


@pytest.mark.asyncio
async def test_rejected_write_logs_the_code_at_warning(caplog):
    """A controller api.err.* on a write is not a routine negative reply."""
    manager = _manager(AiounifiException({"meta": {"rc": "error", "msg": "api.err.InvalidPayload"}, "data": []}))

    with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
        with pytest.raises(AiounifiException):
            await manager.request(ApiRequest(method="post", path="/cmd/stamgr", data={"cmd": "block-sta"}))

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings and "api.err.InvalidPayload" in warnings[0].getMessage()
    assert all(r.exc_info is None for r in caplog.records)


@pytest.mark.parametrize(
    "exc,expected",
    [
        (AiounifiException({"meta": {"rc": "error", "msg": "api.err.UnknownUser"}, "data": []}), "api.err.UnknownUser"),
        (AiounifiException("plain text"), None),
        (AiounifiException(), None),
        (AiounifiException({"data": []}), None),
        (AiounifiException({"meta": {"rc": "error"}}), None),
        (AiounifiException({"meta": {"msg": 5}}), None),
        (AiounifiException({"meta": {"rc": "error", "msg": f"bad station {MAC}"}}), None),
        (Forbidden({"meta": {"rc": "error", "msg": "api.err.X"}}), None),
        (NoPermission({"meta": {"rc": "error", "msg": "api.err.NoPermission"}}), None),
    ],
)
def test_controller_error_code_only_reads_api_err_codes_from_bare_exceptions(exc, expected):
    from unifi_core.network.managers.connection_manager import controller_error_code

    assert controller_error_code(exc) == expected


@pytest.mark.asyncio
async def test_terminal_login_failure_never_stores_or_logs_a_mac(caplog):
    """A 401 after re-authentication is recorded for the reconnect cool-down and
    served to later callers; aiounifi's message quotes the URL."""
    url = f"https://c/proxy/network/api/s/default/stat/user/{MAC}"
    manager = _manager(LoginRequired(f"Call {url} received 401 Unauthorized"))
    manager._reauthenticate = AsyncMock(return_value=True)

    with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
        with pytest.raises(LoginRequired):
            await manager.request(ApiRequest(method="get", path=f"/stat/user/{MAC}"))

    assert MAC not in caplog.text and "aabbccddeeff" not in caplog.text
    assert MAC not in (manager._last_connection_error or "")
    assert MAC not in str(manager._not_connected_error())
