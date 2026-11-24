"""Project tools: the project and the walls of one plan; the project's display unit.

Remaining race: the write lock is per process, so a unit that another server process or the browser editor sets
between the fresh read and the write is overwritten silently.
"""

import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_innerspace_mcp.arguments import CONFIRM_FLOW, Confirm, IncludeShapes, Limit, PlanId, Unit, input_schema
from unifi_innerspace_mcp.runtime import (
    project_manager,
    project_settings_manager,
    server,
    tool_failure,
    tool_success,
    write_failure,
    write_preview,
    write_result,
)

logger = logging.getLogger(__name__)


@server.tool(
    name="innerspace_get_project",
    title="Get InnerSpace Project",
    description=(
        "Returns the InnerSpace project: its title, floor plans, wall types and attenuation-object (RF obstacle) "
        "types. Lengths are in the project's unit unless unit is given; include_shapes adds every shape (large). "
        "Read-only. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="project",
    permission_action="read",
    auth="local_only",
)
async def innerspace_get_project(include_shapes: IncludeShapes = False, unit: Unit = None) -> Dict[str, Any]:
    """Get the project."""
    logger.info("innerspace_get_project tool called")
    try:
        project = await project_manager.get_project(include_shapes=include_shapes, unit=unit)
        return tool_success(project.model_dump())
    except Exception as e:
        return tool_failure("get InnerSpace project", e)


@server.tool(
    name="innerspace_list_walls",
    title="List InnerSpace Walls",
    description=(
        "Lists the walls of one floor plan in the plan's own coordinate frame, in the project's unit unless unit "
        "is given. Cut at limit. Read-only. These IDs are scoped to the InnerSpace tool family — do not pass them "
        "to other products' tools."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="project",
    permission_action="read",
    auth="local_only",
)
async def innerspace_list_walls(plan_id: PlanId, limit: Limit = 500, unit: Unit = None) -> Dict[str, Any]:
    """List the walls of one plan."""
    logger.info("innerspace_list_walls tool called")
    try:
        page = await project_manager.list_walls(plan_id, limit=limit, unit=unit)
        return tool_success(page.model_dump())
    except Exception as e:
        return tool_failure("list InnerSpace walls", e)


ProjectUnit = Annotated[
    str,
    Field(
        description="The unit to display: 'metric' (metres) or 'imperial' (feet).",
        json_schema_extra={"enum": ["metric", "imperial"]},
    ),
]


@server.tool(
    name="innerspace_set_project_unit",
    input_schema=input_schema(unit=ProjectUnit, confirm=(Confirm, False)),
    title="Set InnerSpace Project Unit",
    description=(
        "Sets the unit the InnerSpace app displays lengths in: metric or imperial. Display only: stored "
        "positions do not change, but reads without a unit argument then answer in the new unit. " + CONFIRM_FLOW
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    permission_category="project",
    permission_action="update",
    auth="local_only",
)
async def innerspace_set_project_unit(unit: ProjectUnit, confirm: Confirm = False) -> Dict[str, Any]:
    """Preview or set the project unit."""
    logger.info("innerspace_set_project_unit tool called (confirm=%s)", confirm)
    try:
        if not confirm:
            return write_preview(await project_settings_manager.preview_set_project_unit(unit))
        result = await project_settings_manager.apply_set_project_unit(unit)
        return write_result(result, applied="Project unit set and read back.")
    except Exception as e:
        return write_failure("set InnerSpace project unit", e)
