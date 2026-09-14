"""``ConnectionManager.reauthenticate`` is the public entry the event websocket
loop uses after a 401 handshake: aiounifi reuses the login cookie captured at
login and never re-logs-in on its own."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.errors import RequestError
from unifi_core.network.managers.connection_manager import ConnectionManager


@pytest.mark.asyncio
async def test_reauthenticate_refreshes_the_current_session_generation():
    manager = ConnectionManager("192.168.1.1", "admin", "secret")
    manager._auth_generation = 3
    manager._reauthenticate = AsyncMock(return_value=True)

    assert await manager.reauthenticate() is True

    manager._reauthenticate.assert_awaited_once_with(3, rate_limit_login=True)


@pytest.mark.asyncio
async def test_listener_floor_does_not_throttle_foreground_reauthentication():
    manager = ConnectionManager("controller.invalid", "admin", "secret")
    session = MagicMock(closed=False)
    session.close = AsyncMock()
    controller = MagicMock()
    controller.login = AsyncMock()
    controller.connectivity.can_retry_login = True
    manager.controller = controller
    manager._aiohttp_session = session
    manager._initialized = True
    now = {"value": 0.0}
    manager._reauthentication_clock = lambda: now["value"]

    assert await manager.reauthenticate() is True
    now["value"] = 1.0
    assert await manager._reauthenticate(manager._auth_generation) is True

    assert controller.login.await_count == 2


@pytest.mark.asyncio
async def test_failed_reauthentication_defers_listener_session_reinitialization():
    """A discarded failed-login session cannot bypass the listener login floor."""
    manager = ConnectionManager("controller.invalid", "admin", "secret")
    session = MagicMock(closed=False)
    session.close = AsyncMock()
    controller = MagicMock()
    controller.login = AsyncMock(side_effect=RequestError("temporary"))
    manager.controller = controller
    manager._aiohttp_session = session
    manager._initialized = True
    now = {"value": 0.0}
    manager._reauthentication_clock = lambda: now["value"]

    assert await manager.reauthenticate() is False
    controller.login.assert_awaited_once()
    assert manager.controller is None

    manager._initialize_session = AsyncMock(return_value=True)
    now["value"] = 1.0
    assert await manager.ensure_session_connected() is False
    manager._initialize_session.assert_not_awaited()

    now["value"] = 60.0
    assert await manager.ensure_session_connected() is True
    manager._initialize_session.assert_awaited_once_with(rate_limit_login=True)


@pytest.mark.asyncio
async def test_listener_session_reinitialization_allows_one_login_per_window(monkeypatch):
    """The ordinary connection retry loop cannot issue a second listener login."""
    from unifi_core.network.managers import connection_manager as cm_module

    manager = ConnectionManager("controller.invalid", "admin", "secret", max_retries=3, retry_delay=5)
    manager._last_reauthentication_attempt_at = 0.0
    now = {"value": 60.0}
    manager._reauthentication_clock = lambda: now["value"]
    monkeypatch.setenv("UNIFI_CONTROLLER_TYPE", "proxy")

    controller = MagicMock()
    controller.connectivity = MagicMock()
    controller.login = AsyncMock(side_effect=RequestError("temporary"))
    monkeypatch.setattr(cm_module, "Controller", MagicMock(return_value=controller))

    async def _sleep(delay):
        now["value"] += delay

    monkeypatch.setattr(cm_module.asyncio, "sleep", _sleep)

    assert await manager._initialize_session(rate_limit_login=True) is False
    controller.login.assert_awaited_once()
    assert now["value"] == 65.0
    assert manager._last_reauthentication_attempt_at == 60.0


def test_reconnect_cooldown_active_half_opens_on_the_timer(monkeypatch):
    """``reconnect_blocked`` stays latched until a login succeeds (the audit
    signal); ``reconnect_cooldown_active`` is the time-aware gate a retrying
    caller must consult, and it clears when the cool-down expires."""
    from unifi_core.network.managers import connection_manager as cm_module

    manager = ConnectionManager("192.168.1.1", "admin", "secret")
    now = {"t": 1000.0}
    monkeypatch.setattr(cm_module._time, "monotonic", lambda: now["t"])

    assert manager.reconnect_cooldown_active is False
    manager._block_automatic_reconnect(RuntimeError("401"))
    assert manager.reconnect_blocked is True
    assert manager.reconnect_cooldown_active is True

    now["t"] = manager._reconnect_block_until + 1
    assert manager.reconnect_blocked is True
    assert manager.reconnect_cooldown_active is False
