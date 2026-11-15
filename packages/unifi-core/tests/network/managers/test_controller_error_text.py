"""Network request errors must not carry the controller's address.

aiounifi quotes the full request URL in its errors ("Call <url> received 403
Forbidden"), and Network tools return ``str(e)`` to the MCP caller, so the
controller's scheme, host and port reached every caller. ``ConnectionManager``
rewrites the error in place: the origin goes, the path stays, and a 403 gains a
fixed hint so a missing role can be told apart from an outage.
"""

import logging
from unittest.mock import MagicMock

import pytest
from aiounifi.errors import (
    AiounifiException,
    BadGateway,
    Forbidden,
    LoginRequired,
    RequestError,
    ResponseError,
)
from aiounifi.models.api import ApiRequest
from unifi_core.network.managers.connection_manager import (
    ConnectionManager,
    controller_error_code,
    response_status,
)
from unifi_core.redaction import strip_url_origins

HOST = "controller-host-sentinel.example"
ORIGINS = (f"https://{HOST}:443", f"https://{HOST}", f"http://{HOST}:8080", f"HTTPS://{HOST.upper()}:8443")
MAC = "aa:bb:cc:dd:ee:ff"
PASSWORD = "SENTINEL-login-secret-5d0e"
SUBMITTED = "SENTINEL-submitted-secret-a1c4"
HINT = "The Network account lacks permission for this operation"


class _Session:
    closed = False

    async def close(self):
        return None


def _manager(raise_for, host=HOST) -> ConnectionManager:
    manager = ConnectionManager(host, "admin", PASSWORD)
    controller = MagicMock()
    controller.connectivity.config.session = _Session()
    controller.connectivity.is_unifi_os = True

    async def _request(api_request):
        raise raise_for(api_request)

    controller.request = _request
    manager.controller = controller
    manager._aiohttp_session = controller.connectivity.config.session
    manager._initialized = True
    manager._auth_generation = 1
    return manager


def _assert_no_origin(text: str) -> None:
    assert HOST not in text.lower()
    assert "://" not in text
    assert ":443" not in text and ":8443" not in text and ":8080" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ORIGINS)
async def test_forbidden_drops_the_origin_keeps_the_path_and_explains_the_403(origin, caplog):
    path = "/proxy/network/api/s/default/cmd/backup"
    manager = _manager(lambda _req: Forbidden(f"Call {origin}{path} received 403 Forbidden"))

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(Forbidden) as excinfo:
            await manager.request(ApiRequest(method="post", path="/cmd/backup", data={"cmd": "list-backups"}))

    text = str(excinfo.value)
    assert text.startswith(f"Call {path} received 403 Forbidden. ")
    assert HINT in text and "Full Admin" in text
    _assert_no_origin(text)
    _assert_no_origin(caplog.text)


@pytest.mark.asyncio
async def test_hint_is_added_once_and_the_class_still_classifies():
    error = Forbidden(f"Call https://{HOST}/api/s/default/stat/x received 403 Forbidden")
    manager = _manager(lambda _req: error)

    with pytest.raises(Forbidden):
        await manager.request(ApiRequest(method="get", path="/stat/x"))
    manager._scrub_error(error)

    assert str(error).count(HINT) == 1
    assert isinstance(error, Forbidden)
    assert manager._is_terminal_auth_error(error)


@pytest.mark.asyncio
async def test_a_404_keeps_its_status_and_gets_no_hint():
    manager = _manager(
        lambda _req: ResponseError(f"Call https://{HOST}:443/api/s/default/stat/x received 404 Not Found")
    )

    with pytest.raises(ResponseError) as excinfo:
        await manager.request(ApiRequest(method="get", path="/stat/x"))

    assert str(excinfo.value) == "Call /api/s/default/stat/x received 404 Not Found"
    assert response_status(excinfo.value) == 404
    assert HINT not in str(excinfo.value)


@pytest.mark.asyncio
async def test_a_429_reads_as_429_after_the_rewrite():
    manager = _manager(lambda _req: ResponseError(f"Call https://{HOST}:443/api/s/default/stat/x received 429: b''"))

    with pytest.raises(ResponseError) as excinfo:
        await manager.request(ApiRequest(method="get", path="/stat/x"))

    assert response_status(excinfo.value) == 429
    _assert_no_origin(str(excinfo.value))


@pytest.mark.asyncio
async def test_transport_error_drops_the_url_and_the_bare_host():
    message = (
        f"Error requesting data from https://{HOST}:443/proxy/network/api/s/default/stat/x: "
        f"Cannot connect to host {HOST}:443 ssl:default [Connect call failed ('{HOST}', 443)]"
    )
    manager = _manager(lambda _req: RequestError(message))

    with pytest.raises(RequestError) as excinfo:
        await manager.request(ApiRequest(method="get", path="/stat/x"))

    text = str(excinfo.value)
    assert text.startswith("Error requesting data from /proxy/network/api/s/default/stat/x: ")
    assert HOST not in text
    # Still recognised as a transport failure after the rewrite.
    assert manager._is_unreachable_error(excinfo.value)


