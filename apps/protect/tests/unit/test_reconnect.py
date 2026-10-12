"""Protect tools reconnect when the controller was unavailable at start-up."""

from __future__ import annotations

import inspect
from typing import Annotated
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import Field

from unifi_protect_mcp.reconnect import reconnecting_tool_decorator


def _recording_decorator(registered: list):
    def tool(*args, **kwargs):
        def register(func):
            registered.append(func)
            return func

        return register

    return tool


@pytest.mark.asyncio
async def test_each_call_ensures_a_connection_before_the_tool_runs():
    order = []
    cm = MagicMock()
    cm.ensure_connected = AsyncMock(side_effect=lambda: order.append("connect") or True)
    registered: list = []

    @reconnecting_tool_decorator(_recording_decorator(registered), cm)(name="protect_example")
    async def protect_example(camera_id: Annotated[str, Field(description="Camera")]) -> dict:
        order.append("tool")
        return {"success": True, "data": camera_id}

    assert await registered[0](camera_id="cam-1") == {"success": True, "data": "cam-1"}
    assert order == ["connect", "tool"]
    # FastMCP builds the input schema from the signature it sees.
    assert list(inspect.signature(registered[0]).parameters) == ["camera_id"]
    assert registered[0].__name__ == "protect_example"


@pytest.mark.asyncio
async def test_a_failed_attempt_leaves_the_tool_to_report_the_error():
    cm = MagicMock()
    cm.ensure_connected = AsyncMock(return_value=False)
    registered: list = []

    @reconnecting_tool_decorator(_recording_decorator(registered), cm)()
    async def protect_example() -> dict:
        return {"success": False, "error": "Failed to list cameras: not connected"}

    assert (await registered[0]())["success"] is False
    cm.ensure_connected.assert_awaited_once()


@pytest.fixture
def scratch_tool():
    """Register a throwaway tool through the server's real decorator chain."""
    from unifi_mcp_shared.tool_index import TOOL_REGISTRY
    from unifi_protect_mcp import main

    name = "protect_reconnect_probe"
    calls: list[str] = []

    @main.server.tool(name=name, description="Test-only probe.")
    async def protect_reconnect_probe() -> dict:
        connected = main.connection_manager._client is not None
        calls.append("connected" if connected else "disconnected")
        return {"success": connected, "data": None}

    try:
        yield main, protect_reconnect_probe, calls
    finally:
        main.server.remove_tool(name)
        TOOL_REGISTRY.pop(name, None)


@pytest.mark.asyncio
async def test_domain_tools_registered_by_the_server_reconnect(scratch_tool, monkeypatch):
    main, tool, calls = scratch_tool
    ensure = AsyncMock(return_value=False)
    # On the class: undoing an instance patch would pin the autouse stub to the singleton.
    monkeypatch.setattr(type(main.connection_manager), "ensure_connected", ensure)
    await tool()
    ensure.assert_awaited_once()
    assert calls == ["disconnected"]


def test_meta_tools_use_the_plain_decorator():
    from unifi_protect_mcp import main
    from unifi_protect_mcp.runtime import server

    assert main._original_tool_decorator is server._original_tool


@pytest.mark.real_reconnect
@pytest.mark.asyncio
async def test_down_at_start_then_up_the_next_tool_call_starts_the_listener(scratch_tool, monkeypatch):
    """End to end over the runtime singletons, with the SDK client mocked."""
    from unifi_core.protect.managers import connection_manager as module

    main, tool, calls = scratch_tool
    cm = main.connection_manager
    now = [1000.0]
    for attr, value in {
        "_client": None,
        "_initialized": False,
        "_closed": False,
        "_refresh_task": None,
        "_bootstrap_refresh_seconds": 60.0,
        "_connect_hooks": [],
        "_clock": lambda: now[0],
        "_last_connect_attempt_at": None,
        "_last_failure_class": None,
    }.items():
        monkeypatch.setattr(cm, attr, value)
    monkeypatch.setattr(main.event_manager, "_ws_unsub", None)

    down = MagicMock()
    down.update = AsyncMock(side_effect=ConnectionRefusedError("controller down"))
    down.async_disconnect_ws = AsyncMock()
    down.close_session = AsyncMock()
    up = MagicMock()
    up.update = AsyncMock()
    unsubscribe = MagicMock()
    up.subscribe_websocket = MagicMock(return_value=unsubscribe)
    monkeypatch.setattr(module, "ProtectApiClient", MagicMock(side_effect=[down, up]))

    async def single_attempt(operation, policy=None):
        return await operation()

    monkeypatch.setattr(module, "retry_with_backoff", single_attempt)

    # What main_async does before the start-up connect.
    cm.add_connect_hook(main.start_event_listener)
    try:
        assert await cm.initialize() is False
        up.subscribe_websocket.assert_not_called()

        now[0] += module.RECONNECT_MIN_INTERVAL_SECONDS
        assert await tool() == {"success": True, "data": None}

        assert calls == ["connected"]
        up.subscribe_websocket.assert_called_once()
        assert main.event_manager._ws_unsub is unsubscribe
        assert cm._refresh_task is not None and not cm._refresh_task.done()
    finally:
        if cm._refresh_task is not None:
            cm._refresh_task.cancel()
