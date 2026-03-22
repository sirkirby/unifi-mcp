"""Forwards tool calls to the correct local MCP server."""

from __future__ import annotations

import json
import logging
from typing import Any

from unifi_mcp_relay.discovery import McpHttpClient, ServerInfo

logger = logging.getLogger("unifi-mcp-relay")


class ToolForwarder:
    """Routes tool calls to the correct local MCP server.

    Maintains persistent MCP HTTP clients per server URL with session ID tracking.
    The routing table maps tool names to server URLs derived from discovery results.
    """

    def __init__(self, server_infos: list[ServerInfo]) -> None:
        self._tool_to_url: dict[str, str] = {}
        self._clients: dict[str, McpHttpClient] = {}
        for info in server_infos:
            for tool in info.tools:
                self._tool_to_url[tool.name] = info.url
            if info.url not in self._clients:
                self._clients[info.url] = McpHttpClient(info.url, session_id=info.session_id)

    def get_server_url(self, tool_name: str) -> str | None:
        """Return the server URL responsible for the given tool, or None if unknown."""
        return self._tool_to_url.get(tool_name)

    async def open(self) -> None:
        """Open HTTP sessions for all managed clients."""
        for client in self._clients.values():
            if hasattr(client, "open"):
                await client.open()

    async def close(self) -> None:
        """Close HTTP sessions for all managed clients."""
        for client in self._clients.values():
            await client.close()

    async def _call(self, server_url: str, tool_name: str, arguments: dict) -> Any:
        """Send a tools/call request to a specific server and parse the response.

        Args:
            server_url: The MCP server base URL.
            tool_name: The tool to invoke.
            arguments: Tool arguments dict.

        Returns:
            Parsed result: JSON-decoded text from content[0] if present, else raw result dict.

        Raises:
            RuntimeError: If no client is registered for the given server URL.
            Exception: Propagates any transport or protocol errors from the client.
        """
        client = self._clients.get(server_url)
        if not client:
            raise RuntimeError(f"No client for {server_url}")
        result = await client.request("tools/call", {"name": tool_name, "arguments": arguments})
        content = result.get("content", [])
        if content and content[0].get("type") == "text":
            return json.loads(content[0]["text"])
        return result

    async def forward(self, tool_name: str, arguments: dict) -> Any | None:
        """Forward a tool call to the correct server.

        Args:
            tool_name: The tool to invoke.
            arguments: Tool arguments dict.

        Returns:
            The tool result, or None if the tool is not known to any server.

        Raises:
            Exception: Propagates any transport or protocol errors from the client.
        """
        url = self.get_server_url(tool_name)
        if not url:
            logger.warning("[forwarder] Unknown tool: %s", tool_name)
            return None
        return await self._call(url, tool_name, arguments)

    async def forward_with_error(self, tool_name: str, arguments: dict) -> Any | str:
        """Forward a tool call, returning an error string on any failure.

        Unlike ``forward()``, this method never raises. Unknown tools and
        transport errors both result in a descriptive error string.

        Args:
            tool_name: The tool to invoke.
            arguments: Tool arguments dict.

        Returns:
            The tool result on success, or an error string on failure.
        """
        url = self.get_server_url(tool_name)
        if not url:
            return f"Unknown tool: {tool_name}"
        try:
            return await self._call(url, tool_name, arguments)
        except Exception as e:
            logger.exception("[forwarder] Failed to forward %s to %s", tool_name, url)
            return str(e)

    def update(self, server_infos: list[ServerInfo]) -> None:
        """Refresh the routing table from a new list of discovered servers.

        Only the tool-to-URL mapping is updated. Existing client sessions are
        preserved; new server URLs will not have pre-created clients.

        Args:
            server_infos: Fresh discovery results.
        """
        self._tool_to_url.clear()
        for info in server_infos:
            for tool in info.tools:
                self._tool_to_url[tool.name] = info.url
