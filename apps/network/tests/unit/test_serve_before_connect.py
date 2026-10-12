"""Network answers MCP before it reaches the controller, and connects on its own.

The server starts serving while the controller connection is made in the
background. A tool call waits for that connection only within a bound, fails
with a clear "unreachable" error during an outage, and works again once the
controller answers. Every controller here is a loopback fake: a port that
accepts and never answers, a closed port, or a TLS fake that speaks the login
to the real ``aiounifi`` SDK.
"""

from __future__ import annotations

import asyncio
import inspect
import time

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

from unifi_core.network.managers import connection_manager as ncm
from unifi_core.network.managers.client_manager import ClientManager
from unifi_network_mcp.reconnect import reconnecting_tool_decorator
from unifi_network_mcp.tools import clients

pytestmark = pytest.mark.real_reconnect

WAIT_SECONDS = 0.5
RECONNECT_INTERVAL_SECONDS = 0.2


@pytest.fixture(autouse=True)
def direct_controller(monkeypatch):
    """A standalone controller and a short reconnect interval, so the tests run in seconds."""
    monkeypatch.setenv("UNIFI_CONTROLLER_TYPE", "direct")
    monkeypatch.setattr(ncm, "_RECONNECT_MIN_INTERVAL_SECONDS", RECONNECT_INTERVAL_SECONDS)


@pytest.fixture
def serve_clients(monkeypatch):
    """Point ``unifi_list_clients`` at a test's connection manager."""

    def _serve(cm: ncm.ConnectionManager) -> None:
        monkeypatch.setattr(clients, "client_manager", ClientManager(cm))

    return _serve


def _manager(port: int) -> ncm.ConnectionManager:
    cm = ncm.ConnectionManager(
        host="127.0.0.1", username=FAKE_USERNAME, password=FAKE_PASSWORD, port=port, retry_delay=0
    )
    cm._attempt.wait_seconds = WAIT_SECONDS
    return cm


async def _start(cm: ncm.ConnectionManager) -> asyncio.Task:
    """Start the connect in the background, as ``main_async`` does before it serves."""
    startup = asyncio.create_task(cm.initialize())
    # The server's first request is read after the startup task has begun.
    await asyncio.sleep(0)
    return startup


async def _list_clients(cm: ncm.ConnectionManager) -> dict:
    """Call ``unifi_list_clients`` the way the server registers it: connect first."""
    registered = []
    reconnecting_tool_decorator(lambda *_a, **_k: registered.append, cm)(name="unifi_list_clients")(
        inspect.unwrap(clients.list_clients)
    )
    return await registered[0]()


@pytest.mark.asyncio
async def test_a_call_while_the_controller_hangs_fails_within_the_bound(serve_clients):
    with SilentPort() as silent:
        cm = _manager(silent.port)
        serve_clients(cm)
        startup = await _start(cm)
        try:
            started = time.monotonic()
            result = await _list_clients(cm)
            elapsed = time.monotonic() - started
        finally:
            await cm.cleanup()
            await asyncio.gather(startup, return_exceptions=True)

    assert elapsed < WAIT_SECONDS + 1.0
    assert result["success"] is False
    assert result["error"].startswith("Cannot run unifi_list_clients: Not connected to controller: still connecting")
    assert "credentials" not in result["error"] and "MFA" not in result["error"]


@pytest.mark.asyncio
async def test_the_server_recovers_when_the_controller_comes_up(tmp_path, serve_clients):
    port = closed_port()
    cm = _manager(port)
    serve_clients(cm)
    controller = FakeController("network")
    try:
        assert await cm.initialize() is False

        started = time.monotonic()
        outage = await _list_clients(cm)
        assert time.monotonic() - started < 1.0, "a call within the reconnect interval must fail fast"
        assert outage["success"] is False
        assert "cannot reach the controller" in outage["error"]
        assert "credentials" not in outage["error"]
        assert "MFA" not in outage["error"]

        await controller.start(port, tmp_path)
        await asyncio.sleep(RECONNECT_INTERVAL_SECONDS)
        recovered = await _list_clients(cm)
    finally:
        await cm.cleanup()
        await controller.close()

    assert recovered["success"] is True, recovered
    assert controller.logins == 1


