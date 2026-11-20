"""A connection manager given an auth-failure hint adds it to a rejected login only.

A server that ignored a credential setting passes fixed text naming it, so a
caller whose login then fails learns which variable to set. Unreachable hosts,
certificate failures, timeouts and permission errors are not credential
problems and keep their own text. With no usable credential at all, no login
is sent: the managers fail as a rejected login would, carrying the hint.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.errors import Forbidden, LoginRequired, RequestError
from uiprotect.exceptions import NotAuthorized
from unifi_core.access.managers import connection_manager as access_module
from unifi_core.access.managers.connection_manager import AccessConnectionManager
from unifi_core.auth import UniFiAuth
from unifi_core.connection_failure import ControllerAuthFailed
from unifi_core.exceptions import UniFiAuthError, UniFiConnectionError
from unifi_core.network.managers import connection_manager as network_module
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.protect.managers import connection_manager as protect_module
from unifi_core.tls import CertificateVerificationError

HINT = (
    "UNIFI_PASSWORD is set but not used: the host comes from UNIFI_TEST_HOST, "
    "which differs from UNIFI_HOST; set UNIFI_TEST_PASSWORD (or its _FILE/_COMMAND form)."
)


async def _single_attempt(operation, policy=None):
    return await operation()


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


def _network(hint: str | None = HINT) -> ConnectionManager:
    return ConnectionManager("controller.invalid", "fake-user", "fake-password", auth_failure_hint=hint)


@pytest.mark.parametrize(
    "error",
    [LoginRequired("401"), RequestError("SSO MFA required but no totp_secret configured")],
    ids=["rejected", "mfa"],
)
def test_network_rejected_login_carries_the_hint(error):
    cm = _network()
    cm._block_automatic_reconnect(error)

    message = cm.not_connected_message()
    assert message.endswith(f"check credentials and MFA/TOTP configuration. {HINT}")
    failure = cm.initialization_failure
    assert isinstance(failure, ControllerAuthFailed)
    assert HINT in str(failure)


@pytest.mark.parametrize(
    "error",
    [
        ConnectionRefusedError(),
        asyncio.TimeoutError(),
        CertificateVerificationError("certificate check failed"),
        Forbidden("403"),
    ],
    ids=["unreachable", "timeout", "certificate", "forbidden"],
)
def test_network_other_failures_do_not_carry_the_hint(error):
    cm = _network()
    cm._record_connection_error(error)

    assert HINT not in cm.not_connected_message()
    assert HINT not in str(cm.initialization_failure)


def test_network_without_a_hint_keeps_the_rejected_login_text():
    cm = _network(hint=None)
    cm._block_automatic_reconnect(LoginRequired("401"))

    assert cm.not_connected_message() == (
        "Not connected to controller: last connection attempt failed: "
        "LoginRequired: check credentials and MFA/TOTP configuration."
    )


NETWORK_NO_CREDENTIALS = (
    "Not connected to controller: last connection attempt failed: no Network controller credentials "
    "are configured; set a username and password, or an API key."
)


@pytest.fixture
def network_login(monkeypatch):
    """A controller that answers a login with 403, as UniFi OS answers a blank one."""
    login = AsyncMock(side_effect=Forbidden("403"))
    monkeypatch.setattr("aiounifi.controller.Controller.login", login)
    monkeypatch.setattr(network_module, "detect_with_retry", AsyncMock(return_value=True))
    return login


@pytest.mark.asyncio
@pytest.mark.parametrize(("username", "password"), [("", ""), ("fake-user", ""), ("", "fake-password")])
async def test_network_without_credentials_sends_no_login_and_carries_the_hint(network_login, username, password):
    cm = ConnectionManager("controller.invalid", username, password, auth=UniFiAuth(), auth_failure_hint=HINT)

    assert await cm.initialize() is False
    # The tool path: one more attempt is refused by the reconnect interval, the reason stays.
    assert await cm.ensure_connected() is False

    network_login.assert_not_awaited()
    assert cm._aiohttp_session is None
    message = cm.not_connected_message()
    assert message.startswith(f"{NETWORK_NO_CREDENTIALS} {HINT}")
    assert isinstance(cm.initialization_failure, ControllerAuthFailed)
    assert cm.support_status()["last_attempt"]["error_category"] == "authentication"
    assert not cm.reconnect_blocked


@pytest.mark.asyncio
async def test_network_without_credentials_or_hint_says_what_is_missing(network_login):
    cm = ConnectionManager("controller.invalid", "", "", auth=UniFiAuth())

    assert await cm.initialize() is False

    network_login.assert_not_awaited()
    assert cm.last_connection_error == (
        "no Network controller credentials are configured; set a username and password, or an API key."
    )
    assert cm.not_connected_message().startswith(NETWORK_NO_CREDENTIALS)


@pytest.mark.asyncio
async def test_network_blank_login_answered_403_is_never_sent_without_auth_injection(network_login):
    """The legacy constructor (no auth injected) takes the session route directly."""
    cm = ConnectionManager("controller.invalid", "", "", auth_failure_hint=HINT)

    assert await cm.initialize() is False

    network_login.assert_not_awaited()
    assert HINT in cm.not_connected_message()


# ---------------------------------------------------------------------------
# Protect
# ---------------------------------------------------------------------------


@pytest.fixture
def protect_factory(monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr(protect_module, "ProtectApiClient", factory)
    monkeypatch.setattr(protect_module, "retry_with_backoff", _single_attempt)
    return factory


@pytest.fixture
def protect_manager(protect_factory):
    def _make(update_error: BaseException | None, hint: str | None = HINT, **credentials):
        client = MagicMock()
        client.update = AsyncMock(side_effect=update_error)
        client.close_session = AsyncMock()
        client.async_disconnect_ws = AsyncMock()
        protect_factory.return_value = client
        credentials = credentials or {"username": "fake-user", "password": "fake-password"}
        credentials.setdefault("username", "")
        credentials.setdefault("password", "")
        return protect_module.ProtectConnectionManager(
            host="controller.invalid", auth_failure_hint=hint, bootstrap_refresh_seconds=0, **credentials
        )

    return _make


PROTECT_NO_CREDENTIALS = (
    "UniFi Protect connection is not initialized: no UniFi Protect credentials are configured; "
    "set a username and password, or an API key."
)


@pytest.mark.asyncio
@pytest.mark.parametrize("start", ["initialize", "ensure_connected"])
@pytest.mark.parametrize("credentials", [{"username": ""}, {"username": "fake-user"}], ids=["blank", "no-password"])
async def test_protect_without_credentials_sends_no_login_and_carries_the_hint(
    protect_manager, protect_factory, start, credentials
):
    cm = protect_manager(None, **credentials)

    assert await getattr(cm, start)() is False

    protect_factory.assert_not_called()
    assert cm.last_connection_error == f"{PROTECT_NO_CREDENTIALS} {HINT}"
    with pytest.raises(ControllerAuthFailed) as excinfo:
        cm.client
    assert str(excinfo.value) == f"{PROTECT_NO_CREDENTIALS} {HINT}"
    assert cm.support_status()["last_attempt"]["error_category"] == "authentication"


@pytest.mark.asyncio
async def test_protect_api_key_alone_still_connects(protect_manager, protect_factory):
    cm = protect_manager(None, api_key="synthetic-key")

    assert await cm.initialize() is True

    protect_factory.assert_called_once()
    assert cm.last_connection_error is None
    await cm.close()


@pytest.mark.asyncio
async def test_protect_last_connection_error_reports_every_failure(protect_manager):
    cm = protect_manager(ConnectionRefusedError())
    assert cm.last_connection_error is None

    assert await cm.initialize() is False

    assert cm.last_connection_error == (
        "UniFi Protect connection is not initialized: the last connection attempt failed "
        "(ConnectionRefusedError). Check that the controller is reachable; a later call tries to connect again."
    )
    await cm.close()
    assert cm.last_connection_error is None


def _status_error(status: int) -> NotAuthorized:
    return NotAuthorized(f"Request failed: /api/auth/login - Status: {status} - Reason: rejected")


@pytest.mark.asyncio
async def test_protect_rejected_login_carries_the_hint(protect_manager):
    cm = protect_manager(_status_error(401))

    assert await cm.initialize() is False
    with pytest.raises(UniFiConnectionError) as excinfo:
        cm.client

    assert isinstance(excinfo.value, ControllerAuthFailed)
    assert str(excinfo.value).endswith(f"wait for a login lockout to clear. {HINT}")


@pytest.mark.asyncio
async def test_protect_rejected_login_keeps_the_hint_after_the_cool_down(protect_manager):
    cm = protect_manager(_status_error(401))
    assert await cm.initialize() is False
    cm._clear_reconnect_block()

    with pytest.raises(UniFiConnectionError) as excinfo:
        cm.client

    assert str(excinfo.value).endswith(HINT)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [ConnectionRefusedError(), TimeoutError(), CertificateVerificationError("certificate check failed")],
    ids=["unreachable", "timeout", "certificate"],
)
async def test_protect_other_failures_do_not_carry_the_hint(protect_manager, error):
    cm = protect_manager(error)

    assert await cm.initialize() is False
    with pytest.raises(UniFiConnectionError) as excinfo:
        cm.client

    assert HINT not in str(excinfo.value)


@pytest.mark.asyncio
async def test_protect_forbidden_login_does_not_carry_the_hint(protect_manager):
    cm = protect_manager(_status_error(403))

    assert await cm.initialize() is False
    with pytest.raises(UniFiConnectionError) as excinfo:
        cm.client

    assert HINT not in str(excinfo.value)


@pytest.mark.asyncio
async def test_protect_without_a_hint_keeps_the_rejected_login_text(protect_manager):
    cm = protect_manager(_status_error(401), hint=None)

    assert await cm.initialize() is False
    with pytest.raises(UniFiConnectionError) as excinfo:
        cm.client

    assert str(excinfo.value).endswith("check the Protect username and password, or wait for a login lockout to clear.")


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------


def _access(monkeypatch, path_failure: BaseException | None, hint: str | None = HINT, **credentials):
    credentials = credentials or {"username": "fake-user", "password": "fake-password"}
    cm = AccessConnectionManager(host="controller.invalid", auth_failure_hint=hint, **credentials)
    monkeypatch.setattr(access_module, "retry_with_backoff", _single_attempt)

    async def _try_api_client() -> None:
        return None

    async def _try_proxy_session() -> None:
        if path_failure is not None:
            cm._path_failures.append(path_failure)

    monkeypatch.setattr(cm, "_try_api_client", _try_api_client)
    monkeypatch.setattr(cm, "_try_proxy_session", _try_proxy_session)
    return cm


@pytest.mark.asyncio
async def test_access_rejected_login_carries_the_hint(monkeypatch):
    cm = _access(monkeypatch, UniFiAuthError("rejected"))

    assert await cm.initialize() is False

    assert cm.last_connection_error.startswith("UniFi Access rejected the configured credentials")
    assert HINT in cm.last_connection_error
    assert HINT in str(cm.unavailable_error("No auth path available for list_doors"))


@pytest.mark.asyncio
async def test_access_missing_credentials_carry_the_hint(monkeypatch):
    cm = _access(monkeypatch, None, username="", password="")

    assert await cm.initialize() is False

    assert cm.last_connection_error == (
        f"No UniFi Access credentials are configured. Set an API key or a username and password. {HINT}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [UniFiConnectionError("unreachable"), CertificateVerificationError("certificate check failed")],
    ids=["unreachable", "certificate"],
)
async def test_access_other_failures_do_not_carry_the_hint(monkeypatch, error):
    cm = _access(monkeypatch, error)

    assert await cm.initialize() is False

    assert cm.last_connection_error.startswith("Could not connect to UniFi Access")
    assert HINT not in cm.last_connection_error


@pytest.mark.asyncio
async def test_access_timeout_does_not_carry_the_hint(monkeypatch):
    cm = _access(monkeypatch, None)

    async def _hang() -> None:
        raise TimeoutError

    monkeypatch.setattr(cm, "_try_api_client", _hang)

    assert await cm.initialize() is False

    assert cm.last_connection_error.startswith("Timed out after")
    assert HINT not in cm.last_connection_error


@pytest.mark.asyncio
async def test_access_without_a_hint_keeps_the_rejected_login_text(monkeypatch):
    cm = _access(monkeypatch, UniFiAuthError("rejected"), hint=None)

    assert await cm.initialize() is False

    assert cm.last_connection_error == (
        "UniFi Access rejected the configured credentials (tried username/password on port 443). "
        "Check the username/password or API key."
    )
