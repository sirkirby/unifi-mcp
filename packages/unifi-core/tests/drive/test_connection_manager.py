"""The UniFi Drive session client: login, CSRF handling, re-login and error text."""

import aiohttp
import pytest
from unifi_core.drive.managers import connection_manager as cm
from unifi_core.drive.managers.connection_manager import DriveConnectionManager, DriveWriteOutcomeUnknown
from unifi_core.exceptions import (
    UniFiAuthError,
    UniFiConnectionError,
    UniFiNotFoundError,
    UniFiOperationError,
    UniFiPermissionError,
    UniFiRateLimitError,
    UniFiValidationError,
)
from unifi_core.tls import CertificateVerificationError

from tests.drive.conftest import CSRF, HOST, PASSWORD, USERNAME
from tests.drive.fixtures import service

SMB = "/proxy/drive/api/v1/services/smb/settings"


async def test_logs_in_once_and_sends_the_csrf_token(connection, console):
    console.reply("GET", SMB, service(True), always=True)

    assert await connection.get(SMB) == {"enable": True}
    assert await connection.get(SMB) == {"enable": True}

    (login,) = console.calls("POST", "/api/auth/login")
    assert login.body == {"username": USERNAME, "password": PASSWORD, "rememberMe": False}
    reads = console.calls("GET", SMB)
    assert [r.headers.get("X-CSRF-Token") for r in reads] == [CSRF, CSRF]
    assert all("TOKEN=t" in r.headers.get("Cookie", "") for r in reads)


async def test_no_request_before_the_first_call(console):
    manager = DriveConnectionManager(HOST, USERNAME, PASSWORD, base_url=console.base_url)
    assert manager.configured and not manager.is_connected
    await manager.close()
    assert console.requests == []


async def test_updated_csrf_token_replaces_the_old_one(connection, console):
    console.reply("PUT", SMB, service(False), headers={"x-updated-csrf-token": "csrf-2"})
    console.reply("GET", SMB, service(False))

    await connection.put(SMB, {"enable": False})
    await connection.get(SMB)

    assert console.calls("GET", SMB)[0].headers["X-CSRF-Token"] == "csrf-2"


async def test_expired_session_logs_in_again_once(connection, console):
    console.reply("GET", SMB, service(True))
    await connection.get(SMB)
    console.reply("GET", SMB, status=401)
    console.reply("POST", "/api/auth/login", {}, headers={"x-csrf-token": "csrf-fresh"})
    console.reply("GET", SMB, service(True))

    assert await connection.get(SMB) == {"enable": True}

    assert len(console.calls("POST", "/api/auth/login")) == 2
    assert console.calls("GET", SMB)[-1].headers["X-CSRF-Token"] == "csrf-fresh"


async def test_rejected_login_pauses_further_logins(connection, console):
    console.reply("POST", "/api/auth/login", {"code": "AUTHENTICATION_FAILED_INVALID_CREDENTIALS"}, status=401)

    with pytest.raises(UniFiAuthError, match="rejected the configured username/password") as first:
        await connection.get(SMB)
    with pytest.raises(UniFiAuthError, match="paused"):
        await connection.get(SMB)

    assert len(console.calls("POST", "/api/auth/login")) == 1
    assert PASSWORD not in str(first.value) and USERNAME not in str(first.value)
    assert connection.last_connection_error


async def test_reconnect_blocked_latches_on_a_refused_login_until_one_succeeds(connection, console):
    """Like InnerSpace's: the API heals a cached connection with this flag once a probe proves the login works."""
    assert connection.reconnect_blocked is False

    console.reply("POST", "/api/auth/login", {"code": "AUTHENTICATION_FAILED_INVALID_CREDENTIALS"}, status=401)
    with pytest.raises(UniFiAuthError):
        await connection.get(SMB)
    assert connection.reconnect_blocked is True

    # The pause running out does not clear it: only a login that succeeds does.
    connection._login_block_until = 0.0
    assert connection.reconnect_blocked is True

    console.reply("GET", SMB, service(True))
    assert await connection.get(SMB) == {"enable": True}
    assert connection.reconnect_blocked is False


