"""The server hands the configured HTTP bearer token to the transport."""

import asyncio
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("http_enabled", "expected"),
    [(True, "w" * 40), (False, None)],
)
async def test_http_auth_token_reaches_transport(monkeypatch, http_enabled, expected):
    from unifi_network_mcp import main

    async def serve(**_kwargs) -> None:
        for task in asyncio.all_tasks():
            if task.get_name() == "network-startup-connect":
                await task

    transport = AsyncMock(side_effect=serve)
    monkeypatch.setenv("UNIFI_NETWORK_MCP_HTTP_AUTH_TOKEN", "w" * 40)
    monkeypatch.setattr(main.connection_manager, "initialize", AsyncMock(return_value=False))
    monkeypatch.setattr(main.connection_manager, "cleanup", AsyncMock())
    monkeypatch.setattr(main.event_manager, "stop_listening", AsyncMock())
    monkeypatch.setattr("unifi_mcp_shared.setup_required.controller_host_configured", lambda *a, **kw: True)
    monkeypatch.setattr("unifi_mcp_shared.tool_registration.register_tools_for_mode", AsyncMock())
    monkeypatch.setattr("unifi_mcp_shared.transport.run_transports", transport)
    monkeypatch.setattr(
        "unifi_mcp_shared.transport.resolve_http_config",
        lambda *a, **kw: (http_enabled, "streamable-http", "127.0.0.1", 3000),
    )
    await main.main_async()
    assert transport.await_args.kwargs["auth_token"] == expected
    assert transport.await_args.kwargs["env_prefix"] == "NETWORK"
