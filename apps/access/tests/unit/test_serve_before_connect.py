"""Access answers MCP before it reaches the controller, and connects on its own.

The server starts serving while the controller connection is made in the
background. A tool call waits for that connection only within a bound, fails
with a clear "unreachable" error during an outage, and works again once the
controller answers. Every controller here is a loopback fake: a port that
accepts and never answers, a closed port, or a TLS fake that speaks the login.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest
from fake_controller import (
    FAKE_PASSWORD,
    FAKE_USERNAME,
    FakeController,
    SilentPort,
    closed_port,
    run_stdio_server,
    tool_payload,
)

from unifi_access_mcp.tools import doors
from unifi_core.access.managers import connection_manager as acm
from unifi_core.access.managers.door_manager import DoorManager

pytestmark = pytest.mark.real_reconnect

WAIT_SECONDS = 0.5
RECONNECT_INTERVAL_SECONDS = 0.2


@pytest.fixture(autouse=True)
def short_waits(monkeypatch):
    """No start-up back-off and a short reconnect interval, so the tests run in seconds."""
    policy = acm.RetryPolicy
    monkeypatch.setattr(acm, "RetryPolicy", lambda **kw: policy(**{**kw, "base_delay": 0.0, "max_delay": 0.0}))
    monkeypatch.setattr(acm, "_RECONNECT_MIN_INTERVAL_SECONDS", RECONNECT_INTERVAL_SECONDS)


def _manager(port: int) -> acm.AccessConnectionManager:
    cm = acm.AccessConnectionManager(
        host="127.0.0.1", username=FAKE_USERNAME, password=FAKE_PASSWORD, port=port, verify_ssl=False
    )
    cm._attempt.wait_seconds = WAIT_SECONDS
    return cm


async def _start(cm: acm.AccessConnectionManager) -> asyncio.Task:
    """Start the connect in the background, as ``main_async`` does before it serves."""
    startup = asyncio.create_task(cm.initialize())
    # The server's first request is read after the startup task has begun.
    await asyncio.sleep(0)
    return startup


@pytest.fixture
def serve_doors():
    """Point ``access_list_doors`` at a test's connection manager for the whole test."""
    with patch.object(doors, "door_manager") as patched:

        def _serve(cm: acm.AccessConnectionManager) -> None:
            patched.list_doors = DoorManager(cm).list_doors

        yield _serve


async def _list_doors(cm: acm.AccessConnectionManager) -> dict:
    return await doors.access_list_doors()


@pytest.mark.asyncio
async def test_a_call_while_the_controller_hangs_fails_within_the_bound(serve_doors):
    with SilentPort() as silent:
        cm = _manager(silent.port)
        serve_doors(cm)
        startup = await _start(cm)
        try:
            started = time.monotonic()
            result = await _list_doors(cm)
            elapsed = time.monotonic() - started
        finally:
            await cm.close()
            await asyncio.gather(startup, return_exceptions=True)

    assert elapsed < WAIT_SECONDS + 1.0
    assert result["success"] is False
    assert "still connecting to UniFi Access" in result["error"]
    assert "credentials" not in result["error"]


@pytest.mark.asyncio
async def test_the_server_recovers_when_the_controller_comes_up(tmp_path, serve_doors):
    port = closed_port()
    cm = _manager(port)
    serve_doors(cm)
    controller = FakeController("access")
    try:
        assert await cm.initialize() is False
        assert cm.last_connection_error.startswith("Could not connect to UniFi Access at 127.0.0.1")

        started = time.monotonic()
        outage = await _list_doors(cm)
        assert time.monotonic() - started < 1.0, "a call within the reconnect interval must fail fast"
        assert outage["success"] is False
        assert "Could not connect to UniFi Access" in outage["error"]
        assert "credentials" not in outage["error"]

        await controller.start(port, tmp_path)
        await asyncio.sleep(RECONNECT_INTERVAL_SECONDS)
        # The outage call above needs the short window; the recovery call makes a
        # real login against the fake, which can outlast it on a busy runner.
        cm._attempt.wait_seconds = 10.0
        recovered = await _list_doors(cm)
    finally:
        await cm.close()
        await controller.close()

    assert recovered["success"] is True, recovered
    assert controller.logins == 1