async def test_a_rate_limited_login_latches_reconnect_blocked(connection, console):
    console.reply("POST", "/api/auth/login", {}, status=429)

    with pytest.raises(UniFiRateLimitError):
        await connection.get(SMB)

    assert connection.reconnect_blocked is True


async def test_a_console_that_is_down_does_not_latch_reconnect_blocked(connection, console):
    console.reply("POST", "/api/auth/login", {}, status=503)

    with pytest.raises(UniFiConnectionError):
        await connection.get(SMB)

    assert connection.reconnect_blocked is False


async def test_unconfigured_manager_makes_no_request(console):
    manager = DriveConnectionManager("", "", "", base_url=console.base_url)

    with pytest.raises(UniFiAuthError, match="UNIFI_DRIVE_HOST"):
        await manager.get(SMB)

    assert console.requests == []


@pytest.mark.parametrize(
    ("status", "payload", "error", "match"),
    [
        (403, {}, UniFiPermissionError, "403"),
        (404, {"err": {"msg": "not here", "code": "ErrNotFound"}}, UniFiOperationError, "no endpoint"),
        (400, {"err": {"msg": f"bad client {HOST}"}}, UniFiValidationError, "bad client"),
        (500, {}, UniFiOperationError, r"\(500\)"),
        (302, None, UniFiConnectionError, "redirect"),
    ],
)
async def test_error_statuses_map_to_specific_errors(connection, console, status, payload, error, match):
    console.reply("GET", SMB, payload, status=status, headers={"Location": "https://elsewhere.invalid/"})

    with pytest.raises(error, match=match) as raised:
        await connection.get(SMB)

    assert HOST not in str(raised.value)
    assert "127.0.0.1" not in str(raised.value)


async def test_404_for_a_named_resource_is_not_found(connection, console):
    path = "/proxy/drive/api/v2/drives/abc"
    console.reply("GET", path, {"err": {"msg": "drive not found", "code": "ErrNotFound"}}, status=404)

    with pytest.raises(UniFiNotFoundError, match="Shared drive 'abc' not found"):
        await connection.get(path, resource=("Shared drive", "abc"))


async def test_error_in_a_200_envelope_is_raised(connection, console):
    console.reply(
        "GET", SMB, {"err": {"msg": "smb service not registered", "data": []}, "type": "single", "data": None}
    )

    with pytest.raises(UniFiOperationError, match="smb service not registered"):
        await connection.get(SMB)


async def test_unenveloped_body_is_returned_as_is(connection, console):
    console.reply("GET", "/proxy/drive/api/v2/drives", {"drives": []})

    assert await connection.get("/proxy/drive/api/v2/drives") == {"drives": []}


@pytest.mark.parametrize(
    "path",
    ["proxy/drive/api/v1/services", "//elsewhere.invalid/x", "/proxy/drive/api/v2/drives/../storage", "/a%2e%2e/b"],
)
async def test_paths_that_could_change_the_destination_make_no_request(connection, console, path):
    with pytest.raises(UniFiValidationError):
        await connection.get(path)

    assert console.requests == []


async def test_unreachable_console_error_names_no_address():
    manager = DriveConnectionManager("192.0.2.1", USERNAME, PASSWORD, base_url="http://127.0.0.1:9")

    with pytest.raises(UniFiConnectionError) as raised:
        await manager.get(SMB)

    assert "127.0.0.1" not in str(raised.value) and "192.0.2.1" not in str(raised.value)
    await manager.close()


async def test_close_logs_out(connection, console):
    console.reply("GET", SMB, service(True))
    await connection.get(SMB)

    await connection.close()

    (logout,) = console.calls("POST", "/api/auth/logout")
    assert logout.headers["X-CSRF-Token"] == CSRF
    assert not connection.is_connected


