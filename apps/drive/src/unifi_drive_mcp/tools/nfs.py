"""NFS client connection tools for the UniFi Drive MCP server."""

import logging
from typing import Any, Dict

from mcp.types import ToolAnnotations

from unifi_drive_mcp.runtime import file_service_manager, server, tool_failure, tool_success

logger = logging.getLogger(__name__)


@server.tool(
    name="drive_list_nfs_connections",
    description=(
        "Lists the NFS clients allowed to mount shared drives: each client's IP or hostname, the shared "
        "drives it may mount with rw/ro permission and the export path to mount (<nas>:/var/nfs/shared/<name>), "
        "async writes, and any error codes Drive reports. NFS here is NFSv3 and maps every client user to "
        "one Drive user (no squash option)."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="nfs_connection",
    permission_action="read",
)
async def drive_list_nfs_connections() -> Dict[str, Any]:
    """List NFS client connections."""
    try:
        connections = await file_service_manager.list_nfs_connections()
        return tool_success(
            {
                "connections": [connection.model_dump(exclude_none=True) for connection in connections],
                "count": len(connections),
            }
        )
    except Exception as exc:
        return tool_failure("list NFS connections", exc)
