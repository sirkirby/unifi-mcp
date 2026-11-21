"""The server answers MCP before it reaches the console, and connects on its own.

The connection is made in the background while the server serves. A tool call
during that connect, or during an outage, returns fixed text; once the console
answers, the next call logs in once and succeeds. The console is the loopback
stub, the clock is injected and the stub's switches replace every wait.
"""

from __future__ import annotations

import pytest
from innerspace_stub import start_stub

from tests.unit.harness import SYSTEM_BODY, Clock, build_manager, closed_port, run_main, startup_connect_finished
from unifi_core.innerspace.managers.connection_manager import _RECONNECT_MIN_INTERVAL_SECONDS, SYSTEM_PATH
from unifi_innerspace_mcp.tools import status

pytestmark = pytest.mark.real_reconnect

STILL_CONNECTING = "Failed to get InnerSpace status: still connecting to the UniFi OS console."


async def test_serves_before_connect_and_recovers(monkeypatch):
    port = closed_port()
    clock = Clock()
    cm = build_manager(f"http://127.0.0.1:{port}", clock)
    seen = {}

    async def serving():
        seen["connected_when_serving_began"] = cm.is_connected
        seen["startup_connected"] = await startup_connect_finished()
        seen["outage"] = await status.innerspace_get_status()
        stub, server = await start_stub(port)
        try:
            stub.reply("GET", SYSTEM_PATH, SYSTEM_BODY)
            clock.now += _RECONNECT_MIN_INTERVAL_SECONDS + 1
            seen["recovered"] = await status.innerspace_get_status()
            seen["logins"] = stub.logins
        finally:
            await server.close()

    try:
        await run_main(monkeypatch, cm, serving)
    finally:
        await cm.close()

    assert seen["connected_when_serving_began"] is False
    assert seen["startup_connected"] is False
    assert seen["outage"]["success"] is False
    assert "Could not log in to the UniFi OS console" in seen["outage"]["error"]
    assert str(port) not in seen["outage"]["error"]
    assert seen["recovered"] == {
        "success": True,
        "data": {"installed": True, "running": True, "version": "1.2.3", "update_available": None},
    }
    assert seen["logins"] == 1


async def test_a_call_during_the_connect_gets_the_still_connecting_text(monkeypatch, console):
    release = console.hold_logins()
    console.reply("GET", SYSTEM_PATH, SYSTEM_BODY)
    cm = build_manager(console.base_url, Clock())
    cm._attempt.wait_seconds = 0.0
    seen = {}

    async def serving():
        await console.login_arrived.wait()
        seen["during"] = await status.innerspace_get_status()
        release.set()
        seen["startup_connected"] = await startup_connect_finished()
        seen["after"] = await status.innerspace_get_status()

    try:
        await run_main(monkeypatch, cm, serving)
    finally:
        await cm.close()

    assert seen["during"]["success"] is False
    assert seen["during"]["error"].startswith(STILL_CONNECTING)
    assert seen["startup_connected"] is True
    assert seen["after"]["success"] is True
    assert console.logins == 1
