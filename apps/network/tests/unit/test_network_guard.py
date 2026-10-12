"""The suite's guard keeps the environment-built runtime manager away from real controllers."""

import os

import pytest
import unifi_test_guard


def test_inherited_controller_settings_never_reach_the_runtime_manager():
    from unifi_network_mcp.runtime import connection_manager

    assert os.environ.get("UNIFI_NETWORK_HOST", "") in ("", "127.0.0.1")
    assert connection_manager.host in ("", "127.0.0.1")


@pytest.mark.asyncio
async def test_runtime_manager_does_not_log_in_unless_a_test_opts_in(monkeypatch):
    from unifi_network_mcp.runtime import connection_manager

    monkeypatch.setattr(connection_manager, "host", "192.0.2.1")
    monkeypatch.setattr(connection_manager, "username", "fake-user")
    monkeypatch.setattr(connection_manager, "password", "fake-password")
    before = len(unifi_test_guard.blocked_network_access())

    assert await connection_manager.ensure_session_connected() is False
    assert await connection_manager.initialize() is False

    assert len(unifi_test_guard.blocked_network_access()) == before
