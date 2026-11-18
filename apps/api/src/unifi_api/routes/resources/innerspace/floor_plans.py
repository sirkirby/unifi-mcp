"""InnerSpace floor plans and plan image metadata.

- ``GET /sites/{site_id}/innerspace/floor-plans`` → ``innerspace_list_floor_plans``
- ``GET /sites/{site_id}/innerspace/floor-plans/{plan_id}/asset`` → ``innerspace_get_plan_asset``

The API never returns the image itself: it is read through the InnerSpace MCP
server's plan image resource, and ``include_image`` is refused here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import resolve_controller
from unifi_api.routes.resources.innerspace._common import SITE_NOTE, SiteQuery, detail, items, read
from unifi_api.services.innerspace import InnerSpaceAPIError

router = APIRouter()


@router.get(
    "/sites/{site_id}/innerspace/floor-plans",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["innerspace/floor-plans"],
    summary="List InnerSpace floor plans",
    description=f"Floor plans with scale, image size, image file name and image scale and offset. {SITE_NOTE}",
)
async def list_innerspace_floor_plans(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    innerspace_site_id: str | None = SiteQuery,
) -> dict:
    operation = "list InnerSpace floor plans"
    result = await read(
        request,
        controller,
        manager_attr="floor_plan_manager",
        method="list_floor_plans",
        operation=operation,
        site_id=innerspace_site_id,
    )
    return items(request, "innerspace_list_floor_plans", result, operation=operation)


@router.get(
    "/sites/{site_id}/innerspace/floor-plans/{plan_id}/asset",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["innerspace/floor-plans"],
    summary="Get InnerSpace plan image metadata",
    description=(
        "Image metadata of one floor plan: file name, type, pixel size and scale. The API never returns the image "
        f"and refuses include_image; read the image through the InnerSpace MCP server. {SITE_NOTE}"
    ),
)
async def get_innerspace_plan_asset(
    request: Request,
    site_id: str,
    plan_id: str,
    controller=Depends(resolve_controller),
) -> dict:
    operation = "get InnerSpace plan asset"
    if "include_image" in request.query_params:
        raise InnerSpaceAPIError(
            422,
            "invalid_innerspace_request",
            f"Failed to {operation}: include_image is not supported by the API; read the image "
            "through the InnerSpace MCP server: its plan image resource, innerspace://plans/{plan_id}/image, serves "
            "PNG plan images; for other formats use innerspace_get_plan_asset with include_image on the MCP server.",
        )
    result = await read(
        request,
        controller,
        manager_attr="floor_plan_manager",
        method="get_plan_asset",
        operation=operation,
        args=(plan_id,),
    )
    return detail(request, "innerspace_get_plan_asset", result, operation=operation)
