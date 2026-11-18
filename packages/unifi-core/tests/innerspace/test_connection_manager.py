"""The InnerSpace console session client: login, re-login, error text, logs and transport rules."""

import asyncio
import json
import logging
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from unifi_core.exceptions import (
    UniFiMalformedResponseError,
    UniFiNotFoundError,
    UniFiPermissionError,
    UniFiRateLimitError,
    UniFiValidationError,
)
from unifi_core.innerspace.managers import connection_manager as cm_module
from unifi_core.innerspace.managers.connection_manager import (
    INTEGRATION_PREFIX,
    InnerSpaceConnectionManager,
    InnerSpaceHttpError,
    InnerSpaceUnavailableError,
    reconnects_on_demand,
)
from unifi_core.redaction import is_sensitive_key
from unifi_test_guard import blocked_network_access

from tests.innerspace.conftest import ACCESS_DENIED, HOST, LOGIN, LOGOUT, PASSWORD, USERNAME, start_stub
from tests.secret_assertions import ESCAPED_SECRET, assert_unrecoverable

FIXTURES = Path(__file__).parent / "fixtures"
FLOOR_PLANS = f"{INTEGRATION_PREFIX}/floor_plans"
SYSTEM = "/api/system"
OP = "List floor plans"
MARKER = "body-marker-7f3e"
PERMISSION_TEXT = (
    f"{OP}: the console refused the session for InnerSpace (expired session or an account without InnerSpace access)"
)


def _errors() -> dict:
    return json.loads((FIXTURES / "errors.json").read_text())


def _system() -> dict:
    return json.loads((FIXTURES / "system.json").read_text())


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@reconnects_on_demand
class _Reader:
    def __init__(self, cm: InnerSpaceConnectionManager) -> None:
        self._cm = cm

    async def floor_plans(self):
        return await self._cm.request("GET", FLOOR_PLANS, operation=OP)


def _texts(error: BaseException) -> list[str]:
    return [str(error), str(error.__cause__), str(error.__context__)]


# ---------------------------------------------------------------------------
# Login and session headers
# ---------------------------------------------------------------------------


async def test_login_sends_credentials_once_and_stores_csrf(manager, console):
    assert await manager.initialize() is True

    (login,) = console.calls("POST", LOGIN)
    assert login.body == {"username": USERNAME, "password": PASSWORD}
    assert "X-CSRF-Token" not in login.headers and "Cookie" not in login.headers
    assert console.logins == 1
    assert manager._auth.csrf == "csrf-1"
    assert manager.is_connected


async def test_bad_credentials_fixed_error_no_retry(console, caplog):
    console.reject_logins()
    manager = InnerSpaceConnectionManager(HOST, USERNAME, ESCAPED_SECRET, base_url=console.base_url)
    try:
        with caplog.at_level(logging.DEBUG):
            assert await manager.initialize() is False
            with pytest.raises(InnerSpaceUnavailableError) as raised:
                await manager.request("GET", FLOOR_PLANS, operation=OP)
    finally:
        await manager.close()

    assert console.logins == 1
    assert "rejected" in manager.last_connection_error
    # Positive control: the password reached the console, which echoed it back.
    assert console.calls("POST", LOGIN)[0].body["password"] == ESCAPED_SECRET
    for text in [*_texts(raised.value), caplog.text, manager.last_connection_error]:
        assert_unrecoverable(text, ESCAPED_SECRET)
        assert "TOKEN" not in text


async def test_requests_carry_cookie_and_csrf(connected, console):
    console.reply("GET", FLOOR_PLANS, {"data": []})

    assert await connected.request("GET", FLOOR_PLANS, operation=OP, params={"siteId": "s1"}) == {"data": []}

    (sent,) = console.calls("GET", FLOOR_PLANS)
    assert sent.headers["Cookie"] == "TOKEN=session-1"
    assert sent.headers["X-CSRF-Token"] == "csrf-1"
    assert sent.query == [("siteId", "s1")]


# ---------------------------------------------------------------------------
# Session expiry, concurrency and the auth cool-down
# ---------------------------------------------------------------------------


