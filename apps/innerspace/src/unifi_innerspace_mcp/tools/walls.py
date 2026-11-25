"""Wall tools: create, update and remove the walls of one floor plan.

Remaining race: the operation gate runs one write at a time per server process.
An update sends each wall whole from the fresh read, so a change that another
server process or the browser editor makes to the same wall between that read
and the write is overwritten silently.
"""

import logging
from typing import Any, Dict

from mcp.types import ToolAnnotations

from unifi_core.innerspace.models.writes import MAX_CREATE, MAX_REMOVE, MAX_UPDATE, WallCreate, WallUpdate
from unifi_innerspace_mcp.arguments import (
    CONFIRM_FLOW,
    FAMILY,
    PARTIAL_UPDATE,
    Confirm,
    ConfirmCreate,
    Coordinates,
    PlanId,
    WriteUnit,
    id_list,
    input_schema,
    item_list,
)
from unifi_innerspace_mcp.runtime import server, wall_manager, write_failure, write_preview, write_result

logger = logging.getLogger(__name__)

WallsToCreate = item_list(
    WallCreate,
    "Walls to create, at most 100: end points x1, y1, x2, y2 in unit and a variant (material); "
    'variant "custom" takes the wall_type_id of a project wall type.',
    MAX_CREATE,
)
WallsToUpdate = item_list(
    WallUpdate,
    "Walls to update, at most 100: each names its id and only the fields to change. End points go together "
    '(all four of x1, y1, x2, y2); variant "custom" takes a wall_type_id. Each wall is sent whole from a fresh '
    "read, so an edit made elsewhere to the same wall after that read is overwritten; a wall that is gone or "
    "moved to another plan is refused and nothing is sent.",
    MAX_UPDATE,
)
WallIds = id_list("walls", MAX_REMOVE)


@server.tool(
    name="innerspace_create_walls",
    input_schema=input_schema(
        plan_id=PlanId,
        walls=WallsToCreate,
        unit=WriteUnit,
        coordinates=(Coordinates, "frame"),
        confirm=(ConfirmCreate, False),
    ),
    title="Create InnerSpace Walls",
    description=(
        "Creates walls on one floor plan. Field names match innerspace_list_walls. " + CONFIRM_FLOW + " " + FAMILY
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    permission_category="walls",
    permission_action="create",
    auth="local_only",
)
async def innerspace_create_walls(
    plan_id: PlanId,
    walls: WallsToCreate,
    unit: WriteUnit,
    coordinates: Coordinates = "frame",
    confirm: ConfirmCreate = False,
) -> Dict[str, Any]:
    """Preview or create walls."""
    logger.info("innerspace_create_walls tool called (confirm=%s)", confirm)
    try:
        if not confirm:
            return write_preview(
                await wall_manager.preview_create_walls(plan_id, walls, unit=unit, coordinates=coordinates)
            )
        result = await wall_manager.apply_create_walls(plan_id, walls, unit=unit, coordinates=coordinates)
        return write_result(result, applied="Walls created and read back.")
    except Exception as e:
        return write_failure("create InnerSpace walls", e)


@server.tool(
    name="innerspace_update_walls",
    input_schema=input_schema(
        plan_id=PlanId,
        walls=WallsToUpdate,
        unit=WriteUnit,
        coordinates=(Coordinates, "frame"),
        confirm=(Confirm, False),
    ),
    title="Update InnerSpace Walls",
    description=(
        "Moves walls or changes their material on one floor plan. " + PARTIAL_UPDATE + " " + CONFIRM_FLOW + " " + FAMILY
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    permission_category="walls",
    permission_action="update",
    auth="local_only",
)
async def innerspace_update_walls(
    plan_id: PlanId,
    walls: WallsToUpdate,
    unit: WriteUnit,
    coordinates: Coordinates = "frame",
    confirm: Confirm = False,
) -> Dict[str, Any]:
    """Preview or update walls."""
    logger.info("innerspace_update_walls tool called (confirm=%s)", confirm)
    try:
        if not confirm:
            return write_preview(
                await wall_manager.preview_update_walls(plan_id, walls, unit=unit, coordinates=coordinates)
            )
        result = await wall_manager.apply_update_walls(plan_id, walls, unit=unit, coordinates=coordinates)
        return write_result(result, applied="Walls updated and read back.")
    except Exception as e:
        return write_failure("update InnerSpace walls", e)


@server.tool(
    name="innerspace_remove_walls",
    input_schema=input_schema(plan_id=PlanId, wall_ids=WallIds, confirm=(Confirm, False)),
    title="Remove InnerSpace Walls",
    description=(
        "Removes walls from one floor plan, at most 50 per call. The console has no undo. "
        + CONFIRM_FLOW
        + " "
        + FAMILY
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="walls",
    permission_action="delete",
    auth="local_only",
)
async def innerspace_remove_walls(plan_id: PlanId, wall_ids: WallIds, confirm: Confirm = False) -> Dict[str, Any]:
    """Preview or remove walls."""
    logger.info("innerspace_remove_walls tool called (confirm=%s)", confirm)
    try:
        if not confirm:
            return write_preview(await wall_manager.preview_remove_walls(plan_id, wall_ids))
        result = await wall_manager.apply_remove_walls(plan_id, wall_ids)
        return write_result(result, applied="Walls removed and read back.")
    except Exception as e:
        return write_failure("remove InnerSpace walls", e)
