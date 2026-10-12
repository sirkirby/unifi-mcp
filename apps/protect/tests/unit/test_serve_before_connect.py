"""Protect answers MCP before it reaches the controller, and connects on its own.

The server starts serving while the controller connection is made in the
background. A tool call waits for that connection only within a bound, fails
with a clear "not connected" error during an outage, and works again once the
controller answers. Every controller here is a loopback fake: a port that
accepts and never answers, a closed port, or a TLS fake that speaks the login
and an empty bootstrap to the real ``uiprotect`` SDK.
"""

from __future__ import annotations

import asyncio
import inspect
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

from unifi_core.protect.managers import connection_manager as pcm
from unifi_core.protect.managers.camera_manager import CameraManager
from unifi_protect_mcp.reconnect import reconnecting_tool_decorator
from unifi_protect_mcp.tools import cameras

pytestmark = pytest.mark.real_reconnect

WAIT_SECONDS = 0.5
RECONNECT_INTERVAL_SECONDS = 0.2


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    """No start-up back-off, so the tests run in seconds."""
    policy = pcm.RetryPolicy
    monkeypatch.setattr(pcm, "RetryPolicy", lambda **kw: policy(**{**kw, "base_delay": 0.0, "max_delay": 0.0}))


def _manager(port: int) -> pcm.ProtectConnectionManager:
    cm = pcm.ProtectConnectionManager(
        host="127.0.0.1",
        username=FAKE_USERNAME,
        password=FAKE_PASSWORD,
        port=port,
        verify_ssl=False,
        bootstrap_refresh_seconds=0,
    )
    cm._attempt.wait_seconds = WAIT_SECONDS
    cm._reconnect_min_interval = RECONNECT_INTERVAL_SECONDS
    cm._reconnect_attempt_timeout = 5.0
    return cm


async def _start(cm: pcm.ProtectConnectionManager) -> asyncio.Task:
    """Start the connect in the background, as ``main_async`` does before it serves."""
    startup = asyncio.create_task(cm.initialize())
    # The server's first request is read after the startup task has begun.
    await asyncio.sleep(0)
    return startup


@pytest.fixture
def serve_cameras():
    """Point ``protect_list_cameras`` at a test's connection manager for the whole test."""
    with patch.object(cameras, "camera_manager") as patched:

        def _serve(cm: pcm.ProtectConnectionManager) -> None:
            patched.list_cameras = CameraManager(cm).list_cameras

        yield _serve


async def _list_cameras(cm: pcm.ProtectConnectionManager) -> dict:
    """Call ``protect_list_cameras`` the way the server registers it: reconnect first."""
    plain = inspect.unwrap(cameras.protect_list_cameras)
    tool = reconnecting_tool_decorator(lambda *_a, **_k: lambda func: func, cm)(name="protect_list_cameras")(plain)
    return await tool()


@pytest.mark.asyncio
async def test_a_call_while_the_controller_hangs_fails_within_the_bound(serve_cameras):
    with SilentPort() as silent:
        cm = _manager(silent.port)
        serve_cameras(cm)
        startup = await _start(cm)
        try:
            started = time.monotonic()
            result = await _list_cameras(cm)
            elapsed = time.monotonic() - started
        finally:
            await cm.close()
            await asyncio.gather(startup, return_exceptions=True)

    assert elapsed < WAIT_SECONDS + 1.0
    assert result["success"] is False
    assert "still connecting to the controller" in result["error"]
    assert "password" not in result["error"]


@pytest.mark.asyncio
async def test_the_server_recovers_when_the_controller_comes_up(tmp_path, serve_cameras):
    port = closed_port()
    cm = _manager(port)
    serve_cameras(cm)
    controller = FakeController("protect")
    try:
        assert await cm.initialize() is False

        started = time.monotonic()
        outage = await _list_cameras(cm)
        assert time.monotonic() - started < 1.0, "a call within the reconnect interval must fail fast"
        assert outage["success"] is False
        assert "Check that the controller is reachable" in outage["error"]
        assert "password" not in outage["error"]

        await controller.start(port, tmp_path)
        await asyncio.sleep(RECONNECT_INTERVAL_SECONDS)
        recovered = await _list_cameras(cm)
    finally:
        await cm.close()
        await controller.close()

    assert recovered["success"] is True, recovered
    assert controller.logins == 1


@pytest.mark.asyncio
async def test_a_healthy_controller_serves_the_first_call_as_before(tmp_path, serve_cameras):
    port = closed_port()
    controller = FakeController("protect")
    await controller.start(port, tmp_path)
    cm = _manager(port)
    serve_cameras(cm)
    try:
        startup = await _start(cm)
        result = await _list_cameras(cm)
        assert await startup is True
    finally:
        await cm.close()
        await controller.close()

    assert result["success"] is True, result
    assert result["data"]["cameras"] == []
    assert controller.logins == 1


@pytest.mark.asyncio
async def test_a_rejected_login_keeps_its_cool_down(tmp_path, serve_cameras):
    port = closed_port()
    controller = FakeController("protect", login_status=401)
    await controller.start(port, tmp_path)
    cm = _manager(port)
    serve_cameras(cm)
    try:
        assert await cm.initialize() is False
        await asyncio.sleep(RECONNECT_INTERVAL_SECONDS)
        results = [await _list_cameras(cm) for _ in range(3)]
    finally:
        await cm.close()
        await controller.close()

    assert controller.logins == 1, "the cool-down must hold back further logins"
    for result in results:
        assert result["success"] is False
        assert "rejected the login" in result["error"]
        assert "Automatic reconnect is paused" in result["error"]


@pytest.mark.asyncio
async def test_concurrent_first_calls_share_one_connection_attempt(tmp_path, serve_cameras):
    port = closed_port()
    controller = FakeController("protect")
    controller.release.clear()
    await controller.start(port, tmp_path)
    cm = _manager(port)
    serve_cameras(cm)
    cm._attempt.wait_seconds = 10.0
    try:
        startup = await _start(cm)
        calls = [asyncio.create_task(_list_cameras(cm)) for _ in range(5)]
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
            module="unifi_protect_mcp",
            env_prefix="PROTECT",
            port=silent.port,
            tool="protect_list_cameras",
            wait_seconds=2.0,
        )
        assert silent.connections >= 1, "the server never tried the controller"

    assert run["initialize_seconds"] < 2.0
    assert run["list_seconds"] < 2.0
    assert run["initialize"]["serverInfo"]["name"] == "unifi-protect-mcp"
    assert "protect_tool_index" in run["tools"]
    assert run["call_seconds"] < 2.0 + 2.0
    payload = tool_payload(run["call"])
    assert payload["success"] is False
    assert "still connecting to the controller" in payload["error"]


def test_stdio_call_against_a_closed_port_reports_the_controller_unreachable(tmp_path):
    run = run_stdio_server(
        tmp_path,
        module="unifi_protect_mcp",
        env_prefix="PROTECT",
        port=closed_port(),
        tool="protect_list_cameras",
        wait_seconds=2.0,
    )

    assert run["initialize_seconds"] < 2.0
    assert "protect_tool_index" in run["tools"]
    assert run["call_seconds"] < 2.0 + 2.0
    payload = tool_payload(run["call"])
    assert payload["success"] is False
    assert "Check that the controller is reachable" in payload["error"]
    assert "password" not in payload["error"]
