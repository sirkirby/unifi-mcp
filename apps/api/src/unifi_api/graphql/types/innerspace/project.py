"""The InnerSpace project, and the walls and placed devices of one plan."""

from __future__ import annotations

import strawberry
from strawberry.scalars import JSON

from unifi_api.graphql.types.innerspace._base import DESCRIPTION, Projection


@strawberry.type(description=DESCRIPTION)
class InnerSpaceProjectInfo(Projection):
    id: str | None = strawberry.field(description="InnerSpace project id")
    title: str | None = strawberry.field(description="Project title")
    unit: str = strawberry.field(description="Length unit of the result: metric or imperial")
    created_at: str | None = strawberry.field(description="When the project was created")
    updated_at: str | None = strawberry.field(description="When the project was last updated")


@strawberry.type(description=DESCRIPTION)
class InnerSpacePlanSummary(Projection):
    id: str | None = strawberry.field(description="InnerSpace floor plan id")
    title: str | None = strawberry.field(description="Plan title")
    ordering: float | None = strawberry.field(description="Plan order in the project")
    site_id: str | None = strawberry.field(description="InnerSpace site id")
    scale_per_unit: float | None = strawberry.field(description="Plan units per metre, or per foot when imperial")
    scale_missing: bool = strawberry.field(description="True when the plan has no usable scale")
    image_scale: float | None = strawberry.field(description="The plan map's horizontal image scale, if sent")
    image_offset: list[float] | None = strawberry.field(description="The plan map's image offset (x, y)")
    shape_counts: JSON = strawberry.field(description="Number of shapes on the plan, by shape type")


@strawberry.type(description=DESCRIPTION)
class InnerSpaceWallType(Projection):
    id: str | None = strawberry.field(description="Wall type id")
    name: str | None = strawberry.field(description="Wall type name")
    attenuation_db: float | None = strawberry.field(description="Attenuation in dB")
    color: str | None = strawberry.field(description="Display colour")
    transparent: bool | None = strawberry.field(description="Whether the wall type is drawn transparent")
    overrides_variant: str | None = strawberry.field(description="Wall variant this type overrides")


@strawberry.type(description=DESCRIPTION)
class InnerSpaceProject(Projection):
    project: InnerSpaceProjectInfo = strawberry.field(description="Project identity")
    unit: str = strawberry.field(description="Length unit of the result: metric or imperial")
    plans: list[InnerSpacePlanSummary] = strawberry.field(description="The project's plans, in order")
    wall_types: list[InnerSpaceWallType] = strawberry.field(description="Wall types that are not deleted")
    attenuation_object_types: JSON = strawberry.field(description="Attenuation object types as the console sent them")
    shapes: JSON | None = strawberry.field(
        description="Every shape with converted geometry, when requested; device addresses are not carried"
    )

    _nested = {
        "project": (InnerSpaceProjectInfo, False),
        "plans": (InnerSpacePlanSummary, True),
        "wall_types": (InnerSpaceWallType, True),
    }
    _columns = ["unit"]


@strawberry.type(description=DESCRIPTION)
class InnerSpaceWall(Projection):
    id: str | None = strawberry.field(description="Wall id")
    plan_id: str | None = strawberry.field(description="InnerSpace floor plan id")
    x1: float | None = strawberry.field(description="Start x from the plan's left edge, in the unit")
    y1: float | None = strawberry.field(description="Start y from the plan's top edge, in the unit")
    x2: float | None = strawberry.field(description="End x from the plan's left edge, in the unit")
    y2: float | None = strawberry.field(description="End y from the plan's top edge, in the unit")
    length: float | None = strawberry.field(description="Wall length, in the unit")
    variant: str | None = strawberry.field(description="Wall material variant")
    wall_type_id: str | None = strawberry.field(description="Wall type id")


@strawberry.type(description=DESCRIPTION)
class InnerSpaceWallPage(Projection):
    unit: str = strawberry.field(description="Length unit of the result: metric or imperial")
    plan_id: str = strawberry.field(description="InnerSpace floor plan id")
    walls: list[InnerSpaceWall] = strawberry.field(description="Walls, at most limit")
    limit: int = strawberry.field(description="The limit the list was cut at")
    total: int = strawberry.field(description="Walls on the plan")
    truncated: bool = strawberry.field(description="Whether the list was cut at limit")
    scale_missing: bool = strawberry.field(description="True when the plan has no usable scale")
    unreadable: int = strawberry.field(description="Walls without two readable end points; coordinates are null")

    _nested = {"walls": (InnerSpaceWall, True)}
    _columns = ["plan_id", "total", "truncated"]


@strawberry.type(description=DESCRIPTION)
class InnerSpacePlacedDevice(Projection):
    id: str | None = strawberry.field(description="Placed device id")
    plan_id: str | None = strawberry.field(description="InnerSpace floor plan id")
    title: str | None = strawberry.field(description="Device title")
    product_id: str | None = strawberry.field(description="Product id")
    mac: str | None = strawberry.field(description="Device MAC address")
    x: float | None = strawberry.field(description="Distance from the plan's left edge, in the unit")
    y: float | None = strawberry.field(description="Distance from the plan's top edge, in the unit")
    height: float | None = strawberry.field(description="Mounting height, in the unit")
    mount: str | None = strawberry.field(description="Mount: ceiling, wall, floor or rack")
    rotation: JSON | None = strawberry.field(description="Base and point-of-view rotation quaternions")


@strawberry.type(description=DESCRIPTION)
class InnerSpacePlacedDevicePage(Projection):
    unit: str = strawberry.field(description="Length unit of the result: metric or imperial")
    plan_id: str = strawberry.field(description="InnerSpace floor plan id")
    devices: list[InnerSpacePlacedDevice] = strawberry.field(description="Placed devices, at most limit")
    limit: int = strawberry.field(description="The limit the list was cut at")
    total: int = strawberry.field(description="Devices on the plan")
    truncated: bool = strawberry.field(description="Whether the list was cut at limit")
    scale_missing: bool = strawberry.field(description="True when the plan has no usable scale")

    _nested = {"devices": (InnerSpacePlacedDevice, True)}
    _columns = ["plan_id", "total", "truncated"]
