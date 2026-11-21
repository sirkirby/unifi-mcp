"""InnerSpace devices: placed on a plan, access points, switches and unplaced inventory.

- ``GET /sites/{site_id}/innerspace/floor-plans/{plan_id}/devices`` → ``innerspace_list_placed_devices``
- ``GET /sites/{site_id}/innerspace/access-points`` → ``innerspace_list_access_points``
- ``GET /sites/{site_id}/innerspace/switches`` → ``innerspace_list_switches``
- ``GET /sites/{site_id}/innerspace/inventory`` → ``innerspace_list_inventory``
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import resolve_controller
from unifi_api.routes.resources.innerspace._common import (
    SITE_NOTE,
    LimitQuery,
    SiteQuery,
    UnitQuery,
    detail,
    items,
    read,
)
from unifi_api.services.innerspace import page_with_limit

router = APIRouter()
_TAGS = ["innerspace/devices"]
_READ = [Depends(require_scope(Scope.READ))]


@router.get(
    "/sites/{site_id}/innerspace/floor-plans/{plan_id}/devices",
    dependencies=_READ,
    tags=_TAGS,
    summary="List the devices placed on an InnerSpace floor plan",
    description=(
        "Devices placed on one floor plan with position and height. The result reports limit, total and whether "
        f"the list was cut. {SITE_NOTE}"
    ),
)
async def list_innerspace_placed_devices(
    request: Request,
    site_id: str,
    plan_id: str,
    controller=Depends(resolve_controller),
    limit: int = LimitQuery,
    unit: str | None = UnitQuery,
) -> dict:
    operation = "list InnerSpace placed devices"
    result = await read(
        request,
        controller,
        manager_attr="project_manager",
        method="list_placed_devices",
        operation=operation,
        args=(plan_id,),
        limit=limit,
        unit=unit,
    )
    return detail(request, "innerspace_list_placed_devices", page_with_limit(result, limit), operation=operation)


@router.get(
    "/sites/{site_id}/innerspace/access-points",
    dependencies=_READ,
    tags=_TAGS,
    summary="List InnerSpace access points",
    description=f"Access points with position, height, azimuth and mount. {SITE_NOTE}",
)
async def list_innerspace_access_points(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    innerspace_site_id: str | None = SiteQuery,
    unit: str | None = UnitQuery,
) -> dict:
    operation = "list InnerSpace access points"
    result = await read(
        request,
        controller,
        manager_attr="inventory_manager",
        method="list_access_points",
        operation=operation,
        site_id=innerspace_site_id,
        unit=unit,
    )
    return items(request, "innerspace_list_access_points", result, operation=operation)


@router.get(
    "/sites/{site_id}/innerspace/switches",
    dependencies=_READ,
    tags=_TAGS,
    summary="List InnerSpace switches",
    description=f"Switches with position. {SITE_NOTE}",
)
async def list_innerspace_switches(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    innerspace_site_id: str | None = SiteQuery,
    unit: str | None = UnitQuery,
) -> dict:
    operation = "list InnerSpace switches"
    result = await read(
        request,
        controller,
        manager_attr="inventory_manager",
        method="list_switches",
        operation=operation,
        site_id=innerspace_site_id,
        unit=unit,
    )
    return items(request, "innerspace_list_switches", result, operation=operation)


@router.get(
    "/sites/{site_id}/innerspace/inventory",
    dependencies=_READ,
    tags=_TAGS,
    summary="List unplaced InnerSpace inventory",
    description=f"Devices the console has adopted that are not yet placed on a floor plan. {SITE_NOTE}",
)
async def list_innerspace_inventory(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    innerspace_site_id: str | None = SiteQuery,
) -> dict:
    operation = "list InnerSpace inventory"
    result = await read(
        request,
        controller,
        manager_attr="inventory_manager",
        method="list_inventory",
        operation=operation,
        site_id=innerspace_site_id,
    )
    return items(request, "innerspace_list_inventory", result, operation=operation)