@pytest.mark.asyncio
async def test_cause_chain_is_rewritten():
    def _chained(_req):
        cause = RequestError(f"Error requesting data from https://{HOST}:8443/api/self: timeout")
        try:
            raise cause
        except RequestError as inner:
            try:
                raise RuntimeError(f"wrapped call to https://{HOST}:8443/api/s/default/stat/x") from inner
            except RuntimeError as outer:
                return outer

    manager = _manager(_chained)

    with pytest.raises(RuntimeError) as excinfo:
        await manager.request(ApiRequest(method="get", path="/stat/x"))

    assert str(excinfo.value) == "wrapped call to /api/s/default/stat/x"
    assert str(excinfo.value.__cause__) == "Error requesting data from /api/self: timeout"


@pytest.mark.asyncio
async def test_credentials_and_macs_are_still_masked():
    def _raiser(api_request):
        return ResponseError(
            f"Call https://admin:{PASSWORD}@{HOST}/api/s/default/rest/user/{MAC} received 400: "
            f'b\'{{"x_password": "{SUBMITTED}", "mac": "{MAC}"}}\''
        )

    manager = _manager(_raiser)

    with pytest.raises(ResponseError) as excinfo:
        await manager.request(
            ApiRequest(method="put", path=f"/rest/user/{MAC}", data={"name": "x", "x_password": SUBMITTED})
        )

    text = str(excinfo.value)
    assert PASSWORD not in text and SUBMITTED not in text and MAC not in text
    _assert_no_origin(text)
    assert text.startswith("Call /api/s/default/rest/user/")
    assert response_status(excinfo.value) == 400


@pytest.mark.asyncio
async def test_a_submitted_url_is_masked_whole_not_left_as_a_bare_path():
    secret_url = "https://hooks.example/SENTINEL-webhook-token-77b2"

    def _raiser(_req):
        return ResponseError(
            f'Call https://{HOST}/api/s/default/rest/x received 400: b\'{{"x_secret": "{secret_url}"}}\''
        )

    manager = _manager(_raiser)

    with pytest.raises(ResponseError) as excinfo:
        await manager.request(ApiRequest(method="put", path="/rest/x", data={"x_secret": secret_url}))

    assert "SENTINEL-webhook-token-77b2" not in str(excinfo.value)
    _assert_no_origin(str(excinfo.value))


@pytest.mark.asyncio
async def test_controller_error_code_still_classifies_after_the_rewrite():
    error = AiounifiException({"meta": {"rc": "error", "msg": "api.err.UnknownUser"}, "data": []})
    manager = _manager(lambda _req: error)

    with pytest.raises(AiounifiException):
        await manager.request(ApiRequest(method="get", path="/stat/user/x"))

    assert controller_error_code(error) == "api.err.UnknownUser"


@pytest.mark.asyncio
async def test_forbidden_after_reauthentication_is_rewritten_too():
    calls = []

    def _raiser(_req):
        calls.append(1)
        if len(calls) == 1:
            return LoginRequired(f"Call https://{HOST}/api/s/default/stat/x received 401 Unauthorized")
        return Forbidden(f"Call https://{HOST}/api/s/default/stat/x received 403 Forbidden")

    manager = _manager(_raiser)

    async def _reauthenticate(_generation):
        return True

    manager._reauthenticate = _reauthenticate

    with pytest.raises(Forbidden) as excinfo:
        await manager.request(ApiRequest(method="get", path="/stat/x"))

    assert HINT in str(excinfo.value)
    _assert_no_origin(str(excinfo.value))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            Forbidden(
                f"Call https://{HOST}:443/proxy/network/api/s/default/get/setting/super_mgmt received 403 Forbidden"
            ),
            "Controller settings request failed (Forbidden, HTTP 403). The Network account lacks permission",
        ),
        (
            BadGateway(f"Call https://{HOST}:443/api/s/default/get/setting/super_mgmt received 502 bad gateway"),
            "Controller settings request failed (BadGateway, HTTP 502).",
        ),
        (
            ResponseError(f"Call https://{HOST}:443/api/s/default/get/setting/super_mgmt received 404 Not Found"),
            "Controller settings request failed (ResponseError, HTTP 404).",
        ),
        (RuntimeError(f"opaque https://{HOST} failure"), "Controller settings request failed (RuntimeError)."),
    ],
    ids=["403", "502", "404", "no_status"],
)
async def test_settings_failure_keeps_the_status_and_hint_but_no_controller_text(error, expected):
    manager = _manager(lambda _req: error)

    with pytest.raises(RequestError) as excinfo:
        await manager.request(ApiRequest(method="get", path="/get/setting/super_mgmt"))

    text = str(excinfo.value)
    assert text.startswith(expected)
    assert ("Full Admin" in text) == (type(error) is Forbidden)
    assert "super_mgmt" not in text and "/api/" not in text
    _assert_no_origin(text)
    assert excinfo.value.__cause__ is None and excinfo.value.__suppress_context__


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Call https://10.0.0.1:443/a/b received 403", "Call /a/b received 403"),
        ("Call https://10.0.0.1 received 403", "Call <controller> received 403"),
        ("see https://[fe80::1]:8443/x?y=1", "see /x?y=1"),
        ("wss://10.0.0.1:443/wss/s/default/events closed", "/wss/s/default/events closed"),
        ("host 10.0.0.1:443 and 10.0.0.10 and 10.0.0.1.", "host <controller>:443 and 10.0.0.10 and <controller>."),
        ("no address here", "no address here"),
    ],
)
def test_strip_url_origins(text, expected):
    assert strip_url_origins(text, ["https://10.0.0.1:443"]) == expected