async def test_concurrent_401_triggers_one_login(connected, console):
    console.expire_session(401)
    console.hold_401_until(5)
    for index in range(5):
        console.reply("GET", FLOOR_PLANS, {"data": [index]})

    results = await asyncio.gather(*(connected.request("GET", FLOOR_PLANS, operation=OP) for _ in range(5)))

    assert console.held == 5
    assert console.logins == 2
    assert len(results) == 5
    calls = console.calls("GET", FLOOR_PLANS)
    first, retries = calls[:5], calls[5:]
    assert all(call.headers["Cookie"] == "TOKEN=session-1" for call in first)
    assert len(retries) == 5
    assert all(call.headers["Cookie"] == "TOKEN=session-2" for call in retries)
    assert all(call.headers["X-CSRF-Token"] == "csrf-2" for call in retries)


async def test_csrf_already_rotated_skips_login(connected, console):
    stale = connected._auth

    await connected._relogin(stale, OP)
    assert console.logins == 2
    await connected._relogin(stale, OP)

    assert console.logins == 2
    assert connected._auth.csrf == "csrf-2"


async def test_second_401_not_retried(connected, console):
    console.reply("GET", FLOOR_PLANS, status=401)
    console.reply("GET", FLOOR_PLANS, status=401)

    with pytest.raises(InnerSpaceUnavailableError):
        await connected.request("GET", FLOOR_PLANS, operation=OP)

    assert len(console.calls("GET", FLOOR_PLANS)) == 2
    assert console.logins == 2
    assert not connected.is_connected
    assert connected._reconnect_block_remaining() > 0


async def test_concurrent_rejected_relogin(connected, console):
    console.expire_session(401)
    console.hold_401_until(5)
    console.reject_logins()

    results = await asyncio.gather(
        *(connected.request("GET", FLOOR_PLANS, operation=OP) for _ in range(5)), return_exceptions=True
    )

    assert console.logins == 2
    assert all(isinstance(result, InnerSpaceUnavailableError) for result in results)
    assert len({str(result) for result in results}) == 1
    assert connected._reconnect_block_remaining() > 0
    assert len(console.calls("GET", FLOOR_PLANS)) == 5


async def test_reconnect_block_doubles(manager, console):
    clock = _Clock()
    manager._clock = clock
    console.reject_logins()

    assert await manager.initialize() is False
    assert manager._reconnect_block_until - clock.now == 60

    with pytest.raises(InnerSpaceUnavailableError):
        await _Reader(manager).floor_plans()
    assert await manager.reconnect() is False
    assert console.logins == 1

    clock.now += 61
    assert manager.reconnect_due
    assert await manager.reconnect() is False
    assert console.logins == 2
    assert manager._reconnect_block_until - clock.now == 120


async def test_reconnects_on_demand_after_failed_start(manager, console):
    clock = _Clock()
    manager._clock = clock
    console.reply("POST", LOGIN, status=503)
    assert await manager.initialize() is False
    assert manager._reconnect_block_remaining() == 0

    console.reply("GET", FLOOR_PLANS, {"data": ["plan"]})
    clock.now += 31
    assert await _Reader(manager).floor_plans() == {"data": ["plan"]}
    assert console.logins == 2


async def test_reconnect_callbacks_run_after_reconnect(manager, console):
    clock = _Clock()
    manager._clock = clock
    ran = []

    async def callback():
        ran.append(True)

    manager.add_reconnect_callback(callback)
    console.reply("POST", LOGIN, status=503)
    assert await manager.initialize() is False
    clock.now += 31

    assert await manager.reconnect() is True
    assert ran == [True]


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------


async def test_403_access_code_relogs_in_once(connected, console):
    console.expire_session(403)
    console.reply("GET", FLOOR_PLANS, {"data": []})

    assert await connected.request("GET", FLOOR_PLANS, operation=OP) == {"data": []}

    assert console.logins == 2
    calls = console.calls("GET", FLOOR_PLANS)
    assert [call.headers["Cookie"] for call in calls] == ["TOKEN=session-1", "TOKEN=session-2"]


