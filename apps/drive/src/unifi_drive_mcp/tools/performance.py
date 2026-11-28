"""Performance tools for the UniFi Drive MCP server: network throughput, fan profile and disk activity. Read-only."""

import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.drive.managers.performance_manager import MAX_DISK_STATS_HOURS
from unifi_drive_mcp.runtime import performance_manager, server, tool_failure, tool_success

logger = logging.getLogger(__name__)


@server.tool(
    name="drive_get_network_throughput",
    description="Returns the NAS's network throughput right now: data received and sent, in KB/s.",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="performance",
    permission_action="read",
)
async def drive_get_network_throughput() -> Dict[str, Any]:
    """Get the NAS's live network throughput."""
    try:
        throughput = await performance_manager.get_network_throughput()
        return tool_success(throughput.model_dump(exclude_none=True))
    except Exception as exc:
        return tool_failure("get network throughput", exc)


@server.tool(
    name="drive_get_fan_profile",
    description=(
        "Returns the NAS's fan mode and the modes it offers, with the names the Drive web app shows "
        "(Cooling, Balanced, Quiet). Read-only."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="performance",
    permission_action="read",
)
async def drive_get_fan_profile() -> Dict[str, Any]:
    """Get the NAS's fan profile."""
    try:
        fan = await performance_manager.get_fan_profile()
        return tool_success(fan.model_dump(exclude_none=True))
    except Exception as exc:
        return tool_failure("get fan profile", exc)


@server.tool(
    name="drive_get_disk_stats",
    description=(
        "Returns each disk's temperature, read and write throughput (KB/s) and bad sector count over the last "
        "`hours`, summarized per disk. Buckets are 15 minutes under 7 days, 1 hour under 30 days, 6 hours beyond. "
        "Set include_samples for the per-bucket values; they are large over long windows."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="performance",
    permission_action="read",
)
async def drive_get_disk_stats(
    hours: Annotated[
        int,
        Field(ge=1, le=MAX_DISK_STATS_HOURS, description="How far back to read, in hours (default 24, up to 90 days)"),
    ] = 24,
    include_samples: Annotated[
        bool,
        Field(
            description=(
                "Also return every bucket's values for each disk (default false). Adds one entry per bucket per "
                "disk, about 12 KB per disk per day at 15-minute buckets and up to about 1 MB for a full NAS over a "
                "week or more; use a short window"
            )
        ),
    ] = False,
) -> Dict[str, Any]:
    """Get per-disk activity over a window."""
    try:
        stats = await performance_manager.get_disk_stats(hours=hours)
        data = stats.model_dump(exclude_none=True)
        if not include_samples:
            for disk in data["disks"]:
                disk.pop("samples", None)
        data["count"] = len(stats.disks)
        return tool_success(data)
    except Exception as exc:
        return tool_failure("get disk stats", exc)
