"""A Protect connection that failed at start-up is retried on later calls.

``initialize()`` ran once at start-up: when the controller was unreachable or
rejected the login then, every later call failed until the process restarted.
``ensure_connected()`` gives later callers one rate-limited attempt, and a
rejected login opens an auth circuit with an escalating cool-down so repeated
calls cannot lock the account out.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from uiprotect.exceptions import NotAuthorized, NvrError
from unifi_core.exceptions import UniFiConnectionError
from unifi_core.protect.managers import connection_manager as module

FAKE_PASSWORD = "fake-password-for-tests"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _client(update_error: BaseException | None = None) -> MagicMock:
    client = MagicMock()
    client.update = AsyncMock(side_effect=update_error)
    client.async_disconnect_ws = AsyncMock()
    client.close_session = AsyncMock()
    return client


async def _single_attempt(operation, policy=None):
    return await operation()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def make_manager(monkeypatch, clock):
    managers = []

    def _make(clients, **kwargs):
        factory = MagicMock(side_effect=clients)
        monkeypatch.setattr(module, "ProtectApiClient", factory)
        monkeypatch.setattr(module, "retry_with_backoff", _single_attempt)
        manager = module.ProtectConnectionManager(
            host="controller.invalid", username="fake-user", password=FAKE_PASSWORD, **kwargs
        )
        manager._clock = clock
        managers.append(manager)
        return manager, factory

    yield _make
    for manager in managers:
        if manager._refresh_task is not None:
            manager._refresh_task.cancel()


def _connection_refused() -> OSError:
    return ConnectionRefusedError(f"connect failed password={FAKE_PASSWORD}")


def _rejected_login() -> NotAuthorized:
    return NotAuthorized(f"Request failed: /api/auth/login - Status: 401 - Reason: password={FAKE_PASSWORD}")


@pytest.mark.asyncio
async def test_down_at_start_then_up_the_next_call_connects_and_starts_everything(make_manager, clock):
    up = _client()
    manager, factory = make_manager([_client(_connection_refused()), up], bootstrap_refresh_seconds=60)
    hook = AsyncMock()
    manager.add_connect_hook(hook)

    assert await manager.initialize() is False
    hook.assert_not_awaited()
    assert manager._refresh_task is None
    with pytest.raises(UniFiConnectionError, match="ConnectionRefusedError"):
        manager.client

    clock.advance(module.RECONNECT_MIN_INTERVAL_SECONDS)
    assert await manager.ensure_connected() is True

    assert manager.client is up
    assert factory.call_count == 2
    assert manager._refresh_task is not None and not manager._refresh_task.done()
    hook.assert_awaited_once()
    assert manager.support_status()["last_attempt"]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_a_connected_manager_makes_no_attempt(make_manager):
    manager, factory = make_manager([_client()])
    assert await manager.initialize() is True
    assert await manager.ensure_connected() is True
    assert factory.call_count == 1


@pytest.mark.asyncio
async def test_hooks_run_after_a_normal_start_too(make_manager):
    manager, _ = make_manager([_client()])
    hook = AsyncMock()
    manager.add_connect_hook(hook)
    assert await manager.initialize() is True
    hook.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_failing_hook_does_not_undo_the_connection(make_manager, clock):
    manager, _ = make_manager([_client(_connection_refused()), _client()])
    manager.add_connect_hook(AsyncMock(side_effect=RuntimeError("listener failed")))
    assert await manager.initialize() is False
    clock.advance(module.RECONNECT_MIN_INTERVAL_SECONDS)
    assert await manager.ensure_connected() is True
    assert manager._initialized and manager._client is not None


@pytest.mark.asyncio
async def test_attempts_are_rate_limited(make_manager, clock):
    manager, factory = make_manager([_client(_connection_refused()) for _ in range(3)])
    assert await manager.initialize() is False
    assert factory.call_count == 1

    # Inside the window that the failed start opened: no attempt.
    clock.advance(module.RECONNECT_MIN_INTERVAL_SECONDS - 1)
    assert await manager.ensure_connected() is False
    assert factory.call_count == 1

    clock.advance(1)
    assert await manager.ensure_connected() is False
    assert factory.call_count == 2

    # The failed attempt opens a new window.
    assert await manager.ensure_connected() is False
    clock.advance(module.RECONNECT_MIN_INTERVAL_SECONDS - 1)
    assert await manager.ensure_connected() is False
    assert factory.call_count == 2


@pytest.mark.asyncio
async def test_concurrent_callers_share_one_attempt(make_manager, clock):
    gate = asyncio.Event()
    up = _client()

    async def slow_update():
        await gate.wait()

    up.update.side_effect = slow_update
    manager, factory = make_manager([_client(_connection_refused()), up])
    assert await manager.initialize() is False
    clock.advance(module.RECONNECT_MIN_INTERVAL_SECONDS)

    calls = [asyncio.create_task(manager.ensure_connected()) for _ in range(5)]
    await asyncio.sleep(0)
    gate.set()
    assert await asyncio.gather(*calls) == [True] * 5
    assert factory.call_count == 2


@pytest.mark.asyncio
async def test_an_attempt_that_hangs_is_cut_off_and_released(make_manager, clock):
    hanging = _client()

    async def never_answers():
        await asyncio.Event().wait()

    hanging.update.side_effect = never_answers
    manager, _ = make_manager([_client(_connection_refused()), hanging])
    manager._reconnect_attempt_timeout = 0.01
    assert await manager.initialize() is False
    clock.advance(module.RECONNECT_MIN_INTERVAL_SECONDS)

    assert await manager.ensure_connected() is False
    hanging.close_session.assert_awaited_once()
    assert manager._client is None
    with pytest.raises(UniFiConnectionError, match="TimeoutError"):
        manager.client


@pytest.mark.asyncio
async def test_a_rejected_login_at_start_is_not_retried_and_opens_the_circuit(monkeypatch, clock):
    factory = MagicMock(side_effect=lambda **_: _client(_rejected_login()))
    monkeypatch.setattr(module, "ProtectApiClient", factory)
    sleeps = AsyncMock()
    monkeypatch.setattr("unifi_core.retry.asyncio.sleep", sleeps)
    manager = module.ProtectConnectionManager(host="controller.invalid", username="fake-user", password=FAKE_PASSWORD)
    manager._clock = clock

    assert await manager.initialize() is False
    assert factory.call_count == 1, "the start-up back-off must not retry a rejected login"
    sleeps.assert_not_awaited()
    assert manager.reconnect_cooldown_active
    with pytest.raises(UniFiConnectionError, match="rejected the login"):
        manager.client


@pytest.mark.asyncio
async def test_the_auth_cool_down_blocks_reconnects_and_escalates(make_manager, clock):
    clients = [_client(_rejected_login()) for _ in range(3)] + [_client()]
    manager, factory = make_manager(clients)
    base = module._RECONNECT_BLOCK_BASE_SECONDS

    assert await manager.initialize() is False
    assert manager.reconnect_cooldown_active

    # The rate window has passed, but the cool-down still holds attempts back.
    clock.advance(base - 1)
    assert await manager.ensure_connected() is False
    assert factory.call_count == 1

    # Half-open after the cool-down: one attempt, rejected again, doubles it.
    clock.advance(1)
    assert await manager.ensure_connected() is False
    assert factory.call_count == 2
    clock.advance(2 * base - 1)
    assert await manager.ensure_connected() is False
    assert factory.call_count == 2

    clock.advance(1)
    assert await manager.ensure_connected() is False
    assert factory.call_count == 3
    clock.advance(4 * base)

    # Success clears the circuit.
    assert await manager.ensure_connected() is True
    assert not manager.reconnect_cooldown_active
    assert manager._reconnect_block_count == 0


@pytest.mark.asyncio
async def test_the_cool_down_is_capped(make_manager, clock):
    manager, _ = make_manager([])
    for _ in range(10):
        manager._block_automatic_reconnect(_rejected_login())
    assert manager._reconnect_block_until - clock.now == module._RECONNECT_BLOCK_MAX_SECONDS


@pytest.mark.parametrize(
    ("error", "terminal"),
    [
        (NotAuthorized("Request failed: /api/auth/login - Status: 403 - Reason: Forbidden"), True),
        (NvrError("Request failed: /api/auth/login - Status: 429 - Reason: Too Many Requests"), True),
        (NvrError("Request failed: /api/bootstrap - Status: 4290 - Reason: odd"), False),
        (NvrError("Request failed: /api/bootstrap - Status: 502 - Reason: Bad Gateway"), False),
        (ConnectionRefusedError("refused"), False),
        (TimeoutError(), False),
    ],
)
def test_terminal_auth_classification(error, terminal):
    assert module._is_terminal_auth_error(error) is terminal


@pytest.mark.asyncio
async def test_close_stops_automatic_reconnects(make_manager, clock):
    manager, factory = make_manager([_client(_connection_refused()), _client()])
    assert await manager.initialize() is False
    await manager.close()
    clock.advance(module.RECONNECT_MIN_INTERVAL_SECONDS)
    assert await manager.ensure_connected() is False
    assert factory.call_count == 1
    with pytest.raises(UniFiConnectionError, match="closed"):
        manager.client


@pytest.mark.asyncio
async def test_close_during_an_attempt_releases_the_new_client(make_manager, clock):
    gate = asyncio.Event()
    updating = asyncio.Event()
    late = _client()

    async def slow_update():
        updating.set()
        await gate.wait()

    late.update.side_effect = slow_update
    manager, _ = make_manager([_client(_connection_refused()), late])
    assert await manager.initialize() is False
    clock.advance(module.RECONNECT_MIN_INTERVAL_SECONDS)

    attempt = asyncio.create_task(manager.ensure_connected())
    await updating.wait()
    await manager.close()
    gate.set()
    assert await attempt is False
    assert manager._client is None
    late.close_session.assert_awaited_once()


@pytest.mark.asyncio
async def test_errors_and_logs_carry_no_secrets(make_manager, clock, caplog):
    manager, _ = make_manager([_client(_connection_refused()), _client(_rejected_login())])
    caplog.set_level(logging.DEBUG, logger=module.logger.name)

    assert await manager.initialize() is False
    with pytest.raises(UniFiConnectionError) as refused:
        manager.client
    clock.advance(module.RECONNECT_MIN_INTERVAL_SECONDS)
    assert await manager.ensure_connected() is False
    with pytest.raises(UniFiConnectionError) as rejected:
        manager.client

    texts = [str(refused.value), str(rejected.value), caplog.text, str(manager.support_status())]
    for text in texts:
        assert FAKE_PASSWORD not in text
        assert "password=" not in text
    assert "ConnectionRefusedError" in str(refused.value)
    assert "NotAuthorized" in str(rejected.value)
    assert "reconnect" in caplog.text
