"""The server hands the configured HTTP bearer token and its env prefix to the transport."""

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("http_enabled", "expected"),
    [(True, "w" * 40), (False, None)],
)
async def test_http_auth_token_reaches_transport(monkeypatch, http_enabled, expected):
    from unifi_drive_mcp import main

    transport = AsyncMock()
    monkeypatch.setenv("UNIFI_DRIVE_MCP_HTTP_AUTH_TOKEN", "w" * 40)
    monkeypatch.setattr(main.connection_manager, "close", AsyncMock())
    monkeypatch.setattr("unifi_mcp_shared.setup_required.controller_host_configured", lambda *a, **kw: True)
    monkeypatch.setattr("unifi_mcp_shared.tool_registration.register_tools_for_mode", AsyncMock())
    monkeypatch.setattr("unifi_mcp_shared.transport.run_transports", transport)
    monkeypatch.setattr(
        "unifi_mcp_shared.transport.resolve_http_config",
        lambda *a, **kw: (http_enabled, "streamable-http", "127.0.0.1", 3004),
    )
    await main.main_async()
    assert transport.await_args.kwargs["auth_token"] == expected
    assert transport.await_args.kwargs["env_prefix"] == "DRIVE"
