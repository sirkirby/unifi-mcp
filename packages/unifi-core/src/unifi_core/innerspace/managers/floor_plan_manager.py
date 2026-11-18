"""InnerSpace floor plans."""

from __future__ import annotations

from unifi_core.innerspace.managers._reads import read_floor_plan_rows, read_plan_maps, read_project_unit
from unifi_core.innerspace.managers.connection_manager import InnerSpaceConnectionManager, reconnects_on_demand
from unifi_core.innerspace.models._coerce import text
from unifi_core.innerspace.models.floor_plans import FloorPlan, floor_plan_from_api
from unifi_core.innerspace.models.reads import InnerSpaceSiteInput


@reconnects_on_demand
class InnerSpaceFloorPlanManager:
    def __init__(self, cm: InnerSpaceConnectionManager) -> None:
        self._cm = cm

    async def list_floor_plans(self, *, site_id: str | None = None) -> list[FloorPlan]:
        """Floor plans with scale, image size, image file name and the map's image scale and offset."""
        operation = "list InnerSpace floor plans"
        site = InnerSpaceSiteInput(site_id=site_id)
        await self._cm.ensure_app_running(operation)
        rows = await read_floor_plan_rows(self._cm, operation=operation, site_id=site.site_id)
        maps = await read_plan_maps(self._cm, operation=operation)
        unit = await read_project_unit(self._cm, operation=operation)
        return [floor_plan_from_api(row, unit=unit, image_map=maps.get(text(row.get("id")))) for row in rows]