async def test_403_after_relogin_is_permission_error(connected, console):
    console.reply("GET", FLOOR_PLANS, ACCESS_DENIED, status=403)
    console.reply("GET", FLOOR_PLANS, ACCESS_DENIED, status=403)

    with pytest.raises(UniFiPermissionError) as raised:
        await connected.request("GET", FLOOR_PLANS, operation=OP)

    assert str(raised.value).startswith(PERMISSION_TEXT)
    assert "Super Admin" in str(raised.value)
    assert console.logins == 2
    assert len(console.calls("GET", FLOOR_PLANS)) == 2
    assert connected.is_connected


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"error": {"code": "errors.api.other"}}, "errors.api.other"),
        (_errors()["logout_forbidden"]["body"], None),
        ({"error": {"code": "errors.api.access; DROP <script>"}}, None),
    ],
    ids=["other-code", "numeric-code", "code-outside-allowlist"],
)
async def test_403_other_code_is_http_error(connected, console, payload, code):
    console.reply("GET", FLOOR_PLANS, payload, status=403)

    with pytest.raises(InnerSpaceHttpError) as raised:
        await connected.request("GET", FLOOR_PLANS, operation=OP)

    assert (raised.value.status, raised.value.code) == (403, code)
    assert console.logins == 1
    assert "DROP" not in str(raised.value)


async def test_404_not_found(connected, console):
    error = _errors()["not_found"]
    console.reply("GET", FLOOR_PLANS, error["body"], status=error["status"])

    with pytest.raises(UniFiNotFoundError) as raised:
        await connected.request("GET", FLOOR_PLANS, operation=OP)

    assert str(raised.value) == f"{OP}: InnerSpace route not found"


async def test_429_rate_limit(connected, console):
    console.reply("GET", FLOOR_PLANS, status=429, headers={"Retry-After": "5"})

    with pytest.raises(UniFiRateLimitError, match=OP):
        await connected.request("GET", FLOOR_PLANS, operation=OP)

    assert len(console.calls("GET", FLOOR_PLANS)) == 1


async def test_non_json_200_malformed(connected, console):
    console.reply("GET", FLOOR_PLANS, body_bytes=f"<html>{MARKER}</html>".encode())

    with pytest.raises(UniFiMalformedResponseError) as raised:
        await connected.request("GET", FLOOR_PLANS, operation=OP)

    assert MARKER not in str(raised.value)


async def test_other_status_is_http_error_with_allowlisted_code(connected, console):
    console.reply("GET", FLOOR_PLANS, {"error": {"code": "errors.server.busy", "message": MARKER}}, status=503)

    with pytest.raises(InnerSpaceHttpError) as raised:
        await connected.request("GET", FLOOR_PLANS, operation=OP)

    assert (raised.value.status, raised.value.code) == (503, "errors.server.busy")
    assert MARKER not in str(raised.value)


async def test_redirect_refused(connected, console):
    elsewhere, server = await start_stub()
    try:
        console.redirect(FLOOR_PLANS, f"{elsewhere.base_url}/capture")
        with pytest.raises(InnerSpaceHttpError, match="redirect") as raised:
            await connected.request("GET", FLOOR_PLANS, operation=OP)
    finally:
        await server.close()

    assert raised.value.status == 302
    assert len(console.calls("GET", FLOOR_PLANS)) == 1
    assert elsewhere.requests == []


async def test_login_redirect_refused(manager, console):
    elsewhere, server = await start_stub()
    try:
        console.redirect(LOGIN, f"{elsewhere.base_url}{LOGIN}", method="POST")
        assert await manager.initialize() is False
    finally:
        await server.close()

    assert elsewhere.requests == []
    assert manager._reconnect_block_remaining() == 0


# ---------------------------------------------------------------------------
# Error text, logs and paths
# ---------------------------------------------------------------------------


