"""The server configures trace export under its own name at startup."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.mark.asyncio
async def test_startup_configures_tracing(monkeypatch):
    from unifi_innerspace_mcp import main

    async def serve(**_kwargs) -> None:
        for task in asyncio.all_tasks():
            if task.get_name() == "innerspace-startup-connect":
                await task

    configure_tracing = Mock(return_value=False)
    monkeypatch.setattr(main.connection_manager, "initialize", AsyncMock(return_value=False))
    monkeypatch.setattr(main.connection_manager, "close", AsyncMock())
    monkeypatch.setattr("unifi_mcp_shared.setup_required.controller_host_configured", lambda *a, **kw: True)
    monkeypatch.setattr("unifi_mcp_shared.tool_registration.register_tools_for_mode", AsyncMock())
    monkeypatch.setattr("unifi_mcp_shared.transport.run_transports", AsyncMock(side_effect=serve))
    monkeypatch.setattr("unifi_mcp_shared.tracing.configure_tracing", configure_tracing)
    await main.main_async()
    configure_tracing.assert_called_once_with("unifi-innerspace-mcp", logger=main.logger)
