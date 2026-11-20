"""A connection manager given an auth-failure hint adds it to a rejected login only.

A server that ignored a credential setting passes fixed text naming it, so a
caller whose login then fails learns which variable to set. Unreachable hosts,
certificate failures, timeouts and permission errors are not credential
problems and keep their own text.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.errors import Forbidden, LoginRequired, RequestError
from uiprotect.exceptions import NotAuthorized
from unifi_core.access.managers import connection_manager as access_module
from unifi_core.access.managers.connection_manager import AccessConnectionManager
from unifi_core.connection_failure import ControllerAuthFailed
from unifi_core.exceptions import UniFiAuthError, UniFiConnectionError
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


# ---------------------------------------------------------------------------
# Protect
# ---------------------------------------------------------------------------


@pytest.fixture
def protect_manager(monkeypatch):
    def _make(update_error: BaseException, hint: str | None = HINT):
        client = MagicMock()
        client.update = AsyncMock(side_effect=update_error)
        client.close_session = AsyncMock()
        client.async_disconnect_ws = AsyncMock()
        monkeypatch.setattr(protect_module, "ProtectApiClient", MagicMock(return_value=client))
        monkeypatch.setattr(protect_module, "retry_with_backoff", _single_attempt)
        return protect_module.ProtectConnectionManager(
            host="controller.invalid", username="fake-user", password="fake-password", auth_failure_hint=hint
        )

    return _make


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
