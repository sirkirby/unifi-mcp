"""The server keeps serving when its controller cannot be reached at startup.

Network and Protect log a failed connection and carry on, so tools can report
the problem. These tests drive `main_async` with a real
`AccessConnectionManager` whose HTTP layer fails, so the connection manager's
actual failure contract reaches the startup code. No network is touched: every
aiohttp request raises before leaving the process, and retry delays are skipped.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from unifi_core.access.managers.connection_manager import AccessConnectionManager
from unifi_core.access.managers.door_manager import DoorManager


def _unreachable_cm() -> AccessConnectionManager:
    return AccessConnectionManager(
        host="192.0.2.1",
        username="fake-user",
        password="fake-password",
        port=9,
        verify_ssl=False,
    )


def _refuse(*_args, **_kwargs):
    raise aiohttp.ClientConnectionError("connection refused")


async def _startup_connect_finished() -> None:
    """Wait for the background connect that ``main_async`` starts beside the transports."""
    for task in asyncio.all_tasks():
        if task.get_name() == "access-startup-connect":
            await task


@pytest.mark.asyncio
async def test_startup_registers_tools_and_serves_when_controller_unreachable(monkeypatch):
    from unifi_access_mcp import main

    cm = _unreachable_cm()
    listed: list[str] = []

    async def serve(*, server, **_kwargs):
        listed.extend(tool.name for tool in await server.list_tools())
        await _startup_connect_finished()

    transport = AsyncMock(side_effect=serve)
    monkeypatch.setattr(main, "connection_manager", cm)
    monkeypatch.setattr("unifi_mcp_shared.bootstrap.assert_credentials_configured", lambda *a, **kw: None)
    monkeypatch.setattr("unifi_mcp_shared.transport.run_transports", transport)
    monkeypatch.setattr(
        "unifi_mcp_shared.transport.resolve_http_config", lambda *a, **kw: (False, "http", "127.0.0.1", 3002)
    )
    with (
        patch.object(aiohttp.ClientSession, "post", _refuse),
        patch("unifi_core.retry.asyncio.sleep", AsyncMock()),
        patch.object(main.event_manager, "start_listening", AsyncMock()) as listener,
    ):
        await main.main_async()

    transport.assert_awaited_once()
    listener.assert_not_awaited()
    assert "access_tool_index" in listed
    assert cm.is_connected is False
    assert cm.last_connection_error.startswith("Could not connect to UniFi Access at 192.0.2.1")


@pytest.mark.asyncio
async def test_read_after_failed_startup_reports_the_connection_error():
    cm = _unreachable_cm()
    with (
        patch.object(aiohttp.ClientSession, "post", _refuse),
        patch("unifi_core.retry.asyncio.sleep", AsyncMock()),
    ):
        assert await cm.initialize() is False

    from unifi_access_mcp.tools import doors

    with patch.object(doors, "door_manager", DoorManager(cm)):
        result = await doors.access_list_doors()

    assert result["success"] is False
    assert result["error"].startswith("Failed to list doors: No auth path available for list_doors: Could not connect")
    assert "fake-password" not in result["error"]
    await cm.close()


@pytest.mark.asyncio
@pytest.mark.real_reconnect
@pytest.mark.parametrize("websocket_enabled", [True, False])
async def test_reconnect_after_failed_startup_starts_the_event_listener(monkeypatch, websocket_enabled):
    from unifi_access_mcp import main
    from unifi_access_mcp.runtime import config

    cm = _unreachable_cm()
    events = dict(getattr(config.access, "events", {}) or {})
    events["websocket_enabled"] = websocket_enabled
    reconnected: list[bool] = []

    async def login_succeeds() -> None:
        cm._csrf_token = "fake-csrf"

    async def serve(**_kwargs):
        await _startup_connect_finished()
        # The controller comes back while the server is serving.
        listener.assert_not_awaited()
        cm._last_attempt_at -= 60
        with patch.object(cm, "_proxy_login", login_succeeds):
            reconnected.append(await cm.reconnect())

    monkeypatch.setattr(main, "connection_manager", cm)
    monkeypatch.setattr("unifi_mcp_shared.bootstrap.assert_credentials_configured", lambda *a, **kw: None)
    monkeypatch.setattr("unifi_mcp_shared.tool_registration.register_tools_for_mode", AsyncMock())
    monkeypatch.setattr("unifi_mcp_shared.transport.run_transports", AsyncMock(side_effect=serve))
    monkeypatch.setattr(
        "unifi_mcp_shared.transport.resolve_http_config", lambda *a, **kw: (False, "http", "127.0.0.1", 3002)
    )
    with (
        patch.object(config.access, "events", events),
        patch.object(aiohttp.ClientSession, "post", _refuse),
        patch("unifi_core.retry.asyncio.sleep", AsyncMock()),
        patch.object(main.event_manager, "start_listening", AsyncMock()) as listener,
    ):
        await main.main_async()

    assert reconnected == [True]
    assert listener.await_count == (1 if websocket_enabled else 0)
