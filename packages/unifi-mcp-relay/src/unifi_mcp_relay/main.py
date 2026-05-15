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


class DiscoveryNotReadyError(RuntimeError):
    """Raised when configured local MCP servers are not ready for relay registration."""


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
        if len(servers) != len(self._config.servers):
            raise DiscoveryNotReadyError(
                f"discovered {len(servers)}/{len(self._config.servers)} configured local MCP server(s)"
            )

        catalog: list[ToolInfo] = []
        for info in servers:
            catalog.extend(info.tools)
        if not catalog:
            raise DiscoveryNotReadyError("configured local MCP servers returned an empty tool catalog")

        forwarder = ToolForwarder(servers)
        await forwarder.open()

        # Close old forwarder only after the replacement is ready, so a
        # transient discovery failure cannot drop an active catalog.
        if self._forwarder is not None:
            try:
                await self._forwarder.close()
            except Exception as exc:
                logger.warning("[main] Error closing old forwarder: %s", exc)

        self._forwarder = forwarder

        self._catalog = catalog
        logger.info("[main] Built catalog with %d tools from %d server(s)", len(catalog), len(servers))
        return catalog

    async def _wait_for_startup_catalog(self) -> list[ToolInfo]:
        """Wait until all configured local servers are ready before registering with the relay."""
        delay = min(5, max(1, self._config.reconnect_max_delay))
        attempt = 0
        while self._running:
            attempt += 1
            try:
                return await self._discover_catalog()
            except DiscoveryNotReadyError as exc:
                logger.warning(
                    "[main] Local MCP servers not ready for relay registration (attempt %d): %s; retrying in %ds",
                    attempt,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
            except Exception as exc:
                logger.error(
                    "[main] Startup discovery failed before relay registration (attempt %d): %s; retrying in %ds",
                    attempt,
                    exc,
                    delay,
                    exc_info=True,
                )
                await asyncio.sleep(delay)
        raise asyncio.CancelledError

    async def _handle_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> tuple[Any | None, str | None]:
        """Delegate a tool call to the forwarder, or handle relay-native tools.

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
            except DiscoveryNotReadyError as exc:
                logger.warning(
                    "[main] Refresh skipped; keeping existing catalog because discovery is not ready: %s",
                    exc,
                )
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
            catalog = await self._wait_for_startup_catalog()

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
