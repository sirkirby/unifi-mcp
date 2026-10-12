"""Protect's connection paths stay behind the test-suite network guard.

Core tests run the connection manager's real login paths, so a Protect
manager pointed at a non-loopback controller must be refused and recorded
even though ``ensure_connected`` swallows the error.
"""

import pytest
import unifi_test_guard
from unifi_core.protect.managers.connection_manager import ProtectConnectionManager


def _take_blocked() -> list[str]:
    blocked = list(unifi_test_guard.blocked_network_access())
    unifi_test_guard.blocked_network_access().clear()
    return blocked


@pytest.mark.parametrize(
    ("host", "blocked"),
    [
        ("192.0.2.1", "192.0.2.1:443"),
        ("unifi.example.invalid", "DNS lookup of 'unifi.example.invalid'"),
    ],
)
@pytest.mark.asyncio
async def test_a_reconnect_to_a_non_loopback_controller_is_refused_and_recorded(host, blocked):
    manager = ProtectConnectionManager(host=host, username="fake-user", password="fake-password")
    try:
        assert await manager.ensure_connected() is False
    finally:
        await manager.close()
    assert _take_blocked() == [blocked]