def test_session_ignores_proxy_environment_and_redirects():
    source = open(cm.__file__, encoding="utf-8").read()
    assert "trust_env=False" in source
    assert "allow_redirects=False" in source
    # The module never reads the process environment.
    assert not hasattr(cm, "os")


def test_malformed_pin_fails_at_construction():
    with pytest.raises(ValueError, match="SHA-256"):
        DriveConnectionManager(HOST, USERNAME, PASSWORD, ssl_fingerprint="not-a-fingerprint")


async def test_write_rejected_with_401_is_sent_once_more_after_login(connection, console):
    console.reply("GET", SMB, service(True))
    await connection.get(SMB)
    console.reply("PUT", SMB, status=401)
    console.reply("POST", "/api/auth/login", {}, headers={"x-csrf-token": "csrf-fresh"})
    console.reply("PUT", SMB, service(False))

    assert await connection.put(SMB, {"enable": False}) == {"enable": False}

    first, replay = console.calls("PUT", SMB)
    assert first.body == replay.body == {"enable": False}
    assert replay.headers["X-CSRF-Token"] == "csrf-fresh"


async def test_write_rejected_twice_is_not_sent_a_third_time(connection, console):
    console.reply("PUT", SMB, status=401)
    console.reply("PUT", SMB, status=401)

    with pytest.raises(UniFiAuthError, match="after logging in again"):
        await connection.put(SMB, {"enable": False})

    assert len(console.calls("PUT", SMB)) == 2


@pytest.fixture
async def impatient(console):
    """A client whose own request timeout is far shorter than the console's slow replies."""
    manager = DriveConnectionManager(HOST, USERNAME, PASSWORD, base_url=console.base_url, timeout_seconds=0.2)
    yield manager
    await manager.close()


async def test_a_change_sent_and_never_answered_has_an_unknown_outcome(impatient, console):
    console.reply("PUT", SMB, service(False), delay=1)

    with pytest.raises(DriveWriteOutcomeUnknown, match="whether it was applied is unknown") as raised:
        await impatient.put(SMB, {"enable": False})

    assert isinstance(raised.value, UniFiConnectionError)
    assert len(console.calls("PUT", SMB)) == 1
    assert "127.0.0.1" not in str(raised.value) and HOST not in str(raised.value)


async def test_a_read_that_is_never_answered_is_a_plain_connection_error(impatient, console):
    console.reply("GET", SMB, service(True), delay=1)

    with pytest.raises(UniFiConnectionError, match="timed out") as raised:
        await impatient.get(SMB)

    assert not isinstance(raised.value, DriveWriteOutcomeUnknown)


async def test_a_change_whose_login_fails_is_not_of_unknown_outcome():
    manager = DriveConnectionManager("192.0.2.1", USERNAME, PASSWORD, base_url="http://127.0.0.1:9")

    with pytest.raises(UniFiConnectionError) as raised:
        await manager.put(SMB, {"enable": False})

    assert not isinstance(raised.value, DriveWriteOutcomeUnknown)
    await manager.close()


async def test_a_certificate_failure_names_only_the_drive_pin():
    """The shared fingerprint pins the gateway, so Drive's remediation never suggests it."""
    manager = DriveConnectionManager(HOST, USERNAME, PASSWORD, tls_env_prefix="DRIVE")
    session = manager._get_session()
    try:
        (middleware,) = session._middlewares

        async def handler(request):
            raise aiohttp.ServerFingerprintMismatch(b"a" * 32, b"b" * 32, HOST, 443)

        with pytest.raises(CertificateVerificationError) as caught:
            await middleware(None, handler)
    finally:
        await session.close()
    message = str(caught.value)
    assert "UNIFI_DRIVE_SSL_FINGERPRINT" in message
    assert "UNIFI_SSL_FINGERPRINT" not in message
