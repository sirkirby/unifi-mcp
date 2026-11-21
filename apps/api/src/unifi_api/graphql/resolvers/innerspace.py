"""InnerSpaceQuery: read-only GraphQL fields for UniFi InnerSpace.

Each field calls the same core manager method as the REST route and the
action, through :func:`unifi_api.services.innerspace.read_innerspace`, so a
failure maps to the same fixed text; here it surfaces as a GraphQL error code.
Lists are returned whole (InnerSpace does not page them); walls and placed
devices come as pages with their limit, total and truncation flag. No field
returns plan image bytes.
"""

from __future__ import annotations

from typing import Any

import strawberry
from strawberry.types import Info

from unifi_api.graphql.context import GraphQLContext
from unifi_api.graphql.permissions import IsRead
from unifi_api.graphql.types.innerspace._base import DESCRIPTION
from unifi_api.graphql.types.innerspace.devices import (
    InnerSpaceAccessPoint,
    InnerSpaceInventoryDevice,
    InnerSpaceSwitch,
)
from unifi_api.graphql.types.innerspace.floor_plans import InnerSpaceFloorPlan, InnerSpacePlanAsset
from unifi_api.graphql.types.innerspace.project import (
    InnerSpacePlacedDevicePage,
    InnerSpaceProject,
    InnerSpaceWallPage,
)
from unifi_api.graphql.types.innerspace.system import InnerSpaceStatus
from unifi_api.services.controllers import get_controller
from unifi_api.services.incident_evidence import require_product
from unifi_api.services.innerspace import (
    DEFAULT_LIMIT,
    ID_FAMILY,
    PRODUCT,
    map_innerspace_error,
    page_with_limit,
    read_innerspace,
)


async def _read(
    info: Info,
    controller: str,
    *,
    manager_attr: str,
    method: str,
    operation: str,
    args: tuple[Any, ...] = (),
    **kwargs: Any,
) -> Any:
    ctx: GraphQLContext = info.context
    async with ctx.sessionmaker() as session:
        row = await get_controller(session, str(controller))
    require_product(row, PRODUCT)
    key = f"innerspace/{controller}/{manager_attr}.{method}/{args!r}/{sorted(kwargs.items())!r}"

    async def _fetch() -> Any:
        return await read_innerspace(
            sessionmaker=ctx.sessionmaker,
            factory=ctx.manager_factory,
            controller_id=str(controller),
            manager_attr=manager_attr,
            method=method,
            operation=operation,
            args=args,
            kwargs=kwargs,
        )

    return await ctx.cache.get_or_fetch(key, _fetch)


def _project(info: Info, type_class: type, obj: Any, operation: str) -> Any:
    """Project one result; a result it cannot project maps like any other read failure."""
    ctx: GraphQLContext = info.context
    try:
        return type_class.from_manager_output(obj, redact_sensitive=ctx.redact_sensitive_fields)
    except Exception as exc:
        raise map_innerspace_error(exc, operation) from None


