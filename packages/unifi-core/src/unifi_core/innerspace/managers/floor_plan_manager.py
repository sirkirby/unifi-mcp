"""InnerSpace floor plans: reads, and the title, floor attenuation, order and scale writes.

The plan ``PATCH`` routes answer with every shape and product in the project;
that reply is never logged or returned, and the read-back decides the outcome.
"""

from __future__ import annotations

import base64
import math
import re
from functools import partial
from typing import Any

from unifi_core.exceptions import UniFiMalformedResponseError, UniFiNotFoundError, UniFiValidationError
from unifi_core.innerspace.frames import Coordinates
from unifi_core.innerspace.managers._layout import (
    Display,
    Snapshot,
    WritePlan,
    WriteRequest,
    apply_write,
    matches,
    pick,
    plan_points,
    points_close,
    preview_write,
    shape_change_body,
    state,
)
from unifi_core.innerspace.managers._reads import read_floor_plan_rows, read_plan_maps, read_project_unit
from unifi_core.innerspace.managers._writes import InnerSpaceWriteRefusedError, plan_path, write_ids
from unifi_core.innerspace.managers.connection_manager import (
    PLAN_ORDER_PATH,
    SHAPE_CHANGE_PATH,
    InnerSpaceConnectionManager,
    reconnects_on_demand,
)
from unifi_core.innerspace.models._coerce import number, text
from unifi_core.innerspace.models.floor_plans import FloorPlan, floor_plan_from_api, scale_per_unit
from unifi_core.innerspace.models.reads import InnerSpaceAssetInput, InnerSpaceSiteInput
from unifi_core.innerspace.models.writes import (
    FloorAttenuationInput,
    PlanScaleInput,
    RenameFloorPlanInput,
    ReorderFloorPlansInput,
)
from unifi_core.innerspace.units import Unit, from_metres, to_metres
from unifi_core.write_verification import WriteVerificationResult

PLAN_ASSET_MAX_BYTES = 8_000_000
_ASSET_URL = re.compile(
    r"/proxy/innerspace/integration/v1/assets/(?P<folder>[0-9a-f-]{36})/(?P<file>[0-9a-f-]{36}\.(?P<ext>png|jpg|jpeg))"
)
_IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}

_RENAME = "rename InnerSpace floor plan"
_ATTENUATION = "set InnerSpace floor attenuation"
_REORDER = "reorder InnerSpace floor plans"
_SCALE = "set InnerSpace plan scale"
_SCALE_TOOL = "innerspace_set_plan_scale"
# The read-back key for the plan's computed scale, and how far it may differ from pixels over metres sent.
_COMPUTED_SCALE = "floor_plan_scale"
_SCALE_TOLERANCE = 1e-3
# How far the stored length of the scale line may differ from the metres sent: float round trips, not edits.
_LENGTH_TOLERANCE = 1e-6


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


def _ppm_state(read: float | None, wanted: float, prior: float | None) -> bool | None:
    """The plan's computed scale after a scale write: True within 0.1 % of the line sent, False when unchanged.

    The stored line only echoes what was sent; the floor-plan row's ``ppm`` is what the console made of it,
    so a length taken in another unit shows here. Anything else, a missing ``ppm`` included, is unknown.
    """
    if read is None:
        return None
    if math.isclose(read, wanted, rel_tol=_SCALE_TOLERANCE):
        return True
    return False if prior is not None and math.isclose(read, prior, rel_tol=1e-9) else None


def _length_kept(stored: dict[str, Any] | None, metres: float) -> bool:
    """Whether the stored line's length is the one sent, allowing for the console's float round trip."""
    read = number(stored.get("scale")) if stored else None
    return read is not None and math.isclose(read, metres, rel_tol=_LENGTH_TOLERANCE)


