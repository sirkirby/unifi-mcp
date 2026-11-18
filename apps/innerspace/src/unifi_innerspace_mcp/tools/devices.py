"""Device tools: devices placed on a plan, access points, switches and unplaced inventory."""

import logging
from typing import Any, Dict

from mcp.types import ToolAnnotations

from unifi_innerspace_mcp.arguments import Limit, PlanId, SiteId, Unit
from unifi_innerspace_mcp.runtime import inventory_manager, project_manager, server, tool_failure, tool_success

logger = logging.getLogger(__name__)

_FAMILY = "These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools."


@server.tool(
    name="innerspace_list_placed_devices",
    title="List Placed InnerSpace Devices",
    description=(
        "Lists the devices placed on one floor plan, in the project's unit unless unit is given. Cut at limit. "
        "Read-only. " + _FAMILY
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="devices",
    permission_action="read",
    auth="local_only",
)
async def innerspace_list_placed_devices(plan_id: PlanId, limit: Limit = 500, unit: Unit = None) -> Dict[str, Any]:
    """List the devices placed on one plan."""
    logger.info("innerspace_list_placed_devices tool called")
    try:
        page = await project_manager.list_placed_devices(plan_id, limit=limit, unit=unit)
        return tool_success(page.model_dump())
    except Exception as e:
        return tool_failure("list InnerSpace placed devices", e)


@server.tool(
    name="innerspace_list_access_points",
    title="List InnerSpace Access Points",
    description=(
        "Lists the access points in the InnerSpace project and where they are placed, in the project's unit "
        "unless unit is given. Optionally filtered by site. Read-only. " + _FAMILY
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="devices",
    permission_action="read",
    auth="local_only",
)
async def innerspace_list_access_points(site_id: SiteId = None, unit: Unit = None) -> Dict[str, Any]:
    """List access points."""
    logger.info("innerspace_list_access_points tool called")
    try:
        points = await inventory_manager.list_access_points(site_id=site_id, unit=unit)
        return tool_success({"access_points": [point.model_dump() for point in points], "count": len(points)})
    except Exception as e:
        return tool_failure("list InnerSpace access points", e)


@server.tool(
    name="innerspace_list_switches",
    title="List InnerSpace Switches",
    description=(
        "Lists the switches in the InnerSpace project and where they are placed, in the project's unit unless "
        "unit is given. Optionally filtered by site. Read-only. " + _FAMILY
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="devices",
    permission_action="read",
    auth="local_only",
)
async def innerspace_list_switches(site_id: SiteId = None, unit: Unit = None) -> Dict[str, Any]:
    """List switches."""
    logger.info("innerspace_list_switches tool called")
    try:
        switches = await inventory_manager.list_switches(site_id=site_id, unit=unit)
        return tool_success({"switches": [switch.model_dump() for switch in switches], "count": len(switches)})
    except Exception as e:
        return tool_failure("list InnerSpace switches", e)


@server.tool(
    name="innerspace_list_inventory",
    title="List InnerSpace Inventory",
    description=(
        "Lists the devices the console has adopted that are not yet placed on a floor plan. Optionally filtered "
        "by site. Read-only. " + _FAMILY
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="devices",
    permission_action="read",
    auth="local_only",
)
async def innerspace_list_inventory(site_id: SiteId = None) -> Dict[str, Any]:
    """List unplaced inventory devices."""
    logger.info("innerspace_list_inventory tool called")
    try:
        devices = await inventory_manager.list_inventory(site_id=site_id)
        return tool_success({"devices": [device.model_dump() for device in devices], "count": len(devices)})
    except Exception as e:
        return tool_failure("list InnerSpace inventory", e)
