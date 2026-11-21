"""Project tools: the project, and the walls of one plan."""

import logging
from typing import Any, Dict

from mcp.types import ToolAnnotations

from unifi_innerspace_mcp.arguments import IncludeShapes, Limit, PlanId, Unit
from unifi_innerspace_mcp.runtime import project_manager, server, tool_failure, tool_success

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
