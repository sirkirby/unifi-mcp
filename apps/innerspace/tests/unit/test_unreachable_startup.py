"""The server keeps serving when the console cannot be reached or refuses the login at startup.

Drives ``main_async`` with a real connection manager against the loopback stub,
so the manager's failure contract reaches the startup code. Nothing leaves the
process; the clock is injected.
"""

from __future__ import annotations

import pytest
from innerspace_stub import PASSWORD

from tests.unit.harness import SYSTEM_BODY, Clock, build_manager, closed_port, run_main, startup_connect_finished
from unifi_core.innerspace.managers.connection_manager import _RECONNECT_MIN_INTERVAL_SECONDS, SYSTEM_PATH
from unifi_innerspace_mcp.tools import status

pytestmark = pytest.mark.real_reconnect


async def test_startup_serves_when_the_console_is_unreachable(monkeypatch):
    cm = build_manager(f"http://127.0.0.1:{closed_port()}", Clock())
    seen = {}

    async def serving():
        seen["startup_connected"] = await startup_connect_finished()

    try:
        transport = await run_main(monkeypatch, cm, serving)
    finally:
        await cm.close()

    transport.assert_awaited_once()
    assert seen["startup_connected"] is False
    assert cm.is_connected is False
    assert "reachable from this machine" in cm.last_connection_error


async def test_a_rejected_login_keeps_its_cool_down_and_leaks_nothing(monkeypatch, console):
    console.reject_logins()
    clock = Clock()
    cm = build_manager(console.base_url, clock)
    results = []

    async def serving():
        await startup_connect_finished()
        results.extend([await status.innerspace_get_status() for _ in range(3)])
        clock.now += _RECONNECT_MIN_INTERVAL_SECONDS + 1
        results.append(await status.innerspace_get_status())

    try:
        await run_main(monkeypatch, cm, serving)
    finally:
        await cm.close()

    assert console.logins == 1, "the cool-down must hold back further logins"
    for result in results:
        assert result["success"] is False
        assert "rejected the configured username and password" in result["error"]
        assert "Automatic reconnect is paused" in result["error"]
        assert PASSWORD not in result["error"]


async def test_a_console_that_recovers_after_a_rejected_login_serves_again(monkeypatch, console):
    console.reject_logins()
    console.reply("GET", SYSTEM_PATH, SYSTEM_BODY)
    clock = Clock()
    cm = build_manager(console.base_url, clock)
    seen = {}

    async def serving():
        await startup_connect_finished()
        console.reject_logins(False)
        clock.now += 24 * 3600
        seen["recovered"] = await status.innerspace_get_status()

    try:
        await run_main(monkeypatch, cm, serving)
    finally:
        await cm.close()

    assert seen["recovered"]["success"] is True
    assert console.logins == 2
