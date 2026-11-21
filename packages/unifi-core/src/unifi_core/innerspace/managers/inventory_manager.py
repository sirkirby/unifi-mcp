"""InnerSpace access points, switches and unplaced inventory."""

from __future__ import annotations

from typing import Any

from unifi_core.innerspace.managers._reads import (
    geometry_by_plan,
    read_floor_plan_rows,
    read_list,
    read_project_unit,
    site_params,
)
from unifi_core.innerspace.managers.connection_manager import InnerSpaceConnectionManager, reconnects_on_demand
from unifi_core.innerspace.models._coerce import as_dict
from unifi_core.innerspace.models.devices import (
    AccessPoint,
    InventoryDevice,
    Switch,
    access_point_from_api,
    inventory_device_from_api,
    switch_from_api,
)
from unifi_core.innerspace.models.floor_plans import PlanGeometry
from unifi_core.innerspace.models.reads import InnerSpaceSiteInput, InnerSpaceUnitInput
from unifi_core.innerspace.units import Unit


@reconnects_on_demand
class InnerSpaceInventoryManager:
    def __init__(self, cm: InnerSpaceConnectionManager) -> None:
        self._cm = cm

    async def _placed(
        self, name: str, operation: str, site_id: str | None, unit: Unit | None
    ) -> tuple[list[Any], dict[str, PlanGeometry], Unit]:
        """Rows of a placed-device list with each row's plan scale, and the unit."""
        site = InnerSpaceSiteInput(site_id=site_id)
        chosen = InnerSpaceUnitInput(unit=unit)
        await self._cm.ensure_app_running(operation)
        rows = await read_list(self._cm, name, operation=operation, params=site_params(site.site_id))
        plans = geometry_by_plan(await read_floor_plan_rows(self._cm, operation=operation, site_id=site.site_id))
        resolved = chosen.unit or await read_project_unit(self._cm, operation=operation)
        return rows, plans, resolved

    @staticmethod
    def _ppm(plans: dict[str, PlanGeometry], row: Any) -> float | None:
        geometry = plans.get(as_dict(row).get("floor_plan_id"))
        return None if geometry is None else geometry.ppm

    async def list_access_points(self, *, site_id: str | None = None, unit: Unit | None = None) -> list[AccessPoint]:
        """Access points with position in the project unit; the list is not paged."""
        rows, plans, resolved = await self._placed("access_points", "list InnerSpace access points", site_id, unit)
        return [access_point_from_api(row, ppm=self._ppm(plans, row), unit=resolved) for row in rows]

    async def list_switches(self, *, site_id: str | None = None, unit: Unit | None = None) -> list[Switch]:
        """Switches with position in the project unit; the list is not paged."""
        rows, plans, resolved = await self._placed("switches", "list InnerSpace switches", site_id, unit)
        return [switch_from_api(row, ppm=self._ppm(plans, row), unit=resolved) for row in rows]

    async def list_inventory(self, *, site_id: str | None = None) -> list[InventoryDevice]:
        """Devices adopted by the console but not placed on a plan."""
        operation = "list InnerSpace inventory"
        site = InnerSpaceSiteInput(site_id=site_id)
        await self._cm.ensure_app_running(operation)
        rows = await read_list(
            self._cm, "inventory", operation=operation, params=site_params(site.site_id), key="devices"
        )
        return [inventory_device_from_api(row) for row in rows]
