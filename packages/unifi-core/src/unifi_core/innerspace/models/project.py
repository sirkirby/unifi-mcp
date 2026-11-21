"""The InnerSpace project: plans, wall types, walls and placed devices.

Every coordinate uses one frame, the documented API's plan frame: distance from
the plan's top-left in the vendor's coordinates, x to the right and y downward,
in the project unit. It lines up with the plan image only when the plan's
``image_scale`` is 1 and its ``image_offset`` is (0, 0); the conversion to image
pixels is on :class:`~unifi_core.innerspace.models.floor_plans.FloorPlan`. The
controller sends walls in plan units (origin at the centre, y up) and devices in
metres with the height on the y axis, so both are converted here.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from unifi_core.exceptions import UniFiMalformedResponseError
from unifi_core.innerspace.models._coerce import as_dict, as_list, finite, flag, length, number, text, whole_or_number
from unifi_core.innerspace.models.floor_plans import NO_GEOMETRY, PlanGeometry, image_transform, scale_per_unit
from unifi_core.innerspace.units import Unit, plan_units_to_metres
from unifi_core.mac import canonical_mac

WallVariant = Literal[
    "concrete",
    "drywall",
    "drywall_heavy",
    "glass",
    "glass_thin",
    "brick",
    "metal",
    "wood",
    "door_wood",
    "door_metal",
    "door_glass",
    "window_1_pane",
    "window_2_pane",
    "window_3_pane",
    "elevator",
    "foliage_heavy",
    "foliage_light",
    "machinery",
    "shelf_warehouse",
    "custom",
]
DeviceMount = Literal["ceiling", "wall", "floor", "rack"]
ShapeType = Literal["map", "scale", "device", "wall", "attenuationObject", "rack", "camera"]

Quaternion = dict[str, float]


class Project(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    title: str | None = None
    unit: Unit
    created_at: str | None = None
    updated_at: str | None = None


class PlanSummary(BaseModel):
    """One plan of the project.

    Positions on this plan line up with its image only when ``image_scale`` is 1
    and ``image_offset`` is (0, 0); the conversion to image pixels is on ``FloorPlan``.
    """

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    title: str | None = None
    ordering: int | float | None = None
    site_id: str | None = None
    scale_per_unit: float | None = Field(default=None, description="Plan units per metre, or per foot when imperial")
    scale_missing: bool
    image_scale: float | None = Field(description="The plan map's horizontal image scale, or None when not sent")
    image_offset: tuple[float, float] | None = Field(description="The plan map's image offset (x, y), or None")
    shape_counts: dict[str, int] = Field(default_factory=dict)


class WallType(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    name: str | None = None
    attenuation_db: float | None = None
    color: str | None = None
    transparent: bool | None = None
    overrides_variant: WallVariant | str | None = None


class Wall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    plan_id: str | None = None
    x1: float | None = None
    y1: float | None = None
    x2: float | None = None
    y2: float | None = None
    length: float | None = None
    variant: WallVariant | str | None = None
    wall_type_id: str | None = None


class PlacedDevice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    plan_id: str | None = None
    title: str | None = None
    product_id: str | None = None
    mac: str | None = None
    x: float | None = None
    y: float | None = None
    height: float | None = None
    mount: DeviceMount | str | None = None
    rotation: dict[str, Quaternion] | None = None


class ProjectSummary(BaseModel):
    project: Project
    unit: Unit
    plans: list[PlanSummary]
    wall_types: list[WallType]
    attenuation_object_types: list[dict[str, Any]]
    shapes: list[dict[str, Any]] | None = None


class WallPage(BaseModel):
    unit: Unit
    plan_id: str
    walls: list[Wall]
    total: int
    truncated: bool
    scale_missing: bool
    unreadable: int = Field(description="Walls without exactly two readable end points; their coordinates are None")


class PlacedDevicePage(BaseModel):
    unit: Unit
    plan_id: str
    devices: list[PlacedDevice]
    total: int
    truncated: bool
    scale_missing: bool


def _data(raw: Any) -> dict[str, Any]:
    """The project payload, given the response envelope or its ``data`` member."""
    body = as_dict(raw)
    inner = body.get("data") if "shapes" not in body and "project" not in body else body
    data = as_dict(inner)
    if not isinstance(data.get("project"), dict):
        raise UniFiMalformedResponseError("InnerSpace project response has no project")
    if not isinstance(data.get("plans"), list) or not isinstance(data.get("shapes"), list):
        raise UniFiMalformedResponseError("InnerSpace project response has no plans or shapes list")
    return data


def _shapes(data: dict[str, Any], plan_id: str | None, kind: str) -> list[dict[str, Any]]:
    return [
        shape
        for shape in as_list(data.get("shapes"))
        if isinstance(shape, dict) and shape.get("type") == kind and (plan_id is None or shape.get("planId") == plan_id)
    ]


def _wall_ends(shape: dict[str, Any]) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """The wall's two end points (x, y), or ``None`` unless it has exactly two readable ones."""
    position = shape.get("position")
    if not isinstance(position, list) or len(position) != 2:
        return None
    ends = []
    for point in position:
        x, y = number(as_dict(point).get("x")), number(as_dict(point).get("y"))
        if x is None or y is None:
            return None
        ends.append((x, y))
    return ends[0], ends[1]


