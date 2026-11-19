"""File service tools for the UniFi Drive MCP server: SMB, NFS and Time Machine status."""

import logging
from typing import Any, Dict

from mcp.types import ToolAnnotations

from unifi_drive_mcp.runtime import file_service_manager, server, tool_failure, tool_success

logger = logging.getLogger(__name__)


@server.tool(
    name="drive_get_file_services",
    description=(
        "Returns whether SMB, NFS and Time Machine are enabled on the NAS, and the network interfaces "
        "(address, link speed) clients connect to."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="file_service",
    permission_action="read",
)
async def drive_get_file_services() -> Dict[str, Any]:
    """Get file service status."""
    try:
        services = await file_service_manager.get_file_services()
        return tool_success(services.model_dump(exclude_none=True))
    except Exception as exc:
        return tool_failure("get file services", exc)
