"""Lightweight synchronous MCP HTTP client for skill scripts.

Connects to MCP servers via Streamable HTTP transport,
calls tools by name, and returns parsed JSON results.
All tool calls go through the MCP permission system.

Zero external dependencies — uses only Python stdlib.
"""
import json
import logging
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)

JSONRPC_VERSION = "2.0"
MCP_CONTENT_TYPE = "application/json"


class MCPConnectionError(Exception):
    """Raised when the MCP server is unreachable."""


class MCPToolError(Exception):
    """Raised when a tool call returns an error."""


class MCPClient:
    """Synchronous HTTP client for calling MCP tools.

    Usage:
        client = MCPClient("http://localhost:3000")
        result = client.call_tool("unifi_list_devices", {})
    """

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call a single MCP tool and return the parsed result."""
        payload = {
            "jsonrpc": JSONRPC_VERSION,
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments or {}},
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/mcp",
            data=body,
            headers={"Content-Type": MCP_CONTENT_TYPE, "Accept": MCP_CONTENT_TYPE},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.URLError as e:
            raise MCPConnectionError(
                f"Cannot connect to MCP server at {self.base_url}. "
                f"Is the server running with HTTP enabled? Error: {e}"
            ) from e
        except urllib.error.HTTPError as e:
            raise MCPToolError(f"HTTP error calling {tool_name}: {e.code}") from e

        data = json.loads(raw)
        if "error" in data:
            raise MCPToolError(f"Tool {tool_name} error: {data['error']}")

        result = data.get("result", {})
        content = result.get("content", [])
        for item in content:
            if item.get("type") == "text":
                try:
                    return json.loads(item["text"])
                except json.JSONDecodeError:
                    return {"success": True, "data": item["text"]}
        return {"success": True, "data": result}

    def call_tools_parallel(self, calls: list[tuple[str, dict[str, Any] | None]]) -> list[dict[str, Any]]:
        """Call multiple MCP tools in parallel using threads."""
        with ThreadPoolExecutor(max_workers=len(calls) or 1) as pool:
            results = list(pool.map(lambda c: self.call_tool(c[0], c[1]), calls))
        return results

    def check_ready(self, tool_index_name: str = "unifi_tool_index") -> bool:
        """Check if the MCP server is reachable and has tools available."""
        try:
            result = self.call_tool(tool_index_name, {})
            return result.get("success", False)
        except (MCPConnectionError, MCPToolError):
            return False

    def get_setup_error(self) -> dict[str, Any]:
        """Return a structured setup_required error for JSON output."""
        return {
            "success": False,
            "error": "setup_required",
            "message": (
                f"MCP server not reachable at {self.base_url}. "
                "Run the /setup skill for this plugin first, or set the "
                "UNIFI_*_MCP_URL environment variable."
            ),
        }
