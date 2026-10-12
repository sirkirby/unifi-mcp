"""Automatic reconnect after a failed or rejected Access connection.

A controller that is down when the server starts must be picked up by a later
call without a restart, but a down controller must not add a wait to every
call, and a rejected login must never be retried often enough to lock the
account out. Time is advanced by moving the connection manager's recorded
timestamps back, never by sleeping or touching the event loop's clock.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from unifi_core.access.managers import connection_manager as cm_module
from unifi_core.access.managers.connection_manager import AccessConnectionManager, AccessUnavailableError
from unifi_core.access.managers.door_manager import DoorManager
from unifi_core.exceptions import UniFiAuthError

pytestmark = pytest.mark.real_reconnect

FAKE_PASSWORD = "fake-password-do-not-log"
FAKE_API_KEY = "fake-api-key-do-not-log"


@pytest.fixture(autouse=True)
def _no_backoff_sleep():
    with patch("unifi_core.retry.asyncio.sleep", AsyncMock()):
        yield


def _cm(*, api_key: str | None = None) -> AccessConnectionManager:
    return AccessConnectionManager(
        host="192.0.2.1",
        username="fake-user",
        password=FAKE_PASSWORD,
        port=9,
        verify_ssl=False,
        api_key=api_key,
    )


class _Login:
    """Stand-in for the proxy login: refuses, rejects or succeeds on demand."""

    def __init__(self, cm: AccessConnectionManager, mode: str = "down") -> None:
        self.cm = cm
        self.mode = mode
        self.calls = 0

    async def __call__(self) -> None:
        self.calls += 1
        if self.mode == "down":
            raise aiohttp.ClientConnectionError("connection refused")
        if self.mode == "rejected":
            raise UniFiAuthError("Proxy login failed: HTTP 401")
        if self.mode == "hang":
            await asyncio.Event().wait()
        self.cm._csrf_token = "fake-csrf"


def _elapse_rate_limit(cm: AccessConnectionManager) -> None:
    cm._last_attempt_at -= cm_module._RECONNECT_MIN_INTERVAL_SECONDS + 1


def _elapse_cooldown(cm: AccessConnectionManager) -> None:
    cm._reconnect_block_until = 0.0
    _elapse_rate_limit(cm)


async def _start(cm: AccessConnectionManager, login: _Login) -> bool:
    with patch.object(cm, "_proxy_login", login):
        return await cm.initialize()


DOORS = {"data": {"locations": [{"id": "door-1", "name": "Front"}]}}


@pytest.mark.asyncio
async def test_down_at_start_then_up_the_next_call_succeeds_and_runs_callbacks():
    cm = _cm()
    login = _Login(cm, "down")
    callback = AsyncMock()
    cm.add_reconnect_callback(callback)
    assert await _start(cm, login) is False

    login.mode = "up"
    _elapse_rate_limit(cm)
    with (
        patch.object(cm, "_proxy_login", login),
        patch.object(cm, "proxy_request", AsyncMock(return_value=DOORS)),
    ):
        doors = await DoorManager(cm).list_doors()

    assert doors == DOORS["data"]["locations"]
    assert cm.is_connected is True
    assert cm.last_connection_error is None
    callback.assert_awaited_once()
    await cm.close()


@pytest.mark.asyncio
async def test_calls_within_the_interval_fail_fast_without_an_attempt():
    cm = _cm()
    login = _Login(cm, "down")
    assert await _start(cm, login) is False
    startup_attempts = login.calls

    with patch.object(cm, "_proxy_login", login):
        for _ in range(5):
            with pytest.raises(AccessUnavailableError, match="next automatic reconnect attempt is allowed in"):
                await DoorManager(cm).list_doors()
        assert login.calls == startup_attempts

        _elapse_rate_limit(cm)
        with pytest.raises(AccessUnavailableError, match="Could not reach"):
            await DoorManager(cm).list_doors()
        assert login.calls == startup_attempts + 1, "one single attempt, no startup backoff"


@pytest.mark.asyncio
async def test_concurrent_calls_share_one_attempt():
    cm = _cm()
    login = _Login(cm, "down")
    assert await _start(cm, login) is False
    _elapse_rate_limit(cm)
    before = login.calls

    with patch.object(cm, "_proxy_login", login):
        results = await asyncio.gather(*(DoorManager(cm).list_doors() for _ in range(5)), return_exceptions=True)

    assert all(isinstance(r, AccessUnavailableError) for r in results)
    assert login.calls == before + 1


@pytest.mark.asyncio
async def test_rejected_login_is_not_retried_and_opens_an_escalating_cooldown():
    cm = _cm()
    login = _Login(cm, "rejected")
    assert await _start(cm, login) is False
    assert login.calls == 1, "a rejected login must not be retried by the startup backoff"
    assert cm.last_connection_error.startswith("UniFi Access at 192.0.2.1 rejected the configured credentials")
    first_block = cm._reconnect_block_remaining()
    assert 0 < first_block <= cm_module._RECONNECT_BLOCK_BASE_SECONDS

    with patch.object(cm, "_proxy_login", login):
        # Past the ordinary interval but inside the cool-down: no login.
        _elapse_rate_limit(cm)
        for _ in range(5):
            with pytest.raises(AccessUnavailableError, match="Automatic reconnect is paused"):
                await DoorManager(cm).list_doors()
        assert login.calls == 1

        # Cool-down over: exactly one half-open attempt, rejected again.
        _elapse_cooldown(cm)
        with pytest.raises(AccessUnavailableError):
            await DoorManager(cm).list_doors()
        assert login.calls == 2
        assert cm._reconnect_block_remaining() > cm_module._RECONNECT_BLOCK_BASE_SECONDS

        # The block doubles per rejection and is capped.
        for _ in range(10):
            _elapse_cooldown(cm)
            with pytest.raises(AccessUnavailableError):
                await DoorManager(cm).list_doors()
        assert cm._reconnect_block_remaining() <= cm_module._RECONNECT_BLOCK_MAX_SECONDS

        # Fixed credentials: the next half-open attempt connects and resets the circuit.
        login.mode = "up"
        _elapse_cooldown(cm)
        with patch.object(cm, "proxy_request", AsyncMock(return_value=DOORS)):
            await DoorManager(cm).list_doors()
    assert cm.is_connected is True
    assert cm._reconnect_block_count == 0


@pytest.mark.asyncio
async def test_rejected_relogin_on_an_expired_session_opens_the_cooldown():
    cm = _cm()
    login = _Login(cm, "up")
    assert await _start(cm, login) is True

    expired = MagicMock()
    expired.status = 401
    request_ctx = MagicMock()
    request_ctx.__aenter__ = AsyncMock(return_value=expired)
    request_ctx.__aexit__ = AsyncMock(return_value=False)
    cm._proxy_session.request = MagicMock(return_value=request_ctx)

    login.mode = "rejected"
    with patch.object(cm, "_proxy_login", login):
        with pytest.raises(
            AccessUnavailableError, match="re-authentication failed: UniFi Access at 192.0.2.1 rejected"
        ):
            await DoorManager(cm).list_doors()
        assert login.calls == 2
        assert cm.has_proxy is False and cm.is_connected is False

        _elapse_rate_limit(cm)
        with pytest.raises(AccessUnavailableError, match="Automatic reconnect is paused"):
            await DoorManager(cm).list_doors()
        assert login.calls == 2


@pytest.mark.asyncio
async def test_a_hanging_controller_is_bounded_by_the_attempt_timeout():
    cm = _cm()
    login = _Login(cm, "hang")
    with patch.object(cm_module, "_CONNECT_ATTEMPT_TIMEOUT_SECONDS", 0.01):
        assert await _start(cm, login) is False
    assert cm.last_connection_error.startswith("Timed out after")
    assert cm._proxy_session is None


@pytest.mark.asyncio
async def test_no_reconnect_after_close():
    cm = _cm()
    login = _Login(cm, "down")
    assert await _start(cm, login) is False
    await cm.close()
    _elapse_rate_limit(cm)
    before = login.calls
    with patch.object(cm, "_proxy_login", login), pytest.raises(AccessUnavailableError):
        await DoorManager(cm).list_doors()
    assert login.calls == before


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["down", "rejected"])
async def test_messages_and_logs_carry_no_secrets(caplog, mode):
    cm = _cm(api_key=FAKE_API_KEY)
    login = _Login(cm, mode)
    with caplog.at_level(logging.DEBUG), patch.object(cm, "_try_api_client", AsyncMock()):
        assert await _start(cm, login) is False
        _elapse_cooldown(cm)
        with patch.object(cm, "_proxy_login", login), pytest.raises(AccessUnavailableError) as raised:
            await DoorManager(cm).list_doors()

    texts = [str(raised.value), cm.last_connection_error, caplog.text]
    for text in texts:
        assert FAKE_PASSWORD not in text
        assert FAKE_API_KEY not in text


@pytest.mark.asyncio
async def test_a_cancelled_attempt_leaves_no_session_behind():
    cm = _cm()
    assert await _start(cm, _Login(cm, "down")) is False
    _elapse_rate_limit(cm)

    task = asyncio.create_task(_start_reconnect(cm, _Login(cm, "hang")))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cm._proxy_session is None


async def _start_reconnect(cm: AccessConnectionManager, login: _Login) -> bool:
    with patch.object(cm, "_proxy_login", login):
        return await cm.reconnect()