async def _http_error_with_body(console, tmp_path, managers):
    manager = managers(console.base_url)
    await manager.initialize()
    console.reply("GET", FLOOR_PLANS, {"error": {"message": f"{MARKER} {HOST}"}}, status=500)
    await manager.request("GET", FLOOR_PLANS, operation=OP)


async def _connection_refused(console, tmp_path, managers):
    from fake_controller import closed_port

    manager = managers(f"http://127.0.0.1:{closed_port()}")
    assert await manager.initialize() is False
    assert manager.last_connection_error.startswith("Could not log in")
    await manager.request("GET", FLOOR_PLANS, operation=OP)


async def _tls_failure(console, tmp_path, managers):
    from fake_controller import tls_context

    server = TestServer(web.Application(), host="127.0.0.1")
    await server.start_server(ssl=tls_context(tmp_path))
    try:
        manager = managers(f"https://127.0.0.1:{server.port}", verify_ssl=True)
        assert await manager.initialize() is False
        assert "certificate failed verification" in manager.last_connection_error
        await manager.request("GET", FLOOR_PLANS, operation=OP)
    finally:
        await server.close()


async def _redirect(console, tmp_path, managers):
    manager = managers(console.base_url)
    await manager.initialize()
    console.redirect(FLOOR_PLANS, f"https://{HOST}/{MARKER}")
    await manager.request("GET", FLOOR_PLANS, operation=OP)


@pytest.mark.parametrize(
    "scenario",
    [_http_error_with_body, _connection_refused, _tls_failure, _redirect],
    ids=["http-error", "connection-refused", "tls-failure", "redirect"],
)
async def test_error_text_has_no_body_or_host(console, scenario, caplog, tmp_path):
    built: list[InnerSpaceConnectionManager] = []

    def managers(base_url, **kwargs):
        built.append(InnerSpaceConnectionManager(HOST, USERNAME, PASSWORD, base_url=base_url, **kwargs))
        return built[-1]

    try:
        with caplog.at_level(logging.DEBUG), pytest.raises(Exception) as raised:
            await scenario(console, tmp_path, managers)
    finally:
        for manager in built:
            await manager.close()

    (manager,) = built
    if scenario is _http_error_with_body:
        # Positive control: the stub's body carried the marker the error must not repeat.
        assert isinstance(raised.value, InnerSpaceHttpError) and raised.value.status == 500
    address = f"127.0.0.1:{manager._origin.port}"
    texts = [*_texts(raised.value), caplog.text, manager.last_connection_error or ""]
    for text in texts:
        assert MARKER not in text
        assert HOST not in text
        assert address not in text
    assert raised.value.__cause__ is None and raised.value.__context__ is None


async def test_logs_use_route_template(connected, console, caplog):
    console.reply("GET", FLOOR_PLANS, {"data": []})
    unknown = f"/proxy/innerspace/integration/v1/{MARKER}"
    console.reply("GET", unknown, status=500)
    with caplog.at_level(logging.DEBUG, logger=cm_module.__name__):
        await connected.request("GET", FLOOR_PLANS, operation=OP, params={"siteId": MARKER})
        with pytest.raises(InnerSpaceHttpError):
            await connected.request("GET", unknown, operation=OP)

    assert f"{INTEGRATION_PREFIX}/floor_plans" in caplog.text
    assert "/{unknown}" in caplog.text
    assert MARKER not in caplog.text
    assert HOST not in caplog.text and console.base_url not in caplog.text


@pytest.mark.parametrize(
    ("path", "template"),
    [
        (LOGIN, LOGIN),
        (LOGOUT, LOGOUT),
        (SYSTEM, SYSTEM),
        ("/proxy/innerspace/api/project", "/proxy/innerspace/api/project"),
        (f"{INTEGRATION_PREFIX}/project?mode=3D", f"{INTEGRATION_PREFIX}/project"),
        (f"{INTEGRATION_PREFIX}/floor_plans", f"{INTEGRATION_PREFIX}/floor_plans"),
        (f"{INTEGRATION_PREFIX}/access_points", f"{INTEGRATION_PREFIX}/access_points"),
        (f"{INTEGRATION_PREFIX}/switches", f"{INTEGRATION_PREFIX}/switches"),
        (f"{INTEGRATION_PREFIX}/inventory", f"{INTEGRATION_PREFIX}/inventory"),
        (f"{INTEGRATION_PREFIX}/assets/p-1/plan.png", f"{INTEGRATION_PREFIX}/assets/{{folder}}/{{file}}"),
        (f"{INTEGRATION_PREFIX}/assets/p-1/a/b.png", "/{unknown}"),
        ("/proxy/network/api/self", "/{unknown}"),
    ],
)
def test_log_route_templates(path, template):
    assert cm_module._log_route(path) == template


