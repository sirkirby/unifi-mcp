"""Snapshot tools for the UniFi Drive MCP server. Read-only: no tool takes, locks, restores or deletes a snapshot."""

import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.exceptions import UniFiNotFoundError
from unifi_drive_mcp.runtime import server, snapshot_manager, tool_failure, tool_success

logger = logging.getLogger(__name__)


@server.tool(
    name="drive_get_snapshot_overview",
    description=(
        "Returns every shared and personal drive's snapshot settings and state: snapshot limit and count, "
        "locked and pending-deletion counts, space held, last and next snapshot time, whether snapshots are "
        "paused and why, and the schedule. A drive whose snapshots were never set up is listed with "
        "configured false and a zero limit."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="snapshot",
    permission_action="read",
)
async def drive_get_snapshot_overview() -> Dict[str, Any]:
    """Get every drive's snapshot settings and state."""
    try:
        overview = await snapshot_manager.get_snapshot_overview()
        return tool_success(overview.model_dump(exclude_none=True))
    except Exception as exc:
        return tool_failure("get snapshot overview", exc)


@server.tool(
    name="drive_list_snapshots",
    description=(
        "Lists one shared drive's snapshots (id, name, creation time, locked) by the shared drive's name "
        "from drive_list_shared_drives or drive_get_snapshot_overview. Snapshot IDs are scoped to that "
        "shared drive in the UniFi Drive tool family."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="snapshot",
    permission_action="read",
)
async def drive_list_snapshots(
    shared_drive_name: Annotated[
        str, Field(description="Shared drive name, not its id (from drive_list_shared_drives)")
    ],
) -> Dict[str, Any]:
    """List one shared drive's snapshots."""
    try:
        snapshots = await snapshot_manager.list_snapshots(shared_drive_name)
        return tool_success(
            {
                "snapshots": [snapshot.model_dump(exclude_none=True) for snapshot in snapshots],
                "count": len(snapshots),
            }
        )
    except UniFiNotFoundError as exc:
        return {"success": False, "error": f"Failed to list snapshots: {exc}"}
    except Exception as exc:
        return tool_failure("list snapshots", exc)
