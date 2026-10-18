"""What a Network call is told when no controller connection is available.

The stored failure text (see test_connection_error_guidance) is reused here;
these tests cover the cases the connection attempt adds on top of it.
"""

import asyncio

import pytest
from aiounifi.errors import LoginRequired, RequestError
from unifi_core.network.managers import connection_manager as module
from unifi_core.network.managers.connection_manager import ConnectionManager


def _manager() -> ConnectionManager:
    return ConnectionManager("192.0.2.1", "fake-user", "fake-password")


def test_aiounifi_transport_failure_without_a_cause_is_unreachable():
    # aiounifi raises this "from None", so there is no cause chain to walk.
    message = _manager()._sanitize_connection_error(
        RequestError("Error requesting data from https://192.0.2.1:443/api/login: Connection timeout")
    )

    assert message.startswith("RequestError: cannot reach the controller")
    assert "credentials" not in message and "MFA" not in message


@pytest.mark.asyncio
async def test_a_running_attempt_says_still_connecting():
    cm = _manager()
    gate = asyncio.Event()

    async def connect() -> bool:
        await gate.wait()
        return False

    cm._attempt.start(connect, name="test-connect")
    try:
        message = cm.not_connected_message()
    finally:
        gate.set()
        await cm._attempt.join()

    assert message.startswith("Not connected to controller: still connecting")
    assert "host and port" in message
    assert "credentials" not in message and "MFA" not in message


def test_an_unreachable_controller_reports_the_stored_error_and_the_next_attempt(monkeypatch):
    cm = _manager()
    cm._record_connection_error(ConnectionRefusedError())
    cm._last_failed_connect_at = module._time.monotonic()

    message = cm.not_connected_message()

    assert message.startswith(
        "Not connected to controller: last connection attempt failed: "
        "ConnectionRefusedError: cannot reach the controller"
    )
    assert "The next connection attempt is allowed in" in message
    assert "credentials" not in message and "MFA" not in message


def test_a_rejected_login_reports_the_credentials_and_no_retry_time():
    cm = _manager()
    cm._block_automatic_reconnect(LoginRequired("401"))
    cm._last_failed_connect_at = module._time.monotonic()

    message = cm.not_connected_message()

    assert message == (
        "Not connected to controller: last connection attempt failed: "
        "LoginRequired: check credentials and MFA/TOTP configuration."
    )