@pytest.mark.parametrize(
    "path",
    [
        f"{INTEGRATION_PREFIX}/../../api/users",
        f"{INTEGRATION_PREFIX}/%2e%2e/api/users",
        "//x/api/system",
        "@x/api/system",
        f"{INTEGRATION_PREFIX}\\floor_plans",
        "https://example.invalid/api/system",
        "api/system",
        f"{FLOOR_PLANS}?siteId=x",
        f"{FLOOR_PLANS}#x",
        "",
    ],
)
async def test_rejects_unsafe_path(connected, console, path):
    before = len(console.requests)

    with pytest.raises(UniFiValidationError) as raised:
        await connected.request("GET", path, operation=OP)

    assert len(console.requests) == before
    assert "example.invalid" not in str(raised.value)


# ---------------------------------------------------------------------------
# App status
# ---------------------------------------------------------------------------


async def test_ensure_app_running_caches_running_result(connected, console):
    clock = _Clock()
    connected._clock = clock
    console.reply("GET", SYSTEM, _system())
    console.reply("GET", SYSTEM, _system())

    await connected.ensure_app_running(OP)
    await connected.ensure_app_running(OP)
    assert len(console.calls("GET", SYSTEM)) == 1

    clock.now += 31
    await connected.ensure_app_running(OP)
    assert len(console.calls("GET", SYSTEM)) == 2


@pytest.mark.parametrize("state", ["stopped", "absent"])
async def test_ensure_app_running_refuses_stopped_app(connected, console, state):
    system = _system()
    controllers = system["apps"]["controllers"]
    if state == "stopped":
        controllers[0]["isRunning"] = False
    else:
        del controllers[0]
    console.reply("GET", SYSTEM, system)
    console.reply("GET", SYSTEM, system)

    for _ in range(2):
        with pytest.raises(InnerSpaceUnavailableError) as raised:
            await connected.ensure_app_running(OP)
        assert str(raised.value) == f"{OP}: InnerSpace is not running on this console"
    # A stopped result is never cached.
    assert len(console.calls("GET", SYSTEM)) == 2


# ---------------------------------------------------------------------------
# Auth failure hint: appended to a credential failure only
# ---------------------------------------------------------------------------

HINT = "synthetic-hint: set the server's own password variable."


def _hinted(base_url, **kwargs):
    return InnerSpaceConnectionManager(HOST, USERNAME, PASSWORD, base_url=base_url, auth_failure_hint=HINT, **kwargs)


def _has_hint_once(text):
    return text.count(HINT) == 1 and text.endswith(HINT)


async def test_hint_on_not_configured():
    manager = InnerSpaceConnectionManager("", USERNAME, PASSWORD, auth_failure_hint=HINT)
    try:
        assert await manager.initialize() is False
    finally:
        await manager.close()

    assert manager.last_connection_error == f"{cm_module._NOT_CONFIGURED} {HINT}"


@pytest.mark.parametrize("status", [401, 403])
async def test_hint_on_a_rejected_login(console, status):
    console.reply("POST", LOGIN, ACCESS_DENIED, status=status)
    manager = _hinted(console.base_url)
    try:
        assert await manager.initialize() is False
        with pytest.raises(InnerSpaceUnavailableError) as raised:
            await manager.request("GET", FLOOR_PLANS, operation=OP)
    finally:
        await manager.close()

    assert manager.last_connection_error == f"{cm_module._REJECTED} {HINT}"
    assert str(raised.value).count(HINT) == 1
    assert USERNAME not in str(raised.value) and PASSWORD not in str(raised.value)


