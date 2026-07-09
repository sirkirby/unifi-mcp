"""Tests for the shared UniFi MCP server boundary."""

from __future__ import annotations

from typing import Any

from mcp.types import CallToolResult
from pydantic import BaseModel
from unifi_mcp_shared.server import UniFiMCPServer
from unifi_mcp_shared.strict_dispatch import StrictKwargFastMCP


class StructuredResult(BaseModel):
    success: bool
    data: dict[str, Any]


async def test_adaptive_server_compacts_supported_client(monkeypatch):
    server = UniFiMCPServer("test", mcp_content_mode="adaptive")
    monkeypatch.setattr("unifi_mcp_shared.server.get_request_protocol_revision", lambda _: "2025-11-25")

    @server.tool(name="unifi_test", structured_output=True)
    async def unifi_test() -> StructuredResult:
        return StructuredResult(success=True, data={"rows": [{"id": 1}]})

    result = await server.call_tool("unifi_test", {})

    assert isinstance(result, CallToolResult)
    assert result.structuredContent == {"success": True, "data": {"rows": [{"id": 1}]}}
    assert result.content
    assert "rows" not in result.content[0].text


async def test_adaptive_server_preserves_old_client(monkeypatch):
    server = UniFiMCPServer("test", mcp_content_mode="adaptive")
    monkeypatch.setattr("unifi_mcp_shared.server.get_request_protocol_revision", lambda _: "2025-03-26")

    @server.tool(name="unifi_test", structured_output=True)
    async def unifi_test() -> StructuredResult:
        return StructuredResult(success=True, data={})

    result = await server.call_tool("unifi_test", {})

    assert isinstance(result, tuple)


def test_unifi_server_retains_strict_dispatch_contract():
    assert issubclass(UniFiMCPServer, StrictKwargFastMCP)
