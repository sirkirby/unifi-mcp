"""InnerSpace project and walls.

- ``GET /sites/{site_id}/innerspace/project`` → ``innerspace_get_project``
- ``GET /sites/{site_id}/innerspace/floor-plans/{plan_id}/walls`` → ``innerspace_list_walls``
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import resolve_controller
from unifi_api.routes.resources.innerspace._common import SITE_NOTE, LimitQuery, UnitQuery, detail, read
from unifi_api.services.innerspace import page_with_limit

router = APIRouter()


@router.get(
    "/sites/{site_id}/innerspace/project",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["innerspace/project"],
    summary="Get the InnerSpace project",
    description=(
        "The project's title, its floor plans with their scale, and its wall types; every shape with "
        f"include_shapes (large). {SITE_NOTE}"
    ),
)
async def get_innerspace_project(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    include_shapes: bool = Query(False, description="Also return every shape with converted geometry (large)."),
    unit: str | None = UnitQuery,
) -> dict:
    operation = "get InnerSpace project"
    result = await read(
        request,
        controller,
        manager_attr="project_manager",
        method="get_project",
        operation=operation,
        include_shapes=include_shapes,
        unit=unit,
    )
    return detail(request, "innerspace_get_project", result, operation=operation)


@router.get(
    "/sites/{site_id}/innerspace/floor-plans/{plan_id}/walls",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["innerspace/project"],
    summary="List the walls of an InnerSpace floor plan",
    description=(
        "Walls of one floor plan with end points in the plan's own frame. The result reports limit, total and "
        f"whether the list was cut. {SITE_NOTE}"
    ),
)
async def list_innerspace_walls(
    request: Request,
    site_id: str,
    plan_id: str,
    controller=Depends(resolve_controller),
    limit: int = LimitQuery,
    unit: str | None = UnitQuery,
) -> dict:
    operation = "list InnerSpace walls"
    result = await read(
        request,
        controller,
        manager_attr="project_manager",
        method="list_walls",
        operation=operation,
        args=(plan_id,),
        limit=limit,
        unit=unit,
    )
    return detail(request, "innerspace_list_walls", page_with_limit(result, limit), operation=operation)