async def test_hint_on_a_rejected_relogin_after_an_expired_session(console):
    manager = _hinted(console.base_url)
    try:
        assert await manager.initialize() is True
        console.expire_session(401)
        console.reject_logins()
        with pytest.raises(InnerSpaceUnavailableError) as raised:
            await manager.request("GET", FLOOR_PLANS, operation=OP)
    finally:
        await manager.close()

    assert console.logins == 2
    assert _has_hint_once(manager.last_connection_error)
    assert str(raised.value).count(HINT) == 1


async def _session_rejected(console, manager):
    assert await manager.initialize() is True
    console.reply("GET", FLOOR_PLANS, status=401)
    console.reply("GET", FLOOR_PLANS, status=401)
    with pytest.raises(InnerSpaceUnavailableError):
        await manager.request("GET", FLOOR_PLANS, operation=OP)
    return cm_module._SESSION_REJECTED


async def _login_rate_limited(console, manager):
    console.reply("POST", LOGIN, status=429)
    assert await manager.initialize() is False
    return cm_module._RATE_LIMITED


async def _request_403(console, manager):
    assert await manager.initialize() is True
    console.reply("GET", FLOOR_PLANS, ACCESS_DENIED, status=403)
    console.reply("GET", FLOOR_PLANS, ACCESS_DENIED, status=403)
    with pytest.raises(UniFiPermissionError) as raised:
        await manager.request("GET", FLOOR_PLANS, operation=OP)
    assert HINT not in str(raised.value)
    return None


@pytest.mark.parametrize(
    "scenario",
    [_session_rejected, _login_rate_limited, _request_403],
    ids=["session-rejected", "login-429", "request-403"],
)
@pytest.mark.parametrize("hint", [True, False], ids=["hint", "no-hint"])
async def test_no_hint_on_other_failures(console, scenario, hint):
    manager = (
        _hinted(console.base_url)
        if hint
        else InnerSpaceConnectionManager(HOST, USERNAME, PASSWORD, base_url=console.base_url)
    )
    try:
        expected = await scenario(console, manager)
    finally:
        await manager.close()

    assert manager.last_connection_error == expected


async def test_no_hint_when_the_console_is_unreachable(tmp_path):
    from fake_controller import closed_port

    manager = _hinted(f"http://127.0.0.1:{closed_port()}")
    try:
        assert await manager.initialize() is False
    finally:
        await manager.close()

    assert manager.last_connection_error == cm_module._UNREACHABLE


async def test_no_hint_on_a_certificate_failure(tmp_path):
    from fake_controller import tls_context

    server = TestServer(web.Application(), host="127.0.0.1")
    await server.start_server(ssl=tls_context(tmp_path))
    manager = _hinted(f"https://127.0.0.1:{server.port}", verify_ssl=True)
    try:
        assert await manager.initialize() is False
    finally:
        await manager.close()
        await server.close()

    assert "certificate failed verification" in manager.last_connection_error
    assert HINT not in manager.last_connection_error


@pytest.mark.parametrize("status", [401, 403])
async def test_without_a_hint_a_rejected_login_text_is_unchanged(manager, console, status):
    console.reply("POST", LOGIN, ACCESS_DENIED, status=status)

    assert await manager.initialize() is False

    assert manager.last_connection_error == cm_module._REJECTED


async def test_the_hint_is_never_logged(console, caplog):
    console.reject_logins()
    manager = _hinted(console.base_url)
    try:
        with caplog.at_level(logging.DEBUG):
            assert await manager.initialize() is False
    finally:
        await manager.close()

    assert HINT in manager.last_connection_error
    assert HINT not in caplog.text


# ---------------------------------------------------------------------------
# Construction, status and shutdown
# ---------------------------------------------------------------------------


