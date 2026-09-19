"""Compatibility contract for MCP SDK 2.x modern and handshake-era clients."""

from __future__ import annotations

import httpx
import pytest
from mcp.client import Client
from mcp.server.mcpserver import Context
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel
from unifi_mcp_shared.server import UniFiMCPServer, resolve_allowed_hosts


class NegotiatedResult(BaseModel):
    success: bool
    protocol_version: str


def test_allowed_hosts_default_to_loopback() -> None:
    assert resolve_allowed_hosts(None) == ["localhost", "127.0.0.1"]


def test_allowed_hosts_union_operator_and_internal_values_without_duplicates() -> None:
    assert resolve_allowed_hosts(
        "localhost, proxy.example.com,localhost",
        internal_hosts="unifi-network-mcp,proxy.example.com",
    ) == ["localhost", "proxy.example.com", "unifi-network-mcp"]


def test_deployment_override_replaces_operator_hosts_before_internal_union() -> None:
    assert resolve_allowed_hosts(
        "env-file.example.com",
        override_hosts="shell.example.com",
        internal_hosts="unifi-network-mcp",
    ) == ["shell.example.com", "unifi-network-mcp"]


def test_explicit_empty_override_clears_env_file_hosts() -> None:
    assert resolve_allowed_hosts(
        "env-file.example.com",
        override_hosts="",
        internal_hosts="unifi-network-mcp",
    ) == ["unifi-network-mcp"]


def test_explicit_empty_operator_allowlist_does_not_restore_defaults() -> None:
    assert resolve_allowed_hosts("", internal_hosts="unifi-network-mcp") == ["unifi-network-mcp"]


@pytest.mark.parametrize(
    ("mode", "expected_revision"),
    [("auto", "2026-07-28"), ("legacy", "2025-11-25")],
)
async def test_one_server_supports_modern_and_legacy_clients(mode: str, expected_revision: str) -> None:
    server = UniFiMCPServer("compatibility-test", version="1.0.0")

    @server.tool(
        name="negotiated_tool",
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
        structured_output=True,
    )
    async def negotiated_tool(ctx: Context) -> NegotiatedResult:
        return NegotiatedResult(
            success=True,
            protocol_version=ctx.request_context.protocol_version,
        )

    async with Client(server, mode=mode) as client:
        assert client.protocol_version == expected_revision

        listed = await client.list_tools()
        tool = next(item for item in listed.tools if item.name == "negotiated_tool")
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.open_world_hint is False
        assert tool.input_schema["type"] == "object"

        result = await client.call_tool("negotiated_tool", {})

    assert result.is_error is False
    assert result.structured_content == {
        "success": True,
        "protocol_version": expected_revision,
    }


async def test_bare_allowed_hosts_accept_real_host_headers_with_ports() -> None:
    server = UniFiMCPServer(
        "host-pattern-test",
        transport_security=TransportSecuritySettings(
            allowed_hosts=["localhost", "127.0.0.1", "[::1]"],
        ),
    )
    assert server.transport_security is not None
    assert server.transport_security.allowed_hosts == ["localhost:*", "127.0.0.1:*", "[::1]:*"]

    app = server.streamable_http_app(
        transport_security=server.transport_security,
        host="127.0.0.1",
    )
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:34567",
        ) as client:
            response = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {}},
                headers={
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": "2026-07-28",
                },
            )

    # The deliberately incomplete discover envelope is rejected after host
    # validation. SDK v2 returned 421 here before bare hosts were normalized.
    assert response.status_code == 400
