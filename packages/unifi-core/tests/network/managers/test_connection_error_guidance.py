"""The failure text a manager keeps for later callers must point at the real cause."""

import asyncio

import aiohttp
import pytest
from aiounifi.errors import LoginRequired, RequestError
from unifi_core.network.managers.connection_manager import ConnectionManager


def _guidance(error: BaseException) -> str:
    return ConnectionManager("192.0.2.1", "admin", "secret")._sanitize_connection_error(error)


def _raised_from(error: BaseException, cause: BaseException) -> BaseException:
    try:
        raise error from cause
    except type(error) as raised:
        return raised


@pytest.mark.parametrize(
    "cause",
    [
        aiohttp.ClientConnectionError("Cannot connect to host"),
        ConnectionRefusedError(),
        asyncio.TimeoutError(),
    ],
    ids=["client-connection", "refused", "timeout"],
)
def test_unreachable_controller_does_not_blame_credentials(cause):
    message = _guidance(_raised_from(RequestError("Error requesting data"), cause))

    assert message.startswith("RequestError: cannot reach the controller")
    assert "host and port" in message
    assert "credentials" not in message
    assert "MFA" not in message


@pytest.mark.parametrize(
    "error",
    [LoginRequired("login required"), RequestError("SSO MFA required but no totp_secret configured")],
    ids=["login-required", "mfa-required"],
)
def test_terminal_auth_failure_keeps_the_credentials_guidance(error):
    message = _guidance(error)

    assert "credentials and MFA/TOTP configuration" in message
    assert "reach the controller" not in message
