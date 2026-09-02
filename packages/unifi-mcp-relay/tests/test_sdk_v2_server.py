"""Relay interoperability with a real MCP SDK 2.x HTTP server."""

from __future__ import annotations

import asyncio
import socket
from contextlib import asynccontextmanager
from typing import AsyncIterator

import pytest
import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from unifi_mcp_relay.discovery import discover_tools
from unifi_mcp_relay.forwarder import ToolForwarder
from unifi_mcp_shared.protocol import DEFAULT_MCP_PROTOCOL_REVISION


@asynccontextmanager
async def running_sdk_v2_server() -> AsyncIterator[str]:
    mcp_server = MCPServer("relay-sdk-v2-test", version="2.1.1")

    @mcp_server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            openWorldHint=False,
        )
    )
    async def relay_sdk_v2_echo(value: str) -> dict:
        """Echo a value through a structured MCP tool result."""
        return {"success": True, "data": {"value": value}}

    app = mcp_server.streamable_http_app(
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]

    http_server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    task = asyncio.create_task(http_server.serve(sockets=[sock]))
    try:
        for _ in range(100):
            if http_server.started:
                break
            await asyncio.sleep(0.01)
        else:
            raise RuntimeError("SDK v2 test server did not start")
        yield f"http://127.0.0.1:{port}"
    finally:
        http_server.should_exit = True
        await task
        sock.close()


@pytest.mark.asyncio
async def test_relay_discovers_and_forwards_to_sdk_v2_server() -> None:
    async with running_sdk_v2_server() as server_url:
        info = await discover_tools(server_url)

        assert info is not None
        assert info.name == "relay-sdk-v2-test"
        assert info.protocol_version == DEFAULT_MCP_PROTOCOL_REVISION
        assert [tool.name for tool in info.tools] == ["relay_sdk_v2_echo"]
        assert info.tools[0].annotations == {
            "readOnlyHint": True,
            "openWorldHint": False,
        }

        forwarder = ToolForwarder([info])
        try:
            result = await forwarder.forward("relay_sdk_v2_echo", {"value": "ready"})
        finally:
            await forwarder.close()

        assert result == {"success": True, "data": {"value": "ready"}}
