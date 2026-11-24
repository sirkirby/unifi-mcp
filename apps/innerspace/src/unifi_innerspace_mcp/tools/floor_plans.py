"""Floor plan tools: the plans and one plan's image; a plan's title, floor attenuation and scale, and the plan order.

Remaining race: the write lock is per process, so a title, floor attenuation, plan order or scale line that another
server process or the browser editor sets between the fresh read and the write is overwritten silently.
"""

import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_innerspace_mcp.arguments import (
    CONFIRM_FLOW,
    FAMILY,
    Confirm,
    Coordinates,
    PlanId,
    SiteId,
    WriteUnit,
    input_schema,
)
from unifi_innerspace_mcp.resources.uris import plan_image_uri
from unifi_innerspace_mcp.runtime import (
    floor_plan_manager,
    server,
    tool_failure,
    tool_success,
    write_failure,
    write_preview,
    write_result,
)

logger = logging.getLogger(__name__)


@server.tool(
    name="innerspace_list_floor_plans",
    title="List InnerSpace Floor Plans",
    description=(
        "Lists the floor plans of the InnerSpace project with their scale and image placement. Optionally "
        "filtered by site. Read-only. These IDs are scoped to the InnerSpace tool family — do not pass them to "
        "other products' tools."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="floor_plans",
    permission_action="read",
    auth="local_only",
)
async def innerspace_list_floor_plans(site_id: SiteId = None) -> Dict[str, Any]:
    """List floor plans."""
    logger.info("innerspace_list_floor_plans tool called")
    try:
        plans = await floor_plan_manager.list_floor_plans(site_id=site_id)
        return tool_success({"floor_plans": [plan.model_dump() for plan in plans], "count": len(plans)})
    except Exception as e:
        return tool_failure("list InnerSpace floor plans", e)


@server.tool(
    name="innerspace_get_plan_asset",
    title="Get InnerSpace Plan Image",
    description=(
        "Returns one floor plan's image metadata and the resource URI to read the image from. Read-only. "
        "These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="floor_plans",
    permission_action="read",
    auth="local_only",
)
async def innerspace_get_plan_asset(plan_id: PlanId) -> Dict[str, Any]:
    """Get a plan's image metadata and the resource URI its image is read from."""
    logger.info("innerspace_get_plan_asset tool called")
    try:
        asset = await floor_plan_manager.get_plan_asset(plan_id)
        uri = plan_image_uri(plan_id, asset["content_type"])
        if uri is not None:
            asset = {**asset, "resource_uri": uri}
        return tool_success(asset)
    except Exception as e:
        return tool_failure("get InnerSpace plan asset", e)


Title = Annotated[str, Field(description="New plan title, 1 to 32 characters.")]
FloorAttenuation = Annotated[
    float | None,
    Field(description="Signal loss through this floor in dB, 1 to 99, or null for the app default (20 dB)."),
]
PlanOrder = Annotated[
    list[str],
    Field(description=f"Every floor plan id once, lowest floor first. {FAMILY}"),
]
LineEnd = Annotated[float, Field(description="End of the scale line, in unit.")]
LineLength = Annotated[float, Field(description="The real length of the scale line, in unit; above 0.")]


@server.tool(
    name="innerspace_rename_floor_plan",
    input_schema=input_schema(plan_id=PlanId, title=Title, confirm=(Confirm, False)),
    title="Rename InnerSpace Floor Plan",
    description="Changes a floor plan's title. " + CONFIRM_FLOW + " " + FAMILY,
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    permission_category="floor_plans",
    permission_action="update",
    auth="local_only",
)
async def innerspace_rename_floor_plan(plan_id: PlanId, title: Title, confirm: Confirm = False) -> Dict[str, Any]:
    """Preview or rename a floor plan."""
    logger.info("innerspace_rename_floor_plan tool called (confirm=%s)", confirm)
    try:
        if not confirm:
            return write_preview(await floor_plan_manager.preview_rename_floor_plan(plan_id, title))
        result = await floor_plan_manager.apply_rename_floor_plan(plan_id, title)
        return write_result(result, applied="Floor plan renamed and read back.")
    except Exception as e:
        return write_failure("rename InnerSpace floor plan", e)


@server.tool(
    name="innerspace_set_floor_attenuation",
    input_schema=input_schema(plan_id=PlanId, attenuation_db=FloorAttenuation, confirm=(Confirm, False)),
    title="Set InnerSpace Floor Attenuation",
    description=(
        "Sets the signal loss through one floor, which InnerSpace uses between stacked plans; null restores the "
        "app default. " + CONFIRM_FLOW + " " + FAMILY
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    permission_category="floor_plans",
    permission_action="update",
    auth="local_only",
)
async def innerspace_set_floor_attenuation(
    plan_id: PlanId, attenuation_db: FloorAttenuation, confirm: Confirm = False
) -> Dict[str, Any]:
    """Preview or set a floor's attenuation."""
    logger.info("innerspace_set_floor_attenuation tool called (confirm=%s)", confirm)
    try:
        if not confirm:
            return write_preview(await floor_plan_manager.preview_set_floor_attenuation(plan_id, attenuation_db))
        result = await floor_plan_manager.apply_set_floor_attenuation(plan_id, attenuation_db)
        return write_result(result, applied="Floor attenuation set and read back.")
    except Exception as e:
        return write_failure("set InnerSpace floor attenuation", e)


@server.tool(
    name="innerspace_reorder_floor_plans",
    input_schema=input_schema(plan_ids=PlanOrder, confirm=(Confirm, False)),
    title="Reorder InnerSpace Floor Plans",
    description=(
        "Sets the order of the floor plans, which is how InnerSpace stacks the floors. Name every plan once, "
        "lowest floor first. The plans are renumbered 1, 2, 3 ... in that order, so plans that now share an "
        "order value lose the tie and cannot be put back to it. " + CONFIRM_FLOW + " " + FAMILY
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    permission_category="floor_plans",
    permission_action="update",
    auth="local_only",
)
async def innerspace_reorder_floor_plans(plan_ids: PlanOrder, confirm: Confirm = False) -> Dict[str, Any]:
    """Preview or set the plan order."""
    logger.info("innerspace_reorder_floor_plans tool called (confirm=%s)", confirm)
    try:
        if not confirm:
            return write_preview(await floor_plan_manager.preview_reorder_floor_plans(plan_ids))
        result = await floor_plan_manager.apply_reorder_floor_plans(plan_ids)
        return write_result(result, applied="Floor plan order set and read back.")
    except Exception as e:
        return write_failure("reorder InnerSpace floor plans", e)


@server.tool(
    name="innerspace_set_plan_scale",
    input_schema=input_schema(
        plan_id=PlanId,
        x1=LineEnd,
        y1=LineEnd,
        x2=LineEnd,
        y2=LineEnd,
        length=LineLength,
        unit=WriteUnit,
        coordinates=(Coordinates, "frame"),
        confirm=(Confirm, False),
    ),
    title="Set InnerSpace Plan Scale",
    description=(
        "Replaces a floor plan's scale line: a line between two points and its real length. Destructive: every "
        "length on the plan is measured by it, and devices placed on the plan shift on the image (the preview "
        "counts them). " + CONFIRM_FLOW + " " + FAMILY
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="floor_plans",
    permission_action="delete",
    auth="local_only",
)
async def innerspace_set_plan_scale(
    plan_id: PlanId,
    x1: LineEnd,
    y1: LineEnd,
    x2: LineEnd,
    y2: LineEnd,
    length: LineLength,
    unit: WriteUnit,
    coordinates: Coordinates = "frame",
    confirm: Confirm = False,
) -> Dict[str, Any]:
    """Preview or replace a plan's scale line."""
    logger.info("innerspace_set_plan_scale tool called (confirm=%s)", confirm)
    line = dict(x1=x1, y1=y1, x2=x2, y2=y2, length=length, unit=unit, coordinates=coordinates)
    try:
        if not confirm:
            return write_preview(await floor_plan_manager.preview_set_plan_scale(plan_id, **line))
        result = await floor_plan_manager.apply_set_plan_scale(plan_id, **line)
        return write_result(result, applied="Plan scale replaced and read back.")
    except Exception as e:
        return write_failure("set InnerSpace plan scale", e)