@pytest.mark.asyncio
async def test_a_healthy_controller_serves_the_first_call_as_before(tmp_path, serve_doors):
    port = closed_port()
    controller = FakeController("access")
    await controller.start(port, tmp_path)
    cm = _manager(port)
    serve_doors(cm)
    try:
        startup = await _start(cm)
        result = await _list_doors(cm)
        assert await startup is True
    finally:
        await cm.close()
        await controller.close()

    assert result == {"success": True, "data": {"doors": [], "count": 0}}
    assert controller.logins == 1


@pytest.mark.asyncio
async def test_a_rejected_login_keeps_its_cool_down(tmp_path, serve_doors):
    port = closed_port()
    controller = FakeController("access", login_status=401)
    await controller.start(port, tmp_path)
    cm = _manager(port)
    serve_doors(cm)
    try:
        assert await cm.initialize() is False
        await asyncio.sleep(RECONNECT_INTERVAL_SECONDS)
        results = [await _list_doors(cm) for _ in range(3)]
    finally:
        await cm.close()
        await controller.close()

    assert controller.logins == 1, "the cool-down must hold back further logins"
    for result in results:
        assert result["success"] is False
        assert "rejected the configured credentials" in result["error"]
        assert "Automatic reconnect is paused" in result["error"]


@pytest.mark.asyncio
async def test_concurrent_first_calls_share_one_connection_attempt(tmp_path, serve_doors):
    port = closed_port()
    controller = FakeController("access")
    controller.release.clear()
    await controller.start(port, tmp_path)
    cm = _manager(port)
    serve_doors(cm)
    cm._attempt.wait_seconds = 10.0
    try:
        startup = await _start(cm)
        calls = [asyncio.create_task(_list_doors(cm)) for _ in range(5)]
        await asyncio.wait_for(controller.login_started.wait(), 5)
        await asyncio.sleep(0.05)
        assert not any(call.done() for call in calls)
        controller.release.set()
        results = await asyncio.wait_for(asyncio.gather(*calls), 5)
        assert await startup is True
    finally:
        await cm.close()
        await controller.close()

    assert all(result["success"] for result in results), results
    assert controller.logins == 1


def test_stdio_initialize_and_tools_list_answer_while_the_controller_hangs(tmp_path):
    with SilentPort() as silent:
        run = run_stdio_server(
            tmp_path,
            module="unifi_access_mcp",
            env_prefix="ACCESS",
            port=silent.port,
            tool="access_list_doors",
            wait_seconds=2.0,
        )
        assert silent.connections >= 1, "the server never tried the controller"

    assert run["initialize_seconds"] < 2.0
    assert run["list_seconds"] < 2.0
    assert run["initialize"]["serverInfo"]["name"] == "unifi-access-mcp"
    assert "access_tool_index" in run["tools"]
    assert run["call_seconds"] < 2.0 + 2.0
    payload = tool_payload(run["call"])
    assert payload["success"] is False
    assert "still connecting to UniFi Access" in payload["error"]


def test_stdio_call_against_a_closed_port_reports_the_controller_unreachable(tmp_path):
    run = run_stdio_server(
        tmp_path,
        module="unifi_access_mcp",
        env_prefix="ACCESS",
        port=closed_port(),
        tool="access_list_doors",
        wait_seconds=2.0,
    )

    assert run["initialize_seconds"] < 2.0
    assert "access_tool_index" in run["tools"]
    assert run["call_seconds"] < 2.0 + 2.0
    payload = tool_payload(run["call"])
    assert payload["success"] is False
    assert "Could not connect to UniFi Access at 127.0.0.1" in payload["error"]
    assert "credentials" not in payload["error"]