async def test_authentication_status_session_only(manager):
    before = manager.authentication_status
    assert (before.session_configured, before.api_key_configured) == (True, False)
    assert (before.session_available, before.api_key_available) == (False, None)

    await manager.initialize()

    assert manager.authentication_status.session_available is True
    assert manager.authentication_status.api_key_available is None
    assert not InnerSpaceConnectionManager(HOST, "", "").authentication_status.session_configured


@pytest.mark.parametrize(
    "base_url",
    [
        "http://192.0.2.5:8080",
        "http://console.example.invalid",
        "ftp://127.0.0.1:21",
        "http://user:pw@127.0.0.1:8080",
        "http://127.0.0.1:8080/prefix",
        "http://127.0.0.1:8080?x=1",
        "http://localhost.example.invalid:8080",
    ],
)
def test_base_url_http_non_loopback_refused(base_url):
    with pytest.raises(ValueError) as raised:
        InnerSpaceConnectionManager(HOST, USERNAME, PASSWORD, base_url=base_url)
    assert "192.0.2.5" not in str(raised.value) and "example.invalid" not in str(raised.value)


def test_base_url_https_and_loopback_accepted():
    for base_url in ("https://192.0.2.5:8443", "http://127.0.0.1:8080", "http://[::1]:8080", "http://localhost:80"):
        InnerSpaceConnectionManager(HOST, USERNAME, PASSWORD, base_url=base_url)
    default = InnerSpaceConnectionManager(HOST, USERNAME, PASSWORD, port=8443)
    assert str(default._origin) == f"https://{HOST}:8443"


async def test_host_without_base_url_is_blocked_by_guard():
    manager = InnerSpaceConnectionManager(HOST, USERNAME, PASSWORD)
    blocked = blocked_network_access()
    start = len(blocked)
    try:
        assert await manager.initialize() is False
    finally:
        await manager.close()
    attempted = blocked[start:]
    del blocked[start:]
    assert attempted == [f"{HOST}:443"]
    assert HOST not in manager.last_connection_error


async def test_empty_host_is_not_configured():
    manager = InnerSpaceConnectionManager("", USERNAME, PASSWORD)
    blocked = blocked_network_access()
    start = len(blocked)
    try:
        assert await manager.initialize() is False
        assert manager.last_connection_error == cm_module._NOT_CONFIGURED
        assert manager.authentication_status.session_configured is False
        assert manager.reconnect_due is False
        with pytest.raises(InnerSpaceUnavailableError) as raised:
            await manager.request("GET", FLOOR_PLANS, operation=OP)
    finally:
        await manager.close()
    assert blocked[start:] == []
    assert str(raised.value) == f"{OP}: {cm_module._NOT_CONFIGURED}"
    assert InnerSpaceConnectionManager("  ", USERNAME, PASSWORD).authentication_status.session_configured is False


async def test_session_ignores_proxy_environment(connected, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    assert connected._session.trust_env is False


async def test_close_idempotent_and_logs_out(connected, console):
    await connected.close()
    await connected.close()

    (logout,) = console.calls("POST", LOGOUT)
    assert logout.headers["X-CSRF-Token"] == "csrf-1"
    assert logout.headers["Cookie"] == "TOKEN=session-1"
    assert not connected.is_connected
    assert not connected.reconnect_due


async def test_close_without_session_sends_nothing(manager, console):
    await manager.close()
    assert console.requests == []


async def test_unverified_tls_warns(console, caplog):
    manager = InnerSpaceConnectionManager(
        HOST, USERNAME, PASSWORD, base_url=console.base_url, tls_env_prefix="INNERSPACE"
    )
    try:
        with caplog.at_level(logging.WARNING, logger=cm_module.__name__):
            await manager.initialize()
            await manager.close()
            await manager.initialize()
    finally:
        await manager.close()

    warnings = [record for record in caplog.records if "TLS verification is off" in record.getMessage()]
    assert len(warnings) == 1
    assert "UNIFI_INNERSPACE_SSL_FINGERPRINT" in warnings[0].getMessage()


def test_redaction_covers_session_keys():
    for key in ("TOKEN", "x-csrf-token", "csrfToken", "cookie", "set-cookie"):
        assert is_sensitive_key(key), key