def _scale(args: PlanScaleInput, snapshot: Snapshot) -> WritePlan:
    plan_id = args.plan_id
    plan = snapshot.plan(plan_id, _SCALE)
    lines = snapshot.on_plan(plan_id, "scale")
    if len(lines) != 1:
        raise InnerSpaceWriteRefusedError(
            f"{_SCALE}: the plan has {'no' if not lines else 'more than one'} scale line, and only a plan with "
            "exactly one can have it replaced"
        )
    (stored,) = lines
    metres: float = to_metres(args.length, args.unit)  # type: ignore[assignment]
    stored_metres = number(stored.get("scale"))
    devices = len(snapshot.on_plan(plan_id, "device"))
    if stored.get("id") == write_ids(_SCALE_TOOL, args.model_dump(mode="json"), 1)[0]:
        # The line is this call's own, from an identical earlier call. The plan's scale has changed since,
        # so the same frame points convert differently; they are not compared.
        if not matches({"s": stored_metres}, {"s": metres}):
            raise InnerSpaceWriteRefusedError(
                f"{_SCALE}: the plan's scale line was set by an identical earlier call and has been changed "
                "since. Nothing was sent; change an argument to replace it."
            )
        return WritePlan(
            preview={"plan_id": plan_id, "plan_title": plan.get("title"), "unit": args.unit},
            request=None,
            effects={"devices_shifted": 0},
            noop="already_applied",
        )
    position = plan_points(
        [(args.x1, args.y1), (args.x2, args.y2)],
        frame=snapshot.frame(plan_id),
        unit=args.unit,
        coordinates=args.coordinates,
        operation=_SCALE,
    )
    pixels = math.hypot(position[1]["x"] - position[0]["x"], position[1]["y"] - position[0]["y"])
    # Unrounded: the current line is what an undo sends back.
    display = Display(snapshot.geometry(plan_id), args.unit, args.coordinates, exact=True)
    (x1, y1), (x2, y2) = (display.position(stored.get("position")) + [(None, None)] * 2)[:2]
    unchanged = points_close(stored.get("position"), position) and matches({"s": stored_metres}, {"s": metres})
    prior_ppm = snapshot.geometry(plan_id).ppm

    def request(ids: list[str]) -> WriteRequest:
        line = {
            "id": ids[0],
            "type": "scale",
            "projectId": snapshot.project_id,
            "planId": plan_id,
            "scale": metres,
            "height": stored.get("height"),
            "position": position,
            "status": stored.get("status", 0),
            "defaultScale": False,
            "defaultHeight": stored.get("defaultHeight", False),
            "computedScale": None,
        }
        wanted = pick(line, ("type", "planId", "position"))

        def expect(after: Snapshot) -> dict[str, bool | None]:
            created = after.shapes.get(line["id"])
            created_state = state(created, wanted, None)
            if created_state and not _length_kept(created, metres):
                created_state = None
            states = {line["id"]: created_state, stored["id"]: after.shapes.get(stored["id"]) is None}
            # When the new line keeps the scale, the computed scale reads the same either way and decides nothing.
            if prior_ppm is None or not math.isclose(pixels / metres, prior_ppm, rel_tol=_SCALE_TOLERANCE):
                states[_COMPUTED_SCALE] = _ppm_state(after.geometry(plan_id).ppm, pixels / metres, prior_ppm)
            return states

        body = shape_change_body(create=[line], remove=[stored], scale=True)
        return WriteRequest("POST", SHAPE_CHANGE_PATH, body, expect, [line["id"]], read_rows=True)

    preview = {
        "plan_id": plan_id,
        "plan_title": plan.get("title"),
        "unit": args.unit,
        "coordinates": args.coordinates,
        "current": {
            "line": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
            # Unrounded: it is what an undo sends back.
            "length": None if stored_metres is None else from_metres(stored_metres, args.unit),  # type: ignore[arg-type]
            "scale_per_unit": scale_per_unit(snapshot.geometry(plan_id).ppm, args.unit),
        },
        "proposed": {
            "line": {"x1": args.x1, "y1": args.y1, "x2": args.x2, "y2": args.y2},
            "length": args.length,
            "scale_per_unit": scale_per_unit(pixels / metres, args.unit),
        },
    }
    warnings = [
        f"{devices} devices on this plan are stored in metres and move on the image when its scale changes; "
        "walls and attenuation objects keep their place on the image"
    ]
    return WritePlan(
        preview=preview,
        request=None if unchanged else request,
        new_ids=1,
        effects={"devices_shifted": devices},
        warnings=warnings,
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

    async def get_plan_asset(
        self, plan_id: str, *, include_image: bool = False, image_type: str | None = None
    ) -> dict[str, Any]:
        """A plan's image metadata and, with ``include_image``, the image itself as base64.

        With ``image_type`` too, the image is downloaded only when the plan's image is that
        type; otherwise the metadata comes back without it, so a caller that serves one type
        learns the plan's type from this one pass instead of reading the metadata twice. A
        mismatch is not an error: ``include_image`` is then not applied, so compare the returned
        ``content_type`` with ``image_type``. Without ``include_image``, ``image_type`` changes nothing.

        The address is only the plan's own ``image_url`` from its floor-plan row, and it is
        fetched only when it matches the fixed asset pattern and equals the image address of
        that plan's map in the project; nothing in it comes from the caller. The folder
        segment is the console's own id, not the plan id. The metadata carries the map's
        image scale and offset, which place plan positions on the image (see ``FloorPlan``).
        """
        operation = "get InnerSpace plan asset"
        args = InnerSpaceAssetInput(plan_id=plan_id, include_image=include_image, image_type=image_type)
        await self._cm.ensure_app_running(operation)
        rows = await read_floor_plan_rows(self._cm, operation=operation)
        row = next((r for r in rows if r.get("id") == args.plan_id), None)
        if row is None:
            raise UniFiNotFoundError("floor plan", args.plan_id, f"{operation}: no such floor plan")
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
        if args.include_image and args.image_type in (None, content_type):
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

    async def preview_set_plan_scale(
        self,
        plan_id: str,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        length: float,
        *,
        unit: Unit,
        coordinates: Coordinates = "frame",
    ) -> dict[str, Any]:
        """The current and proposed scale line and scale, and how many devices would shift on the image."""
        args = PlanScaleInput(
            plan_id=plan_id, x1=x1, y1=y1, x2=x2, y2=y2, length=length, unit=unit, coordinates=coordinates
        )
        return await preview_write(self._cm, operation=_SCALE, build=partial(_scale, args), tool=_SCALE_TOOL, args=args)

    async def apply_set_plan_scale(
        self,
        plan_id: str,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        length: float,
        *,
        unit: Unit,
        coordinates: Coordinates = "frame",
    ) -> WriteVerificationResult:
        """Replace the plan's scale line (a new one created, the old one removed, in one call).

        Destructive: devices are stored in metres, so every device on the plan moves on the image.
        """
        args = PlanScaleInput(
            plan_id=plan_id, x1=x1, y1=y1, x2=x2, y2=y2, length=length, unit=unit, coordinates=coordinates
        )
        return await apply_write(self._cm, operation=_SCALE, tool=_SCALE_TOOL, args=args, build=partial(_scale, args))
