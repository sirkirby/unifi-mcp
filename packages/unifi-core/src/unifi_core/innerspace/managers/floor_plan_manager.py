"""InnerSpace floor plans: reads, and the title, floor attenuation and order writes.

The plan ``PATCH`` routes answer with every shape and product in the project;
that reply is never logged or returned, and the read-back decides the outcome.
"""

from __future__ import annotations

import base64
import re
from functools import partial
from typing import Any

from unifi_core.exceptions import UniFiMalformedResponseError, UniFiNotFoundError, UniFiValidationError
from unifi_core.innerspace.managers._layout import (
    Snapshot,
    WritePlan,
    WriteRequest,
    apply_write,
    matches,
    preview_write,
    state,
)
from unifi_core.innerspace.managers._reads import read_floor_plan_rows, read_plan_maps, read_project_unit
from unifi_core.innerspace.managers._writes import plan_path
from unifi_core.innerspace.managers.connection_manager import (
    PLAN_ORDER_PATH,
    InnerSpaceConnectionManager,
    reconnects_on_demand,
)
from unifi_core.innerspace.models._coerce import text
from unifi_core.innerspace.models.floor_plans import FloorPlan, floor_plan_from_api
from unifi_core.innerspace.models.reads import InnerSpaceAssetInput, InnerSpaceSiteInput
from unifi_core.innerspace.models.writes import (
    FloorAttenuationInput,
    RenameFloorPlanInput,
    ReorderFloorPlansInput,
)
from unifi_core.write_verification import WriteVerificationResult

PLAN_ASSET_MAX_BYTES = 8_000_000
_ASSET_URL = re.compile(
    r"/proxy/innerspace/integration/v1/assets/(?P<folder>[0-9a-f-]{36})/(?P<file>[0-9a-f-]{36}\.(?P<ext>png|jpg|jpeg))"
)
_IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}

_RENAME = "rename InnerSpace floor plan"
_ATTENUATION = "set InnerSpace floor attenuation"
_REORDER = "reorder InnerSpace floor plans"


def _plan_field(snapshot: Snapshot, plan_id: str, key: str, value: Any, operation: str, shown: str) -> WritePlan:
    """One field of one plan, sent alone in ``PATCH /plan/{id}``."""
    current = snapshot.plan(plan_id, operation).get(key)

    def request(_: list[str]) -> WriteRequest:
        def expect(after: Snapshot) -> dict[str, bool | None]:
            return {plan_id: state(after.plans.get(plan_id), {key: value}, {key: current})}

        return WriteRequest("PATCH", plan_path(plan_id), {key: value}, expect)

    preview = {"plan_id": plan_id, "current": {shown: current}, "proposed": {shown: value}}
    unchanged = matches({key: current}, {key: value})
    return WritePlan(preview=preview, request=None if unchanged else request)


def _rename(args: RenameFloorPlanInput, snapshot: Snapshot) -> WritePlan:
    return _plan_field(snapshot, args.plan_id, "title", args.title, _RENAME, "title")


def _attenuation(args: FloorAttenuationInput, snapshot: Snapshot) -> WritePlan:
    plan = _plan_field(snapshot, args.plan_id, "attenuation", args.attenuation_db, _ATTENUATION, "attenuation_db")
    plan.warnings.append("null means the app default of 20 dB")
    return plan


def _reorder(args: ReorderFloorPlansInput, snapshot: Snapshot) -> WritePlan:
    if set(args.plan_ids) != set(snapshot.plans):
        raise UniFiValidationError(f"{_REORDER}: name every floor plan of the project exactly once")
    body = [{"id": plan_id, "ordering": index} for index, plan_id in enumerate(args.plan_ids, start=1)]
    current = {plan_id: snapshot.plans[plan_id].get("ordering") for plan_id in args.plan_ids}
    moved = [item for item in body if not matches({"o": current[item["id"]]}, {"o": item["ordering"]})]

    def request(_: list[str]) -> WriteRequest:
        def expect(after: Snapshot) -> dict[str, bool | None]:
            # Only a moved plan can tell landed from not landed: an unmoved one reads the same either way.
            return {
                item["id"]: state(
                    after.plans.get(item["id"]), {"ordering": item["ordering"]}, {"ordering": current[item["id"]]}
                )
                for item in moved
            }

        return WriteRequest("PATCH", PLAN_ORDER_PATH, body, expect)

    preview = {
        "count": len(body),
        "items": [
            {
                "id": item["id"],
                "title": snapshot.plans[item["id"]].get("title"),
                "current": current[item["id"]],
                "proposed": item["ordering"],
            }
            for item in body
        ],
    }
    return WritePlan(
        preview=preview,
        request=request if moved else None,
        effects={"plans_moved": len(moved)},
        warnings=["Plan order also stacks the floors: neighbouring order values are adjacent floors for coverage"],
    )


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

    async def preview_rename_floor_plan(self, plan_id: str, title: str) -> dict[str, Any]:
        """The plan's current and proposed title."""
        args = RenameFloorPlanInput(plan_id=plan_id, title=title)
        return await preview_write(self._cm, operation=_RENAME, build=partial(_rename, args))

    async def apply_rename_floor_plan(self, plan_id: str, title: str) -> WriteVerificationResult:
        """Rename a floor plan (1 to 32 characters)."""
        args = RenameFloorPlanInput(plan_id=plan_id, title=title)
        return await apply_write(
            self._cm, operation=_RENAME, tool="innerspace_rename_floor_plan", args=args, build=partial(_rename, args)
        )

    async def preview_set_floor_attenuation(self, plan_id: str, attenuation_db: float | None) -> dict[str, Any]:
        """The floor's current and proposed attenuation; ``None`` is the app default (20 dB)."""
        args = FloorAttenuationInput(plan_id=plan_id, attenuation_db=attenuation_db)
        return await preview_write(self._cm, operation=_ATTENUATION, build=partial(_attenuation, args))

    async def apply_set_floor_attenuation(self, plan_id: str, attenuation_db: float | None) -> WriteVerificationResult:
        """Set the loss through this floor in dB (1 to 99), or ``None`` for the app default."""
        args = FloorAttenuationInput(plan_id=plan_id, attenuation_db=attenuation_db)
        return await apply_write(
            self._cm,
            operation=_ATTENUATION,
            tool="innerspace_set_floor_attenuation",
            args=args,
            build=partial(_attenuation, args),
        )

    async def preview_reorder_floor_plans(self, plan_ids: list[str]) -> dict[str, Any]:
        """Each plan's current and proposed order value; ``plan_ids`` lists every plan, lowest floor first."""
        args = ReorderFloorPlansInput(plan_ids=plan_ids)
        return await preview_write(self._cm, operation=_REORDER, build=partial(_reorder, args))

    async def apply_reorder_floor_plans(self, plan_ids: list[str]) -> WriteVerificationResult:
        """Set the plan order: every plan once, lowest floor first; plan ``i`` gets order value ``i + 1``."""
        args = ReorderFloorPlansInput(plan_ids=plan_ids)
        return await apply_write(
            self._cm,
            operation=_REORDER,
            tool="innerspace_reorder_floor_plans",
            args=args,
            build=partial(_reorder, args),
        )
