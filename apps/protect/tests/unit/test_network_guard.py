"""Protect's reconnect paths stay behind the test-suite network guard."""

import os

import pytest
import unifi_test_guard


def _take_blocked() -> list[str]:
    blocked = list(unifi_test_guard.blocked_network_access())
    unifi_test_guard.blocked_network_access().clear()
    return blocked


def test_inherited_protect_hosts_are_scrubbed():
    assert os.environ.get("UNIFI_PROTECT_HOST", "") in ("", "127.0.0.1")


@pytest.mark.asyncio
async def test_runtime_connection_manager_does_not_reconnect_unless_a_test_opts_in(monkeypatch):
    from unifi_protect_mcp.runtime import connection_manager

    assert connection_manager.host in ("", "127.0.0.1")
    # With a reachable-looking configuration, only the stub stands between a
    # tool call and a login attempt.
    for attr, value in {"host": "192.0.2.1", "username": "fake-user", "password": "fake-password"}.items():
        monkeypatch.setattr(connection_manager, attr, value)
    monkeypatch.setattr(connection_manager, "_last_connect_attempt_at", None)
    assert await connection_manager.ensure_connected() is False
    assert _take_blocked() == []


@pytest.mark.real_reconnect
@pytest.mark.asyncio
async def test_a_real_reconnect_to_a_non_loopback_controller_is_refused_and_recorded():
    from unifi_core.protect.managers.connection_manager import ProtectConnectionManager

    manager = ProtectConnectionManager(host="192.0.2.1", username="fake-user", password="fake-password")
    try:
        assert await manager.ensure_connected() is False
    finally:
        await manager.close()
    assert _take_blocked() == ["192.0.2.1:443"]
