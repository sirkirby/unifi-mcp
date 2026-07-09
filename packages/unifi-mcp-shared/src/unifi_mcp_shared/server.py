"""Shared UniFi MCP server boundary."""

from __future__ import annotations

from typing import Any

from unifi_mcp_shared.protocol import get_request_protocol_revision
from unifi_mcp_shared.response_policy import MCPContentMode
from unifi_mcp_shared.response_serialization import serialize_call_tool_result
from unifi_mcp_shared.strict_dispatch import StrictKwargFastMCP


class UniFiMCPServer(StrictKwargFastMCP):
    """Apply UniFi response policy after strict FastMCP dispatch."""

    def __init__(
        self,
        *args: Any,
        mcp_content_mode: MCPContentMode = "adaptive",
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._mcp_content_mode = mcp_content_mode

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = await super().call_tool(name, arguments)
        return serialize_call_tool_result(
            result,
            mode=self._mcp_content_mode,
            protocol_revision=get_request_protocol_revision(self),
            tool_name=name,
        )
