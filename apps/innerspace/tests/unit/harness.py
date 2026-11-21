"""Drive ``main_async`` in-process against a real connection manager and the loopback console stub.

Only the pieces that would leave the process are replaced: the MCP transport (a
test body runs in its place, as the server would be serving), tool registration,
and the settings check. The connection manager is real, with its clock injected,
so the manager's actual failure and recovery contract reaches the startup code.
"""

from __future__ import annotations

import asyncio
import importlib
import socket
import sys
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock

import pytest
from innerspace_stub import PASSWORD, USERNAME

from unifi_core.innerspace.managers.connection_manager import InnerSpaceConnectionManager
from unifi_core.innerspace.managers.system_manager import InnerSpaceSystemManager
from unifi_innerspace_mcp import main
from unifi_innerspace_mcp.tools import status

SYSTEM_BODY = {
    "apps": {"controllers": [{"name": "innerspace", "isInstalled": True, "isRunning": True, "version": "1.2.3"}]}
}


class Clock:
    """The manager's injectable clock; a test moves it instead of waiting."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def closed_port() -> int:
    """A loopback port nothing listens on, until a test starts the stub on it."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def build_manager(base_url: str, clock: Clock) -> InnerSpaceConnectionManager:
    cm = InnerSpaceConnectionManager("192.0.2.10", USERNAME, PASSWORD, base_url=base_url)
    cm._clock = clock
    return cm


async def startup_connect_finished() -> bool:
    """Wait for the background connect that ``main_async`` starts beside the transports."""
    for task in asyncio.all_tasks():
        if task.get_name() == "innerspace-startup-connect":
            return await task
    raise AssertionError("main_async started no startup connect")


async def run_main(
    monkeypatch,
    cm: InnerSpaceConnectionManager,
    serving: Callable[[], Awaitable[None]],
    *,
    registration: AsyncMock | None = None,
    real_registration: bool = False,
) -> AsyncMock:
    """Run ``main_async`` with ``serving`` as the transport; the status tool reads through ``cm``."""

    async def serve(**_kwargs) -> None:
        await serving()

    transport = AsyncMock(side_effect=serve)
    monkeypatch.setattr(main, "connection_manager", cm)
    monkeypatch.setattr(status, "system_manager", InnerSpaceSystemManager(cm))
    monkeypatch.setattr("unifi_mcp_shared.setup_required.controller_host_configured", lambda *a, **kw: True)
    if not real_registration:
        monkeypatch.setattr("unifi_mcp_shared.tool_registration.register_tools_for_mode", registration or AsyncMock())
    monkeypatch.setattr("unifi_mcp_shared.transport.run_transports", transport)
    monkeypatch.setattr(
        "unifi_mcp_shared.transport.resolve_http_config", lambda *a, **kw: (False, "http", "127.0.0.1", 3005)
    )
    await main.main_async()
    return transport


@pytest.fixture
def fresh_registrations(monkeypatch):
    """Start a registration run from an empty server.

    The server is a process singleton and a tool registers when its module is
    first imported, so a second run in the same process would see the first
    run's tools. This empties the server's tools and the tool index and forgets
    the tool modules, so the run imports them afresh; all of it is restored at
    the end of the test.
    """
    from unifi_innerspace_mcp.runtime import server
    from unifi_innerspace_mcp.tool_index import TOOL_REGISTRY

    package = importlib.import_module("unifi_innerspace_mcp.tools")
    monkeypatch.setattr(server._tool_manager, "_tools", {})
    indexed = dict(TOOL_REGISTRY)
    TOOL_REGISTRY.clear()
    for name in [n for n in sys.modules if n.startswith("unifi_innerspace_mcp.tools.")]:
        module = sys.modules[name]
        monkeypatch.delitem(sys.modules, name)
        monkeypatch.setattr(package, name.rsplit(".", 1)[1], module)
    yield
    TOOL_REGISTRY.clear()
    TOOL_REGISTRY.update(indexed)
