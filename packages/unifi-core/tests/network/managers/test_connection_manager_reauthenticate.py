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
