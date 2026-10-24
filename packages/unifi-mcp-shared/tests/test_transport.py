"""Tests for shared transport lifecycle management."""

import asyncio
import logging
import socket
from contextlib import suppress
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import uvicorn
from mcp.client import Client
from mcp.client.sse import sse_client
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel
from unifi_mcp_shared.server import UniFiMCPServer
from unifi_mcp_shared.transport import resolve_http_config, run_transports


class SSEEchoData(BaseModel):
    value: str


class SSEEchoResult(BaseModel):
    success: bool
    data: SSEEchoData


class TestResolveHttpConfig:
    """Tests for resolve_http_config utility."""

    @pytest.mark.parametrize(
        ("overrides", "expected_enabled", "expected_transport", "expected_host"),
        [
            (None, False, "streamable-http", "127.0.0.1"),
            ({}, False, "streamable-http", "0.0.0.0"),
            ({"http": {"enabled": True, "force": True, "transport": "bogus"}}, True, "streamable-http", "0.0.0.0"),
        ],
    )
    def test_resolve_http_config(self, overrides, expected_enabled, expected_transport, expected_host):
        if overrides is None:
            cfg = {}
        else:
            raw = {
                "host": "0.0.0.0",
                "port": 3000,
                "http": {"enabled": False, "force": False, "transport": "streamable-http"},
                **overrides,
            }
            cfg = MagicMock(**{"get.side_effect": raw.get})
        enabled, transport, host, _ = resolve_http_config(cfg, default_port=3000, logger=logging.getLogger("test"))
        assert enabled is expected_enabled
        assert transport == expected_transport
        assert host == expected_host


class TestRunTransports:
    """Tests for transport lifecycle coupling."""

    @pytest.fixture()
    def mock_server(self):
        server = MagicMock()
        server.run_stdio_async = AsyncMock()
        server.run_streamable_http_async = AsyncMock()
        server.run_sse_async = AsyncMock()
        server.settings = MagicMock()
        return server

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("pid", "http_enabled", "http_transport", "expected_stdio", "expected_http", "expected_sse"),
        [
            (12345, False, "streamable-http", 1, 0, 0),
            (1, True, "streamable-http", 0, 1, 0),
            (1, True, "sse", 0, 0, 1),
            (12345, True, "streamable-http", 1, 1, 0),
        ],
    )
    async def test_run_transports_dispatch(
        self, mock_server, pid, http_enabled, http_transport, expected_stdio, expected_http, expected_sse
    ):
        with patch("unifi_mcp_shared.transport.os.getpid", return_value=pid):
            await run_transports(
                server=mock_server,
                http_enabled=http_enabled,
                host="0.0.0.0",
                port=3000,
                http_transport=http_transport,
                logger=logging.getLogger("test"),
            )
        assert mock_server.run_stdio_async.await_count == expected_stdio
        assert mock_server.run_streamable_http_async.await_count == expected_http
        assert mock_server.run_sse_async.await_count == expected_sse

    @pytest.mark.asyncio
    async def test_pid1_http_error_logged_not_raised(self, mock_server, caplog):
        """HTTP errors are logged but don't crash in PID 1 mode (matches dual-transport behaviour)."""
        mock_server.run_streamable_http_async.side_effect = RuntimeError("bind failed")

        with patch("unifi_mcp_shared.transport.os.getpid", return_value=1):
            # Should not raise — run_http catches the exception internally
            await run_transports(
                server=mock_server,
                http_enabled=True,
                host="0.0.0.0",
                port=3000,
                http_transport="streamable-http",
                logger=logging.getLogger("test"),
            )
        assert "bind failed" in caplog.text

    @pytest.mark.asyncio
    async def test_http_systemexit_does_not_cancel_stdio(self, mock_server):
        """HTTP bind failure must not cascade to stdio.

        Stdio is the primary control flow; HTTP failures are contained inside
        ``run_http`` so the only transport Claude Code talks over keeps serving.
        """
        mock_server.run_streamable_http_async.side_effect = SystemExit(1)

        stdio_completed = False

        async def stdio_runs_for_a_moment():
            nonlocal stdio_completed
            await asyncio.sleep(0.05)
            stdio_completed = True

        mock_server.run_stdio_async.side_effect = stdio_runs_for_a_moment

        with patch("unifi_mcp_shared.transport.os.getpid", return_value=12345):
            await run_transports(
                server=mock_server,
                http_enabled=True,
                host="0.0.0.0",
                port=3000,
                http_transport="streamable-http",
                logger=logging.getLogger("test"),
            )

        assert stdio_completed, "stdio was cancelled when HTTP failed — HTTP failure cascade regressed"
        mock_server.run_streamable_http_async.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stdio_exit_cancels_http(self, mock_server):
        """When stdio exits (client disconnect), HTTP must be cancelled.

        Without this, the HTTP server would keep the process alive as an
        orphan after the stdio client disconnected.
        """
        # stdio returns immediately (simulates client disconnect at startup).
        mock_server.run_stdio_async.return_value = None

        http_started = asyncio.Event()
        http_was_cancelled = False

        async def long_running_http(**_kwargs):
            nonlocal http_was_cancelled
            http_started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                http_was_cancelled = True
                raise

        mock_server.run_streamable_http_async.side_effect = long_running_http

        with patch("unifi_mcp_shared.transport.os.getpid", return_value=12345):
            # Should complete promptly: stdio exits, then http_task is cancelled.
            await asyncio.wait_for(
                run_transports(
                    server=mock_server,
                    http_enabled=True,
                    host="0.0.0.0",
                    port=3000,
                    http_transport="streamable-http",
                    logger=logging.getLogger("test"),
                ),
                timeout=2.0,
            )

        assert http_started.is_set(), "HTTP transport never started"
        assert http_was_cancelled, "HTTP transport was not cancelled when stdio exited"


