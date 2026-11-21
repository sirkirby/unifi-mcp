"""InnerSpace floor plans."""

from __future__ import annotations

import base64
import re
from typing import Any

from unifi_core.exceptions import UniFiMalformedResponseError, UniFiNotFoundError
from unifi_core.innerspace.managers._reads import read_floor_plan_rows, read_plan_maps, read_project_unit
from unifi_core.innerspace.managers.connection_manager import InnerSpaceConnectionManager, reconnects_on_demand
from unifi_core.innerspace.models._coerce import text
from unifi_core.innerspace.models.floor_plans import FloorPlan, floor_plan_from_api
from unifi_core.innerspace.models.reads import InnerSpaceAssetInput, InnerSpaceSiteInput

PLAN_ASSET_MAX_BYTES = 8_000_000
_ASSET_URL = re.compile(
    r"/proxy/innerspace/integration/v1/assets/(?P<folder>[0-9a-f-]{36})/(?P<file>[0-9a-f-]{36}\.(?P<ext>png|jpg|jpeg))"
)
_IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}


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

    async def get_plan_asset(self, plan_id: str, *, include_image: bool = False) -> dict[str, Any]:
        """A plan's image metadata and, with ``include_image``, the image itself as base64.

        The address is only the plan's own ``image_url`` from its floor-plan row, and it is
        fetched only when it matches the fixed asset pattern and equals the image address of
        that plan's map in the project; nothing in it comes from the caller. The folder
        segment is the console's own id, not the plan id. The metadata carries the map's
        image scale and offset, which place plan positions on the image (see ``FloorPlan``).
        """
        operation = "get InnerSpace plan asset"
        args = InnerSpaceAssetInput(plan_id=plan_id, include_image=include_image)
        await self._cm.ensure_app_running(operation)
        rows = await read_floor_plan_rows(self._cm, operation=operation)
        row = next((r for r in rows if r.get("id") == args.plan_id), None)
        if row is None:
            raise UniFiNotFoundError("floor plan", "InnerSpace", f"{operation}: no such floor plan")
        image_map = (await read_plan_maps(self._cm, operation=operation)).get(args.plan_id)
        unit = await read_project_unit(self._cm, operation=operation)
        plan = floor_plan_from_api(row, unit=unit, image_map=image_map)
        url = row.get("image_url")
        match = _ASSET_URL.fullmatch(url) if isinstance(url, str) else None
        if match is None or image_map is None or image_map.get("urlImage") != url:
            raise UniFiMalformedResponseError(f"{operation}: the floor plan has no usable image address")
        content_type = _IMAGE_TYPES[match["ext"]]
        result: dict[str, Any] = {
            "filename": match["file"],
            "content_type": content_type,
            "width_px": plan.width_px,
            "height_px": plan.height_px,
            "scale_per_unit": plan.scale_per_unit,
            "image_scale": plan.image_scale,
            "image_offset": plan.image_offset,
            "unit": unit,
        }
        if args.include_image:
            body, result["content_type"] = await self._cm.request_bytes(
                url, operation=operation, max_bytes=PLAN_ASSET_MAX_BYTES, allowed_types=(content_type,)
            )
            result["image_base64"] = base64.b64encode(body).decode("ascii")
        return result
