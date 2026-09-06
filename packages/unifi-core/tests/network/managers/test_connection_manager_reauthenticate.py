"""``ConnectionManager.reauthenticate`` is the public entry the event websocket
loop uses after a 401 handshake: aiounifi reuses the login cookie captured at
login and never re-logs-in on its own."""

from unittest.mock import AsyncMock

import pytest
from unifi_core.network.managers.connection_manager import ConnectionManager


@pytest.mark.asyncio
async def test_reauthenticate_refreshes_the_current_session_generation():
    manager = ConnectionManager("192.168.1.1", "admin", "secret")
    manager._auth_generation = 3
    manager._reauthenticate = AsyncMock(return_value=True)

    assert await manager.reauthenticate() is True

    manager._reauthenticate.assert_awaited_once_with(3)


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