@pytest.mark.asyncio
async def test_a_healthy_controller_serves_the_first_call_as_before(tmp_path, serve_clients):
    port = closed_port()
    controller = FakeController("network")
    await controller.start(port, tmp_path)
    cm = _manager(port)
    serve_clients(cm)
    try:
        startup = await _start(cm)
        result = await _list_clients(cm)
        assert await startup is True
    finally:
        await cm.cleanup()
        await controller.close()

    assert result["success"] is True, result
    assert result["count"] == 0
    assert controller.logins == 1


@pytest.mark.asyncio
async def test_a_rejected_login_keeps_its_cool_down(tmp_path, serve_clients):
    port = closed_port()
    controller = FakeController("network", login_status=401)
    await controller.start(port, tmp_path)
    cm = _manager(port)
    serve_clients(cm)
    try:
        assert await cm.initialize() is False
        await asyncio.sleep(RECONNECT_INTERVAL_SECONDS)
        results = [await _list_clients(cm) for _ in range(3)]
        assert cm.reconnect_cooldown_active is True
    finally:
        await cm.cleanup()
        await controller.close()

    assert controller.logins == 1, "the cool-down must hold back further logins"
    for result in results:
        assert result["success"] is False
        assert "check credentials and MFA/TOTP configuration" in result["error"]


@pytest.mark.asyncio
async def test_concurrent_first_calls_share_one_connection_attempt(tmp_path, serve_clients):
    port = closed_port()
    controller = FakeController("network")
    controller.release.clear()
    await controller.start(port, tmp_path)
    cm = _manager(port)
    serve_clients(cm)
    cm._attempt.wait_seconds = 10.0
    try:
        startup = await _start(cm)
        calls = [asyncio.create_task(_list_clients(cm)) for _ in range(5)]
        await asyncio.wait_for(controller.login_started.wait(), 5)
        await asyncio.sleep(0.05)
        assert not any(call.done() for call in calls)
        controller.release.set()
        results = await asyncio.wait_for(asyncio.gather(*calls), 5)
        assert await startup is True
    finally:
        await cm.cleanup()
        await controller.close()

    assert all(result["success"] for result in results), results
    assert controller.logins == 1


@pytest.mark.asyncio
async def test_concurrent_on_demand_calls_share_one_attempt_after_the_interval(tmp_path, serve_clients):
    """Without a start-up connect (deferred mode), the first calls still share one login."""
    port = closed_port()
    controller = FakeController("network")
    controller.release.clear()
    await controller.start(port, tmp_path)
    cm = _manager(port)
    serve_clients(cm)
    cm._attempt.wait_seconds = 10.0
    try:
        calls = [asyncio.create_task(_list_clients(cm)) for _ in range(5)]
        await asyncio.wait_for(controller.login_started.wait(), 5)
        controller.release.set()
        results = await asyncio.wait_for(asyncio.gather(*calls), 5)
    finally:
        await cm.cleanup()
        await controller.close()

    assert all(result["success"] for result in results), results
    assert controller.logins == 1


def test_stdio_initialize_and_tools_list_answer_while_the_controller_hangs(tmp_path):
    with SilentPort() as silent:
        run = run_stdio_server(
            tmp_path,
            module="unifi_network_mcp",
            env_prefix="NETWORK",
            port=silent.port,
            tool="unifi_list_clients",
            wait_seconds=2.0,
        )
        assert silent.connections >= 1, "the server never tried the controller"

    assert run["initialize_seconds"] < 2.0
    assert run["list_seconds"] < 2.0
    assert run["initialize"]["serverInfo"]["name"] == "unifi-network-mcp"
    assert "unifi_tool_index" in run["tools"]
    assert run["call_seconds"] < 2.0 + 2.0
    payload = tool_payload(run["call"])
    assert payload["success"] is False
    assert "still connecting" in payload["error"]


def test_stdio_call_against_a_closed_port_reports_the_controller_unreachable(tmp_path):
    run = run_stdio_server(
        tmp_path,
        module="unifi_network_mcp",
        env_prefix="NETWORK",
        port=closed_port(),
        tool="unifi_list_clients",
        wait_seconds=2.0,
    )

    assert run["initialize_seconds"] < 2.0
    assert "unifi_tool_index" in run["tools"]
    assert run["call_seconds"] < 2.0 + 2.0
    payload = tool_payload(run["call"])
    assert payload["success"] is False
    assert "cannot reach the controller" in payload["error"] or "still connecting" in payload["error"]
    assert "MFA" not in payload["error"]
    assert "credentials" not in payload["error"]
