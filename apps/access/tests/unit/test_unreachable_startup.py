"""The server keeps serving when its controller cannot be reached at startup.

Network and Protect log a failed connection and carry on, so tools can report
the problem. These tests drive `main_async` with a real
`AccessConnectionManager` whose HTTP layer fails, so the connection manager's
actual failure contract reaches the startup code. No network is touched: every
aiohttp request raises before leaving the process, and retry delays are skipped.
"""

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


@pytest.mark.asyncio
async def test_startup_registers_tools_and_serves_when_controller_unreachable(monkeypatch):
    from unifi_access_mcp import main

    cm = _unreachable_cm()
    listed: list[str] = []

    async def serve(*, server, **_kwargs):
        listed.extend(tool.name for tool in await server.list_tools())

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
    assert cm.last_connection_error.startswith("Could not reach or authenticate to UniFi Access at 192.0.2.1")


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
    assert result["error"].startswith("Failed to list doors: No auth path available for list_doors: Could not reach")
    assert "fake-password" not in result["error"]
    await cm.close()
