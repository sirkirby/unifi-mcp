"""Server teardown releases the controller after normal and failed startup."""

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "initialize", "registration", "transport"])
async def test_server_always_closes_its_connection(monkeypatch, failure):
    from unifi_access_mcp import main

    initialize = AsyncMock(return_value=False)
    registration = AsyncMock()
    transport = AsyncMock()
    close = AsyncMock()
    stages = {"initialize": initialize, "registration": registration, "transport": transport}
    if failure:
        stages[failure].side_effect = RuntimeError("startup failure")
    monkeypatch.setattr(main.connection_manager, "initialize", initialize)
    monkeypatch.setattr(main.connection_manager, "close", close)
    monkeypatch.setattr("unifi_mcp_shared.setup_required.controller_host_configured", lambda *a, **kw: True)
    monkeypatch.setattr("unifi_mcp_shared.tool_registration.register_tools_for_mode", registration)
    monkeypatch.setattr("unifi_mcp_shared.transport.run_transports", transport)
    monkeypatch.setattr(
        "unifi_mcp_shared.transport.resolve_http_config", lambda *a, **kw: (False, "http", "127.0.0.1", 3000)
    )
    if failure:
        with pytest.raises(RuntimeError, match="startup failure"):
            await main.main_async()
    else:
        await main.main_async()
    close.assert_awaited_once()