@pytest.mark.asyncio
async def test_real_sdk_v2_sse_transport_completes_handshake() -> None:
    """Exercise the production SSE branch against the SDK's real client."""
    server = UniFiMCPServer(
        "sse-transport-test",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @server.tool(
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
        structured_output=True,
    )
    async def sse_echo(value: str) -> SSEEchoResult:
        return SSEEchoResult(success=True, data=SSEEchoData(value=value))

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    real_uvicorn_server = uvicorn.Server
    http_server: uvicorn.Server | None = None

    def capture_uvicorn_server(config: uvicorn.Config) -> uvicorn.Server:
        nonlocal http_server
        http_server = real_uvicorn_server(config)
        return http_server

    with (
        patch("unifi_mcp_shared.transport.os.getpid", return_value=1),
        patch("uvicorn.Server", side_effect=capture_uvicorn_server),
    ):
        transport_task = asyncio.create_task(
            run_transports(
                server=server,
                http_enabled=True,
                host="127.0.0.1",
                port=port,
                http_transport="sse",
                logger=logging.getLogger("test"),
            )
        )
        try:
            for _ in range(100):
                try:
                    reader, writer = await asyncio.open_connection("127.0.0.1", port)
                except OSError:
                    await asyncio.sleep(0.01)
                    continue
                writer.close()
                await writer.wait_closed()
                del reader
                break
            else:
                raise RuntimeError("SDK v2 SSE test server did not start")

            async with Client(sse_client(f"http://127.0.0.1:{port}/sse")) as client:
                assert client.protocol_version == "2026-07-28"
                listed = await client.list_tools()
                assert [tool.name for tool in listed.tools] == ["sse_echo"]
                result = await client.call_tool("sse_echo", {"value": "ready"})
                assert result.structured_content == {
                    "success": True,
                    "data": {"value": "ready"},
                }
        finally:
            if http_server is not None:
                http_server.should_exit = True
            try:
                await asyncio.wait_for(transport_task, timeout=3.0)
            except TimeoutError:
                transport_task.cancel()
                with suppress(asyncio.CancelledError):
                    await transport_task
