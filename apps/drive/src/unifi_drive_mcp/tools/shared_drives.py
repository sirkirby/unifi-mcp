"""Shared drive tools for the UniFi Drive MCP server. Read-only."""

import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.exceptions import UniFiNotFoundError
from unifi_drive_mcp.runtime import server, shared_drive_manager, tool_failure, tool_success

logger = logging.getLogger(__name__)


@server.tool(
    name="drive_list_shared_drives",
    description=(
        "Lists shared drives with their storage pool, usage, quota, status, encryption, snapshot and "
        "remote-backup flags. These IDs are scoped to the UniFi Drive tool family; pass them as "
        "shared_drives[].id to the drive_*_nfs_connection tools, not to other products' tools."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="shared_drive",
    permission_action="read",
)
async def drive_list_shared_drives() -> Dict[str, Any]:
    """List shared drives."""
    try:
        drives = await shared_drive_manager.list_shared_drives()
        return tool_success({"drives": [drive.model_dump(exclude_none=True) for drive in drives], "count": len(drives)})
    except Exception as exc:
        return tool_failure("list shared drives", exc)


@server.tool(
    name="drive_get_shared_drive",
    description=(
        "Returns one shared drive by ID (from drive_list_shared_drives). This endpoint omits the "
        "protection flags and member count that the list includes."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="shared_drive",
    permission_action="read",
)
async def drive_get_shared_drive(
    drive_id: Annotated[str, Field(description="Shared drive ID (from drive_list_shared_drives)")],
) -> Dict[str, Any]:
    """Get one shared drive."""
    try:
        drive = await shared_drive_manager.get_shared_drive(drive_id)
        return tool_success(drive.model_dump(exclude_none=True))
    except UniFiNotFoundError as exc:
        return {"success": False, "error": f"Failed to get shared drive: {exc}"}
    except Exception as exc:
        return tool_failure("get shared drive", exc)
