"""The InnerSpace project: plans, wall types, walls and placed devices.

Every coordinate uses one frame: distance from the top-left of the plan image,
x to the right and y downward, measured in the project unit (the documented
API's frame; the map's image offset and scale are not applied). The controller
sends walls in plan units (origin at the image centre, y up) and devices in
metres with the height on the y axis, so both are converted here.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from unifi_core.exceptions import UniFiMalformedResponseError
from unifi_core.innerspace.models._coerce import as_dict, as_list, finite, flag, length, text
from unifi_core.innerspace.models.floor_plans import NO_GEOMETRY, PlanGeometry, scale_per_unit
from unifi_core.innerspace.units import Unit, plan_units_to_metres

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
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    title: str | None = None
    ordering: int | None = None
    site_id: str | None = None
    scale_per_unit: float | None = Field(default=None, description="Plan units per metre, or per foot when imperial")
    scale_missing: bool
    image_scale: float = Field(description="The map's horizontal image scale")
    image_offset: tuple[float, float] = Field(description="The map's image offset (x, y)")
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
    return data


def _shapes(data: dict[str, Any], plan_id: str | None, kind: str) -> list[dict[str, Any]]:
    return [
        shape
        for shape in as_list(data.get("shapes"))
        if isinstance(shape, dict) and shape.get("type") == kind and (plan_id is None or shape.get("planId") == plan_id)
    ]


def _points(shape: dict[str, Any]) -> list[tuple[float, float, float]]:
    points = []
    for point in as_list(shape.get("position")):
        p = as_dict(point)
        x, y, z = finite(p.get("x")), finite(p.get("y")), finite(p.get("z", 0))
        if x is not None and y is not None and z is not None:
            points.append((x, y, z))
    return points


def _wall_metres(x: float, y: float, geometry: PlanGeometry) -> tuple[float, float] | None:
    """A wall point (plan units: image-centre origin, y up) as metres from the image's top-left."""
    if not geometry.usable:
        return None
    mx = plan_units_to_metres(x + geometry.width_px / 2, geometry.ppm)  # type: ignore[operator]
    my = plan_units_to_metres(geometry.height_px / 2 - y, geometry.ppm)  # type: ignore[operator]
    return None if mx is None or my is None else (mx, my)


def _device_metres(x: float, z: float, geometry: PlanGeometry) -> tuple[float, float] | None:
    """A device's metre position (x, z) as metres from the image's top-left."""
    if not geometry.usable:
        return None
    ppm = geometry.ppm
    mx = plan_units_to_metres(x * ppm + geometry.width_px / 2, ppm)  # type: ignore[operator]
    my = plan_units_to_metres(geometry.height_px / 2 + z * ppm, ppm)  # type: ignore[operator]
    return None if mx is None or my is None else (mx, my)


def _wall(shape: dict[str, Any], geometry: PlanGeometry, unit: Unit) -> Wall | None:
    points = _points(shape)
    if len(points) < 2:
        return None
    start = _wall_metres(points[0][0], points[0][1], geometry)
    end = _wall_metres(points[1][0], points[1][1], geometry)
    coords: dict[str, float | None] = dict.fromkeys(("x1", "y1", "x2", "y2", "length"))
    if start and end:
        coords = {
            "x1": length(start[0], unit),
            "y1": length(start[1], unit),
            "x2": length(end[0], unit),
            "y2": length(end[1], unit),
            "length": length(math.hypot(end[0] - start[0], end[1] - start[1]), unit),
        }
    return Wall(
        id=text(shape.get("id")),
        plan_id=text(shape.get("planId")),
        variant=text(shape.get("variant")),
        wall_type_id=text(shape.get("wallTypeId")),
        **coords,
    )


def _quaternion(value: Any) -> Quaternion | None:
    parts = {axis: finite(as_dict(value).get(axis)) for axis in "wxyz"}
    return None if any(v is None for v in parts.values()) else parts  # type: ignore[return-value]


def _rotation(value: Any) -> dict[str, Quaternion] | None:
    rotation = {name: q for name, q in ((n, _quaternion(as_dict(value).get(n))) for n in ("base", "pov")) if q}
    return rotation or None


def _placed_device(shape: dict[str, Any], geometry: PlanGeometry, unit: Unit) -> PlacedDevice:
    points = _points(shape)
    x = y = height = None
    if points:
        px, py, pz = points[0]
        height = length(py, unit)
        placed = _device_metres(px, pz, geometry)
        if placed:
            x, y = length(placed[0], unit), length(placed[1], unit)
    return PlacedDevice(
        id=text(shape.get("id")),
        plan_id=text(shape.get("planId")),
        title=text(shape.get("title")),
        product_id=text(shape.get("productId")),
        mac=text(as_dict(shape.get("meta")).get("mac")),
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
    image_map = next((s for s in shapes if s.get("type") == "map"), {})
    offset = as_dict(image_map.get("imageOffset"))
    ordering = finite(plan.get("ordering"))
    return PlanSummary(
        id=text(plan_id),
        title=text(plan.get("title")),
        ordering=int(ordering) if ordering is not None else None,
        site_id=text(plan.get("siteId")),
        scale_per_unit=scale_per_unit(geometry.ppm, unit),
        scale_missing=not geometry.usable,
        image_scale=finite(as_dict(image_map.get("imageScale")).get("x")) or 1.0,
        image_offset=(finite(offset.get("x")) or 0.0, finite(offset.get("y")) or 0.0),
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
        if entry["type"] == "wall" and (wall := _wall(shape, plan_geometry, unit)):
            entry.update(wall.model_dump(exclude={"id", "plan_id"}))
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
    walls = [w for s in _shapes(_data(raw_project), plan_id, "wall") if (w := _wall(s, geometry, unit))]
    return WallPage(
        unit=unit,
        plan_id=plan_id,
        walls=walls[:limit],
        total=len(walls),
        truncated=len(walls) > limit,
        scale_missing=not geometry.usable,
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
