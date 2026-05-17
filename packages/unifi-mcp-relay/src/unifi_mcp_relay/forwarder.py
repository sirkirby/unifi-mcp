"""Forwards tool calls to the correct local MCP server."""

from __future__ import annotations

import json
import logging
from typing import Any

from unifi_mcp_shared.meta_tools import is_meta_tool as _is_meta_tool

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
        self._lazy_load_tool_by_url: dict[str, str] = {}
        self._lazy_advertised_tools_by_url: dict[str, set[str]] = {}
        self._loaded_lazy_tools_by_url: dict[str, set[str]] = {}
        for info in server_infos:
            for tool in info.tools:
                self._tool_to_url[tool.name] = info.url
            if info.lazy_load_tool_name:
                self._lazy_load_tool_by_url[info.url] = info.lazy_load_tool_name
                self._lazy_advertised_tools_by_url[info.url] = {
                    tool.name for tool in info.tools if not _is_meta_tool(tool.name)
                }
                self._loaded_lazy_tools_by_url.setdefault(info.url, set())
            if info.url not in self._clients:
                self._clients[info.url] = McpHttpClient(
                    info.url,
                    session_id=info.session_id,
                    protocol_version=info.protocol_version,
                )

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
        Parsed result: structuredContent when present, JSON-decoded text
        from content[0] if present, else raw result dict.

        Raises:
            RuntimeError: If no client is registered for the given server URL.
            Exception: Propagates any transport or protocol errors from the client.
        """
        client = self._clients.get(server_url)
        if not client:
            raise RuntimeError(f"No client for {server_url}")
        result = await client.request("tools/call", {"name": tool_name, "arguments": arguments})
        return self._parse_tool_result(result, tool_name)

    def _parse_tool_result(self, result: dict, tool_name: str) -> Any:
        """Parse a tools/call result from current or legacy MCP response shapes."""
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        content = result.get("content", [])
        if content and content[0].get("type") == "text":
            raw_text = content[0].get("text", "")
            try:
                return json.loads(raw_text)
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("[forwarder] Failed to parse tool response for %s: %s", tool_name, exc)
                return result
        return result

    async def _ensure_lazy_tool_loaded(self, server_url: str, tool_name: str) -> None:
        """Load a lazy-advertised tool on the backing server before forwarding."""
        load_tool_name = self._lazy_load_tool_by_url.get(server_url)
        if not load_tool_name:
            return
        if tool_name not in self._lazy_advertised_tools_by_url.get(server_url, set()):
            return
        loaded_tools = self._loaded_lazy_tools_by_url.setdefault(server_url, set())
        if tool_name in loaded_tools:
            return

        result = await self._call(server_url, load_tool_name, {"tools": [tool_name]})
        if isinstance(result, dict) and tool_name in result.get("loaded", []):
            loaded_tools.add(tool_name)
            return

        raise RuntimeError(f"Failed to load lazy tool {tool_name} via {load_tool_name}: {result}")

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
        await self._ensure_lazy_tool_loaded(url, tool_name)
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
            await self._ensure_lazy_tool_loaded(url, tool_name)
            return await self._call(url, tool_name, arguments)
        except Exception as e:
            logger.exception("[forwarder] Failed to forward %s to %s", tool_name, url)
            return str(e)
