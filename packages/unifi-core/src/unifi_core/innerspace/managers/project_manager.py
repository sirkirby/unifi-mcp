"""The InnerSpace project: plans, walls and placed devices."""

from __future__ import annotations

from typing import Any

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.innerspace.managers._reads import (
    geometry_by_plan,
    read_floor_plan_rows,
    read_project,
    read_project_unit,
)
from unifi_core.innerspace.managers.connection_manager import InnerSpaceConnectionManager, reconnects_on_demand
from unifi_core.innerspace.models.floor_plans import NO_GEOMETRY, PlanGeometry
from unifi_core.innerspace.models.project import (
    PlacedDevicePage,
    ProjectSummary,
    WallPage,
    placed_devices_from_api,
    plan_ids_from_api,
    project_summary_from_api,
    walls_from_api,
)
from unifi_core.innerspace.models.reads import (
    InnerSpaceListInput,
    InnerSpacePlanInput,
    InnerSpaceProjectInput,
    InnerSpaceUnitInput,
)
from unifi_core.innerspace.units import Unit


@reconnects_on_demand
class InnerSpaceProjectManager:
    def __init__(self, cm: InnerSpaceConnectionManager) -> None:
        self._cm = cm

    async def _read(self, operation: str, unit: Unit | None) -> tuple[Any, dict[str, PlanGeometry], Unit]:
        """The 3D project, the geometry of each plan and the unit, after the app status check."""
        await self._cm.ensure_app_running(operation)
        raw = await read_project(self._cm, operation=operation)
        geometry = geometry_by_plan(await read_floor_plan_rows(self._cm, operation=operation))
        return raw, geometry, unit or await read_project_unit(self._cm, operation=operation)

    async def get_project(self, *, include_shapes: bool = False, unit: Unit | None = None) -> ProjectSummary:
        """Project title, plans with their scale, wall types and, on request, every shape."""
        args = InnerSpaceProjectInput(include_shapes=include_shapes, unit=unit)
        raw, geometry, resolved = await self._read("get InnerSpace project", args.unit)
        return project_summary_from_api(raw, geometry=geometry, unit=resolved, include_shapes=args.include_shapes)

    async def _plan_read(self, operation: str, plan_id: str, unit: Unit | None) -> tuple[Any, PlanGeometry, Unit]:
        raw, geometry, resolved = await self._read(operation, unit)
        if plan_id not in plan_ids_from_api(raw):
            raise UniFiNotFoundError("floor plan", "InnerSpace", f"{operation}: no such floor plan")
        return raw, geometry.get(plan_id, NO_GEOMETRY), resolved

    async def list_walls(self, plan_id: str, *, limit: int = 500, unit: Unit | None = None) -> WallPage:
        """Walls of one plan in the project unit, in the documented API's plan frame (see ``FloorPlan``)."""
        plan = InnerSpacePlanInput(plan_id=plan_id)
        page = InnerSpaceListInput(limit=limit)
        chosen = InnerSpaceUnitInput(unit=unit)
        raw, geometry, resolved = await self._plan_read("list InnerSpace walls", plan.plan_id, chosen.unit)
        return walls_from_api(raw, plan.plan_id, geometry=geometry, unit=resolved, limit=page.limit)

    async def list_placed_devices(
        self, plan_id: str, *, limit: int = 500, unit: Unit | None = None
    ) -> PlacedDevicePage:
        """Devices placed on one plan, with position and height in the project unit."""
        plan = InnerSpacePlanInput(plan_id=plan_id)
        page = InnerSpaceListInput(limit=limit)
        chosen = InnerSpaceUnitInput(unit=unit)
        raw, geometry, resolved = await self._plan_read("list InnerSpace placed devices", plan.plan_id, chosen.unit)
        return placed_devices_from_api(raw, plan.plan_id, geometry=geometry, unit=resolved, limit=page.limit)
