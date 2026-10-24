"""Tests for the shared UniFi MCP server boundary."""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp.types import CallToolResult
from pydantic import BaseModel
from unifi_mcp_shared.server import UniFiMCPServer
from unifi_mcp_shared.strict_dispatch import StrictKwargFastMCP


class StructuredResult(BaseModel):
    success: bool
    data: dict[str, Any]


@pytest.mark.parametrize(("revision", "compacted"), [("2025-11-25", True), ("2025-03-26", False)])
async def test_adaptive_server_compacts_by_protocol_revision(monkeypatch, revision, compacted):
    server = UniFiMCPServer("test", mcp_content_mode="adaptive")
    monkeypatch.setattr("unifi_mcp_shared.server.get_request_protocol_revision", lambda _: revision)

    @server.tool(name="unifi_test", structured_output=True)
    async def unifi_test() -> StructuredResult:
        return StructuredResult(success=True, data={"rows": [{"id": 1}]})

    result = await server.call_tool("unifi_test", {})

    assert isinstance(result, CallToolResult)
    assert result.structured_content == {"success": True, "data": {"rows": [{"id": 1}]}}
    if compacted:
        assert "rows" not in result.content[0].text
    else:
        assert json.loads(result.content[0].text) == {"success": True, "data": {"rows": [{"id": 1}]}}


def test_unifi_server_retains_strict_dispatch_contract():
    assert issubclass(UniFiMCPServer, StrictKwargFastMCP)
