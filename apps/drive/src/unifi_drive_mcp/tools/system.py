"""System tools for the UniFi Drive MCP server."""

import logging
from typing import Any, Dict

from mcp.types import ToolAnnotations

from unifi_drive_mcp.runtime import server, system_manager, tool_failure, tool_success

logger = logging.getLogger(__name__)


@server.tool(
    name="drive_get_system_info",
    description=(
        "Returns the NAS console's identity and health: name, model (e.g. UNASPRO8), MAC, UniFi OS firmware "
        "version and any available update, device state, uptime, CPU load and temperature, and memory."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="system",
    permission_action="read",
)
async def drive_get_system_info() -> Dict[str, Any]:
    """Get system information for the UniFi Drive console."""
    try:
        info = await system_manager.get_system_info()
        return tool_success(info.model_dump(exclude_none=True))
    except Exception as exc:
        return tool_failure("get system info", exc)
