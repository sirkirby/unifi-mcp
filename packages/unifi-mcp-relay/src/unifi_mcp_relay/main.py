"""Main orchestrator for the UniFi MCP Relay.

Coordinates discovery, forwarding, and the relay client lifecycle.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from unifi_mcp_relay.client import RelayClient
from unifi_mcp_relay.config import RelayConfig
from unifi_mcp_relay.discovery import ServerInfo, discover_all
from unifi_mcp_relay.forwarder import ToolForwarder
from unifi_mcp_relay.protocol import ToolInfo

logger = logging.getLogger("unifi-mcp-relay")


class RelaySidecar:
    """Top-level orchestrator that wires discovery, forwarding, and the relay client together."""

    def __init__(self, config: RelayConfig) -> None:
        self._config = config
        self._client = RelayClient(config)
        self._forwarder: ToolForwarder | None = None
        self._catalog: list[ToolInfo] = []
        self._refresh_task: asyncio.Task | None = None
        self._running: bool = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _discover_catalog(self) -> list[ToolInfo]:
        """Run discovery against all configured servers and build a flat tool list.

        Creates a new ToolForwarder, opens its HTTP sessions, and returns the
        flat list of ToolInfo objects discovered across all servers.
        """
        servers: list[ServerInfo] = await discover_all(self._config.servers)

        # Close old forwarder before replacing
        if self._forwarder is not None:
            try:
                await self._forwarder.close()
            except Exception as exc:
                logger.debug("[main] Error closing old forwarder: %s", exc)

        forwarder = ToolForwarder(servers)
        await forwarder.open()
        self._forwarder = forwarder

        catalog: list[ToolInfo] = []
        for info in servers:
            catalog.extend(info.tools)

        self._catalog = catalog
        logger.info("[main] Built catalog with %d tools from %d server(s)", len(catalog), len(servers))
        return catalog

    async def _handle_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> tuple[Any | None, str | None]:
        """Delegate a tool call to the forwarder.

        Returns:
            ``(result, None)`` on success, ``(None, error_string)`` on failure.
        """
        if self._forwarder is None:
            return None, "Forwarder not initialized"

        outcome = await self._forwarder.forward_with_error(tool_name, arguments)
        if isinstance(outcome, str):
            # forward_with_error returns a string on error
            return None, outcome
        return outcome, None

    async def _refresh_loop(self) -> None:
        """Periodically re-discover the tool catalog and push updates to the worker."""
        while self._running:
            await asyncio.sleep(self._config.refresh_interval)
            if not self._running:
                break

            logger.info("[main] Refresh: re-discovering tool catalog...")
            try:
                old_names = {t.name for t in self._catalog}  # Save BEFORE refresh
                await self._discover_catalog()
                new_names = {t.name for t in self._catalog}  # Compare AFTER refresh

                if old_names != new_names:
                    sent = await self._client.send_catalog_update(self._catalog)
                    if sent:
                        logger.info("[main] Sent catalog_update with %d tools", len(self._catalog))
                    else:
                        logger.warning("[main] Could not send catalog_update: client not connected")
                else:
                    logger.debug("[main] Catalog unchanged after refresh")
            except Exception as exc:
                logger.error("[main] Refresh failed: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main lifecycle: discover → start refresh task → run client.

        Cleans up all resources on exit.
        """
        self._running = True

        try:
            catalog = await self._discover_catalog()

            self._refresh_task = asyncio.create_task(self._refresh_loop())

            await self._client.run(
                tools=catalog,
                tool_call_handler=self._handle_tool_call,
            )
        finally:
            self._running = False

            if self._refresh_task is not None and not self._refresh_task.done():
                self._refresh_task.cancel()
                try:
                    await self._refresh_task
                except asyncio.CancelledError:
                    pass
                self._refresh_task = None

            if self._forwarder is not None:
                try:
                    await self._forwarder.close()
                except Exception as exc:
                    logger.debug("[main] Error closing forwarder during shutdown: %s", exc)
                self._forwarder = None

            logger.info("[main] Shutdown complete")

    async def stop(self) -> None:
        """Graceful shutdown: stop the refresh loop and the relay client."""
        self._running = False
        await self._client.stop()