def _device_point(shape: dict[str, Any]) -> dict[str, Any]:
    """The device's first position entry; later entries are never used in its place."""
    position = shape.get("position")
    return as_dict(position[0]) if isinstance(position, list) and position else {}


def _wall_metres(x: float, y: float, geometry: PlanGeometry) -> tuple[float, float] | None:
    """A wall point (plan units: image-centre origin, y up) as metres from the plan's top-left (vendor frame)."""
    if not geometry.usable:
        return None
    mx = plan_units_to_metres(x + geometry.width_px / 2, geometry.ppm)  # type: ignore[operator]
    my = plan_units_to_metres(geometry.height_px / 2 - y, geometry.ppm)  # type: ignore[operator]
    return None if mx is None or my is None else (mx, my)


def _device_metres(x: float, z: float, geometry: PlanGeometry) -> tuple[float, float] | None:
    """A device's metre position (x, z) as metres from the plan's top-left (vendor frame)."""
    if not geometry.usable:
        return None
    ppm = geometry.ppm
    mx = plan_units_to_metres(x * ppm + geometry.width_px / 2, ppm)  # type: ignore[operator]
    my = plan_units_to_metres(geometry.height_px / 2 + z * ppm, ppm)  # type: ignore[operator]
    return None if mx is None or my is None else (mx, my)


def _wall(shape: dict[str, Any], geometry: PlanGeometry, unit: Unit) -> tuple[Wall, bool]:
    """The wall and whether its end points were readable; an unreadable wall has no coordinates."""
    ends = _wall_ends(shape)
    start = end = None
    if ends:
        start = _wall_metres(*ends[0], geometry)
        end = _wall_metres(*ends[1], geometry)
    coords: dict[str, float | None] = dict.fromkeys(("x1", "y1", "x2", "y2", "length"))
    if start and end:
        coords = {
            "x1": length(start[0], unit),
            "y1": length(start[1], unit),
            "x2": length(end[0], unit),
            "y2": length(end[1], unit),
            "length": length(math.hypot(end[0] - start[0], end[1] - start[1]), unit),
        }
    wall = Wall(
        id=text(shape.get("id")),
        plan_id=text(shape.get("planId")),
        variant=text(shape.get("variant")),
        wall_type_id=text(shape.get("wallTypeId")),
        **coords,
    )
    return wall, ends is not None


def _quaternion(value: Any) -> Quaternion | None:
    parts = {axis: finite(as_dict(value).get(axis)) for axis in "wxyz"}
    return None if any(v is None for v in parts.values()) else parts  # type: ignore[return-value]


def _rotation(value: Any) -> dict[str, Quaternion] | None:
    rotation = {name: q for name, q in ((n, _quaternion(as_dict(value).get(n))) for n in ("base", "pov")) if q}
    return rotation or None


def _placed_device(shape: dict[str, Any], geometry: PlanGeometry, unit: Unit) -> PlacedDevice:
    point = _device_point(shape)
    px, py, pz = number(point.get("x")), number(point.get("y")), number(point.get("z"))
    height = length(py, unit)
    x = y = None
    placed = None if px is None or pz is None else _device_metres(px, pz, geometry)
    if placed:
        x, y = length(placed[0], unit), length(placed[1], unit)
    return PlacedDevice(
        id=text(shape.get("id")),
        plan_id=text(shape.get("planId")),
        title=text(shape.get("title")),
        product_id=text(shape.get("productId")),
        mac=canonical_mac(as_dict(shape.get("meta")).get("mac")),
        x=x,
        y=y,
        height=height,
        mount=text(shape.get("mount")),
        rotation=_rotation(shape.get("rotation")),
    )


def _wall_type(raw: Any) -> WallType:
    row = as_dict(raw)
    return WallType(
        id=text(row.get("id")),
        name=text(row.get("name")),
        attenuation_db=finite(row.get("attenuation")),
        color=text(row.get("color")),
        transparent=flag(row.get("transparent")),
        overrides_variant=text(row.get("overridesVariant")),
    )