@strawberry.type(description=f"Read-only access to UniFi InnerSpace resources. {ID_FAMILY}")
class InnerSpaceQuery:
    @strawberry.field(
        permission_classes=[IsRead],
        description=f"Whether InnerSpace is installed and running on the console. {ID_FAMILY}",
    )
    async def status(self, info: Info, controller: strawberry.ID) -> InnerSpaceStatus:
        operation = "get InnerSpace status"
        result = await _read(info, controller, manager_attr="system_manager", method="get_status", operation=operation)
        return _project(info, InnerSpaceStatus, result, operation)

    @strawberry.field(permission_classes=[IsRead], description=f"The InnerSpace project. {DESCRIPTION}")
    async def project(
        self,
        info: Info,
        controller: strawberry.ID,
        include_shapes: bool = False,
        unit: str | None = None,
    ) -> InnerSpaceProject:
        operation = "get InnerSpace project"
        result = await _read(
            info,
            controller,
            manager_attr="project_manager",
            method="get_project",
            operation=operation,
            include_shapes=include_shapes,
            unit=unit,
        )
        return _project(info, InnerSpaceProject, result, operation)

    @strawberry.field(permission_classes=[IsRead], description=f"InnerSpace floor plans. {DESCRIPTION}")
    async def floor_plans(
        self,
        info: Info,
        controller: strawberry.ID,
        innerspace_site_id: str | None = None,
    ) -> list[InnerSpaceFloorPlan]:
        operation = "list InnerSpace floor plans"
        result = await _read(
            info,
            controller,
            manager_attr="floor_plan_manager",
            method="list_floor_plans",
            operation=operation,
            site_id=innerspace_site_id,
        )
        return [_project(info, InnerSpaceFloorPlan, plan, operation) for plan in result]

    @strawberry.field(permission_classes=[IsRead], description=f"Walls of one InnerSpace floor plan. {DESCRIPTION}")
    async def walls(
        self,
        info: Info,
        controller: strawberry.ID,
        plan_id: str,
        limit: int = DEFAULT_LIMIT,
        unit: str | None = None,
    ) -> InnerSpaceWallPage:
        operation = "list InnerSpace walls"
        result = await _read(
            info,
            controller,
            manager_attr="project_manager",
            method="list_walls",
            operation=operation,
            args=(plan_id,),
            limit=limit,
            unit=unit,
        )
        return _project(info, InnerSpaceWallPage, page_with_limit(result, limit), operation)

    @strawberry.field(
        permission_classes=[IsRead], description=f"Devices placed on one InnerSpace floor plan. {DESCRIPTION}"
    )
    async def placed_devices(
        self,
        info: Info,
        controller: strawberry.ID,
        plan_id: str,
        limit: int = DEFAULT_LIMIT,
        unit: str | None = None,
    ) -> InnerSpacePlacedDevicePage:
        operation = "list InnerSpace placed devices"
        result = await _read(
            info,
            controller,
            manager_attr="project_manager",
            method="list_placed_devices",
            operation=operation,
            args=(plan_id,),
            limit=limit,
            unit=unit,
        )
        return _project(info, InnerSpacePlacedDevicePage, page_with_limit(result, limit), operation)

    @strawberry.field(permission_classes=[IsRead], description=f"InnerSpace access points. {DESCRIPTION}")
    async def access_points(
        self,
        info: Info,
        controller: strawberry.ID,
        innerspace_site_id: str | None = None,
        unit: str | None = None,
    ) -> list[InnerSpaceAccessPoint]:
        operation = "list InnerSpace access points"
        result = await _read(
            info,
            controller,
            manager_attr="inventory_manager",
            method="list_access_points",
            operation=operation,
            site_id=innerspace_site_id,
            unit=unit,
        )
        return [_project(info, InnerSpaceAccessPoint, point, operation) for point in result]

    @strawberry.field(permission_classes=[IsRead], description=f"InnerSpace switches. {DESCRIPTION}")
    async def switches(
        self,
        info: Info,
        controller: strawberry.ID,
        innerspace_site_id: str | None = None,
        unit: str | None = None,
    ) -> list[InnerSpaceSwitch]:
        operation = "list InnerSpace switches"
        result = await _read(
            info,
            controller,
            manager_attr="inventory_manager",
            method="list_switches",
            operation=operation,
            site_id=innerspace_site_id,
            unit=unit,
        )
        return [_project(info, InnerSpaceSwitch, switch, operation) for switch in result]

    @strawberry.field(
        permission_classes=[IsRead], description=f"Adopted devices not yet placed on a plan. {DESCRIPTION}"
    )
    async def inventory(
        self,
        info: Info,
        controller: strawberry.ID,
        innerspace_site_id: str | None = None,
    ) -> list[InnerSpaceInventoryDevice]:
        operation = "list InnerSpace inventory"
        result = await _read(
            info,
            controller,
            manager_attr="inventory_manager",
            method="list_inventory",
            operation=operation,
            site_id=innerspace_site_id,
        )
        return [_project(info, InnerSpaceInventoryDevice, device, operation) for device in result]

    @strawberry.field(
        permission_classes=[IsRead],
        description=(
            "Image metadata of one InnerSpace floor plan. The image itself is read through the InnerSpace MCP "
            f"server, never through this API. {DESCRIPTION}"
        ),
    )
    async def plan_asset(self, info: Info, controller: strawberry.ID, plan_id: str) -> InnerSpacePlanAsset:
        operation = "get InnerSpace plan asset"
        result = await _read(
            info,
            controller,
            manager_attr="floor_plan_manager",
            method="get_plan_asset",
            operation=operation,
            args=(plan_id,),
        )
        return _project(info, InnerSpacePlanAsset, result, operation)
