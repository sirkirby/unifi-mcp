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
async def running_sdk_v2_server(
    *, idle_timeout: float | None = None, calls: list[str] | None = None
) -> AsyncIterator[str]:
    mcp_server = MCPServer("relay-sdk-v2-test", version="2.1.1")

    @mcp_server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            openWorldHint=False,
        )
    )
    async def relay_sdk_v2_echo(value: str) -> dict:
        """Echo a value through a structured MCP tool result."""
        if calls is not None:
            calls.append(value)
        return {"success": True, "data": {"value": value}}

    app = mcp_server.streamable_http_app(
        json_response=True,
        session_idle_timeout=idle_timeout,
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


@pytest.mark.asyncio
async def test_relay_recovers_after_sdk_idle_session_expiry() -> None:
    calls: list[str] = []
    async with running_sdk_v2_server(idle_timeout=0.2, calls=calls) as server_url:
        info = await discover_tools(server_url)
        assert info is not None
        assert info.session_id is not None
        forwarder = ToolForwarder([info])
        client = forwarder._clients[server_url]
        try:
            # Let the real SDK reap the discovered legacy session.
            await asyncio.sleep(0.4)
            results = await asyncio.gather(
                *(forwarder.forward("relay_sdk_v2_echo", {"value": str(i)}) for i in range(3))
            )
            assert client.session_id != info.session_id
            assert results == [{"success": True, "data": {"value": str(i)}} for i in range(3)]
            assert sorted(calls) == ["0", "1", "2"]

            # Expiry can recur without reconnecting the relay.
            previous_id = client.session_id
            await asyncio.sleep(0.4)
            assert await forwarder.forward("relay_sdk_v2_echo", {"value": "again"}) == {
                "success": True,
                "data": {"value": "again"},
            }
            assert client.session_id != previous_id
            assert calls.count("again") == 1
        finally:
            await forwarder.close()