def _plan_summary(plan: dict[str, Any], data: dict[str, Any], geometry: PlanGeometry, unit: Unit) -> PlanSummary:
    plan_id = plan.get("id")
    shapes = [s for s in as_list(data.get("shapes")) if isinstance(s, dict) and s.get("planId") == plan_id]
    image_scale, image_offset = image_transform(next((s for s in shapes if s.get("type") == "map"), None))
    return PlanSummary(
        id=text(plan_id),
        title=text(plan.get("title")),
        ordering=whole_or_number(plan.get("ordering")),
        site_id=text(plan.get("siteId")),
        scale_per_unit=scale_per_unit(geometry.ppm, unit),
        scale_missing=not geometry.usable,
        image_scale=image_scale,
        image_offset=image_offset,
        shape_counts=dict(Counter(s["type"] for s in shapes if isinstance(s.get("type"), str))),
    )


def _shape_listing(data: dict[str, Any], geometry: Mapping[str, PlanGeometry], unit: Unit) -> list[dict[str, Any]]:
    """Shapes reduced to identifiers and converted geometry; device meta (IP, MAC) is not carried."""
    listing = []
    for shape in as_list(data.get("shapes")):
        if not isinstance(shape, dict):
            continue
        plan_geometry = geometry.get(shape.get("planId"), NO_GEOMETRY)
        entry: dict[str, Any] = {
            "id": text(shape.get("id")),
            "type": text(shape.get("type")),
            "plan_id": text(shape.get("planId")),
        }
        if entry["type"] == "wall":
            entry.update(_wall(shape, plan_geometry, unit)[0].model_dump(exclude={"id", "plan_id"}))
        elif entry["type"] == "device":
            entry.update(_placed_device(shape, plan_geometry, unit).model_dump(exclude={"id", "plan_id", "mac"}))
        listing.append(entry)
    return listing


def project_summary_from_api(
    raw_project: Any, *, geometry: Mapping[str, PlanGeometry], unit: Unit, include_shapes: bool
) -> ProjectSummary:
    data = _data(raw_project)
    project = as_dict(data["project"])
    plans = sorted(
        (p for p in as_list(data.get("plans")) if isinstance(p, dict)),
        key=lambda p: finite(p.get("ordering")) if finite(p.get("ordering")) is not None else math.inf,
    )
    return ProjectSummary(
        project=Project(
            id=text(project.get("id")),
            title=text(project.get("title")),
            unit=unit,
            created_at=text(project.get("createdAt")),
            updated_at=text(project.get("updatedAt")),
        ),
        unit=unit,
        plans=[_plan_summary(p, data, geometry.get(p.get("id"), NO_GEOMETRY), unit) for p in plans],
        wall_types=[
            _wall_type(t)
            for t in as_list(data.get("wallTypes"))
            if isinstance(t, dict) and t.get("isDeleted") is not True
        ],
        attenuation_object_types=[t for t in as_list(data.get("attenuationObjectTypes")) if isinstance(t, dict)],
        shapes=_shape_listing(data, geometry, unit) if include_shapes else None,
    )


def walls_from_api(raw_project: Any, plan_id: str, *, geometry: PlanGeometry, unit: Unit, limit: int) -> WallPage:
    read = [_wall(s, geometry, unit) for s in _shapes(_data(raw_project), plan_id, "wall")]
    walls = [wall for wall, _ in read]
    return WallPage(
        unit=unit,
        plan_id=plan_id,
        walls=walls[:limit],
        total=len(walls),
        truncated=len(walls) > limit,
        scale_missing=not geometry.usable,
        unreadable=sum(1 for _, readable in read if not readable),
    )


def placed_devices_from_api(
    raw_project: Any, plan_id: str, *, geometry: PlanGeometry, unit: Unit, limit: int
) -> PlacedDevicePage:
    devices = [_placed_device(s, geometry, unit) for s in _shapes(_data(raw_project), plan_id, "device")]
    return PlacedDevicePage(
        unit=unit,
        plan_id=plan_id,
        devices=devices[:limit],
        total=len(devices),
        truncated=len(devices) > limit,
        scale_missing=not geometry.usable,
    )


def plan_maps_from_api(raw_project: Any) -> dict[str, dict[str, Any]]:
    """Each plan's first map shape, by plan id."""
    maps: dict[str, dict[str, Any]] = {}
    for shape in _data(raw_project)["shapes"]:
        if isinstance(shape, dict) and shape.get("type") == "map" and isinstance(shape.get("planId"), str):
            maps.setdefault(shape["planId"], shape)
    return maps


def plan_ids_from_api(raw_project: Any) -> set[str]:
    """Ids of the plans in the project response."""
    return {
        p["id"]
        for p in as_list(_data(raw_project).get("plans"))
        if isinstance(p, dict) and isinstance(p.get("id"), str)
    }
