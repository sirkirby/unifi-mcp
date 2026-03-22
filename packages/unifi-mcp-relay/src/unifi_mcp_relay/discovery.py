"""MCP protocol tool discovery for local MCP servers.

Connects to local MCP servers via Streamable HTTP transport, runs the
MCP initialization handshake, discovers available tools, and builds a
tool catalog for relay registration.

Discovery strategy:
1. Initialize MCP session (initialize request + initialized notification)
2. List tools via tools/list
3. If a ``*_tool_index`` meta-tool is found (lazy mode), call it to get the
   full catalog with annotations and schemas
4. Otherwise, fall back to using tools/list results directly (eager mode)
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

import aiohttp

from unifi_mcp_relay.protocol import ToolInfo

logger = logging.getLogger("unifi-mcp-relay")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ServerInfo:
    """Discovered server metadata and tool catalog."""

    name: str
    url: str
    session_id: str | None = None
    tools: list[ToolInfo] = field(default_factory=list)


# ---------------------------------------------------------------------------
# MCP HTTP Client
# ---------------------------------------------------------------------------


class McpHttpClient:
    """Persistent aiohttp session for a single MCP server.

    Tracks the ``Mcp-Session-Id`` header across requests as required by
    the MCP Streamable HTTP transport spec.
    """

    def __init__(self, server_url: str, session_id: str | None = None) -> None:
        self._base_url = server_url.rstrip("/") + "/mcp"
        self._session: aiohttp.ClientSession | None = None
        self._session_id: str | None = session_id
        self._request_id: int = 0

    @property
    def session_id(self) -> str | None:
        return self._session_id

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def request(self, method: str, params: dict | None = None) -> dict:
        """Send a JSON-RPC request to the MCP server.

        Args:
            method: JSON-RPC method name (e.g., "initialize", "tools/list").
            params: Optional parameters dict.

        Returns:
            The ``result`` field from the JSON-RPC response.

        Raises:
            RuntimeError: If the server returns a JSON-RPC error.
            aiohttp.ClientError: On transport-level failures.
        """
        session = await self._ensure_session()
        self._request_id += 1

        payload: dict = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        async with session.post(self._base_url, json=payload, headers=headers) as resp:
            # Capture session ID from response
            if "mcp-session-id" in resp.headers:
                self._session_id = resp.headers["mcp-session-id"]

            resp.raise_for_status()
            data = await resp.json()

        if "error" in data:
            raise RuntimeError(f"MCP error: {data['error']}")

        return data.get("result", {})

    async def notify(self, method: str, params: dict | None = None) -> None:
        """Send a JSON-RPC notification (no id, no response expected)."""
        session = await self._ensure_session()

        payload: dict = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        async with session.post(self._base_url, json=payload, headers=headers) as resp:
            if "mcp-session-id" in resp.headers:
                self._session_id = resp.headers["mcp-session-id"]

    async def close(self) -> None:
        """Close the underlying aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def _extract_annotations(tool_data: dict) -> dict | None:
    """Extract MCP ToolAnnotations from a tools/list entry (eager mode fallback)."""
    annotations = tool_data.get("annotations")
    if annotations and isinstance(annotations, dict):
        return annotations
    return None


def _build_tools_from_index(index_result: dict, server_name: str) -> list[ToolInfo]:
    """Build ToolInfo list from a tool_index response."""
    tools = []
    for entry in index_result.get("tools", []):
        # tool_index returns schema as {"input": ...}, we want just the input schema
        schema = entry.get("schema", {})
        input_schema = schema.get("input") if isinstance(schema, dict) else None

        tools.append(
            ToolInfo(
                name=entry["name"],
                description=entry.get("description", ""),
                input_schema=input_schema,
                annotations=entry.get("annotations"),
                server_origin=server_name,
            )
        )
    return tools


def _build_tools_from_list(tools_list: list[dict], server_name: str) -> list[ToolInfo]:
    """Build ToolInfo list from tools/list response (eager mode fallback)."""
    tools = []
    for entry in tools_list:
        tools.append(
            ToolInfo(
                name=entry["name"],
                description=entry.get("description", ""),
                input_schema=entry.get("inputSchema"),
                annotations=_extract_annotations(entry),
                server_origin=server_name,
            )
        )
    return tools


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def discover_tools(server_url: str) -> ServerInfo | None:
    """Discover tools from a single MCP server using the MCP protocol.

    Performs the full MCP handshake:
    1. ``initialize`` — establish session, learn server capabilities
    2. ``tools/list`` — get registered tools (may be meta-tools only in lazy mode)
    3. If a ``*_tool_index`` tool is found, call it for the full catalog

    Args:
        server_url: Base URL of the MCP server (e.g., ``http://localhost:3000``).

    Returns:
        ServerInfo with discovered tools, or None on failure.
    """
    client = McpHttpClient(server_url)
    try:
        # Step 1: Initialize
        init_result = await client.request(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "unifi-mcp-relay", "version": "1.0.0"},
            },
        )

        server_name = init_result.get("serverInfo", {}).get("name", "unknown")

        # Send initialized notification
        try:
            await client.notify("notifications/initialized")
        except Exception:
            # Not all transports handle notifications; continue anyway
            pass

        # Step 2: List tools
        list_result = await client.request("tools/list")
        listed_tools = list_result.get("tools", [])

        # Step 3: Look for a *_tool_index meta-tool (suffix match)
        tool_index_name = None
        for tool in listed_tools:
            if tool.get("name", "").endswith("_tool_index"):
                tool_index_name = tool["name"]
                break

        if tool_index_name:
            # Lazy mode: call the tool_index for the full catalog
            logger.info("[discovery] Found tool index '%s' on %s, fetching full catalog", tool_index_name, server_name)
            call_result = await client.request("tools/call", {"name": tool_index_name, "arguments": {}})

            # Parse the tool_index response (content[0].text is JSON)
            content = call_result.get("content", [])
            if content and content[0].get("type") == "text":
                index_data = json.loads(content[0]["text"])
                tools = _build_tools_from_index(index_data, server_name)
            else:
                logger.warning("[discovery] Unexpected tool_index response from %s", server_name)
                tools = _build_tools_from_list(listed_tools, server_name)
        else:
            # Eager mode fallback: use tools/list directly
            logger.info("[discovery] No tool_index found on %s, using tools/list directly", server_name)
            tools = _build_tools_from_list(listed_tools, server_name)

        info = ServerInfo(
            name=server_name,
            url=server_url,
            session_id=client.session_id,
            tools=tools,
        )
        logger.info("[discovery] Discovered %d tools from %s (%s)", len(tools), server_name, server_url)
        return info

    except Exception as e:
        logger.error("[discovery] Failed to discover tools from %s: %s", server_url, e, exc_info=True)
        return None
    finally:
        await client.close()


async def discover_all(server_urls: list[str]) -> list[ServerInfo]:
    """Discover tools from multiple MCP servers concurrently.

    Args:
        server_urls: List of MCP server base URLs.

    Returns:
        List of successfully discovered ServerInfo objects.
        Failed discoveries are logged and excluded.
    """
    results = await asyncio.gather(
        *(discover_tools(url) for url in server_urls),
        return_exceptions=True,
    )

    servers: list[ServerInfo] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error("[discovery] Server %s failed: %s", server_urls[i], result)
        elif result is not None:
            servers.append(result)
        else:
            logger.warning("[discovery] Server %s returned no results", server_urls[i])

    logger.info("[discovery] Discovered %d/%d servers successfully", len(servers), len(server_urls))
    return servers
