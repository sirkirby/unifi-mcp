"""Storage tools for the UniFi Drive MCP server: pools, RAID groups, disks and pool usage. Read-only."""

import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_drive_mcp.runtime import server, storage_manager, tool_failure, tool_success

logger = logging.getLogger(__name__)


@server.tool(
    name="drive_list_storage_pools",
    description=(
        "Lists storage pools with capacity, usage and status, and each pool's RAID groups: the RAID level in "
        "effect (current_level) versus the configured one (config_level), current and expected disk-failure "
        "protection, and rebuild or expansion progress. A pool with status noDataProtectionYet has no "
        "redundancy yet. Storage pool IDs are scoped to the UniFi Drive tool family; do not pass them to "
        "other products' storage tools."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="storage",
    permission_action="read",
)
async def drive_list_storage_pools() -> Dict[str, Any]:
    """List storage pools and their RAID groups."""
    try:
        pools = await storage_manager.list_pools()
        return tool_success({"pools": [pool.model_dump(exclude_none=True) for pool in pools], "count": len(pools)})
    except Exception as exc:
        return tool_failure("list storage pools", exc)


@server.tool(
    name="drive_list_disks",
    description=(
        "Lists the NAS's drive bays and SSD cache slots with the disk in each, its pool membership and "
        "SMART health. Empty bays are left out unless include_empty is true."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="storage",
    permission_action="read",
)
async def drive_list_disks(
    include_empty: Annotated[bool, Field(description="Also list empty bays and slots (default false)")] = False,
    include_cache: Annotated[bool, Field(description="Include SSD cache slots (default true)")] = True,
) -> Dict[str, Any]:
    """List disks and their SMART health."""
    try:
        disks = await storage_manager.list_disks(include_empty=include_empty, include_cache=include_cache)
        return tool_success({"disks": [disk.model_dump(exclude_none=True) for disk in disks], "count": len(disks)})
    except Exception as exc:
        return tool_failure("list disks", exc)


@server.tool(
    name="drive_get_storage_usage",
    description=(
        "Returns each storage pool's capacity, used and free space, and what the used space is used by: "
        "personal drives, shared drives, Microsoft 365 backups, snapshots and the rest (system and other data). "
        "pool_id is the id drive_list_storage_pools returns. Storage pool IDs are scoped to the UniFi Drive tool "
        "family; do not pass them to other products' storage tools."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="storage",
    permission_action="read",
)
async def drive_get_storage_usage() -> Dict[str, Any]:
    """Get per-pool storage usage."""
    try:
        pools = await storage_manager.get_usage()
        return tool_success({"pools": [pool.model_dump(exclude_none=True) for pool in pools], "count": len(pools)})
    except Exception as exc:
        return tool_failure("get storage usage", exc)
