"""Floor plan tools: the plans, and one plan's image."""

import logging
from typing import Any, Dict

from mcp.types import ToolAnnotations

from unifi_innerspace_mcp.arguments import IncludeImage, PlanId, SiteId
from unifi_innerspace_mcp.resources.uris import plan_image_uri
from unifi_innerspace_mcp.runtime import floor_plan_manager, server, tool_failure, tool_success

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
        "Returns one floor plan's image metadata and, for a PNG, the resource URI to read the image from; "
        "include_image also returns the image. Read-only. These IDs are scoped to the InnerSpace tool family — "
        "do not pass them to other products' tools."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="floor_plans",
    permission_action="read",
    auth="local_only",
)
async def innerspace_get_plan_asset(plan_id: PlanId, include_image: IncludeImage = False) -> Dict[str, Any]:
    """Get a plan's image metadata, and optionally the image."""
    logger.info("innerspace_get_plan_asset tool called")
    try:
        asset = await floor_plan_manager.get_plan_asset(plan_id, include_image=include_image)
        # The resource serves PNG only; another type is read with include_image.
        if asset["content_type"] == "image/png":
            asset = {**asset, "resource_uri": plan_image_uri(plan_id)}
        return tool_success(asset)
    except Exception as e:
        return tool_failure("get InnerSpace plan asset", e)
