"""Tests for shared transport lifecycle management."""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unifi_mcp_shared.transport import resolve_http_config, run_transports


class TestResolveHttpConfig:
    """Tests for resolve_http_config utility."""

    def _make_server_cfg(self, **overrides):
        cfg = {
            "host": "0.0.0.0",
            "port": 3000,
            "http": {"enabled": False, "force": False, "transport": "streamable-http"},
        }
        cfg.update(overrides)
        return MagicMock(**{"get.side_effect": cfg.get})

    def test_http_disabled_by_default(self):
        cfg = self._make_server_cfg()
        enabled, transport, host, port = resolve_http_config(
            cfg, default_port=3000, logger=logging.getLogger("test")
        )
        assert enabled is False

    def test_invalid_transport_falls_back(self):
        cfg = self._make_server_cfg(http={"enabled": True, "force": True, "transport": "bogus"})
        enabled, transport, host, port = resolve_http_config(
            cfg, default_port=3000, logger=logging.getLogger("test")
        )
        assert transport == "streamable-http"


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
    async def test_stdio_only_when_http_disabled(self, mock_server):
        """When HTTP is disabled, only stdio runs."""
        await run_transports(
            server=mock_server,
            http_enabled=False,
            host="0.0.0.0",
            port=3000,
            http_transport="streamable-http",
            logger=logging.getLogger("test"),
        )
        mock_server.run_stdio_async.assert_awaited_once()
        mock_server.run_streamable_http_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pid1_skips_stdio_runs_http_only(self, mock_server):
        """When PID is 1 (Docker container), skip stdio and run HTTP only."""
        with patch("unifi_mcp_shared.transport.os.getpid", return_value=1):
            await run_transports(
                server=mock_server,
                http_enabled=True,
                host="0.0.0.0",
                port=3000,
                http_transport="streamable-http",
                logger=logging.getLogger("test"),
            )
        mock_server.run_stdio_async.assert_not_awaited()
        mock_server.run_streamable_http_async.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pid1_runs_sse_transport(self, mock_server):
        """PID 1 with SSE transport runs SSE, not streamable-http."""
        with patch("unifi_mcp_shared.transport.os.getpid", return_value=1):
            await run_transports(
                server=mock_server,
                http_enabled=True,
                host="0.0.0.0",
                port=3000,
                http_transport="sse",
                logger=logging.getLogger("test"),
            )
        mock_server.run_sse_async.assert_awaited_once()
        mock_server.run_streamable_http_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_pid1_runs_both_transports(self, mock_server):
        """When not PID 1 (local dev with force), both transports start."""
        # Make both return immediately to avoid hanging
        mock_server.run_stdio_async.return_value = None
        mock_server.run_streamable_http_async.return_value = None

        with patch("unifi_mcp_shared.transport.os.getpid", return_value=12345):
            await run_transports(
                server=mock_server,
                http_enabled=True,
                host="0.0.0.0",
                port=3000,
                http_transport="streamable-http",
                logger=logging.getLogger("test"),
            )
        mock_server.run_stdio_async.assert_awaited_once()
        mock_server.run_streamable_http_async.assert_awaited_once()

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
        """Regression for issue #200: HTTP bind failure must not cascade to stdio.

        Previously ``asyncio.wait(FIRST_COMPLETED)`` treated HTTP-died-fast as
        'transport finished' and cancelled stdio — taking down the only
        transport Claude Code talks over.  After the refactor stdio is the
        primary control flow and HTTP failures are contained.
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

        assert stdio_completed, (
            "stdio was cancelled when HTTP failed — the bug from #200 has regressed"
        )
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

        async def long_running_http():
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
