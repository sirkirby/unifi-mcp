"""InnerSpace access points, switches and unplaced inventory."""

from __future__ import annotations

import strawberry

from unifi_api.graphql.types.innerspace._base import DESCRIPTION, Projection


@strawberry.type(description=DESCRIPTION)
class InnerSpaceAccessPoint(Projection):
    id: str | None = strawberry.field(description="InnerSpace device id")
    name: str | None = strawberry.field(description="Device name")
    model: str | None = strawberry.field(description="Device model")
    mac: str | None = strawberry.field(description="Device MAC address")
    serial: str | None = strawberry.field(description="Device serial number")
    floor_plan_id: str | None = strawberry.field(description="InnerSpace floor plan id")
    x: float | None = strawberry.field(description="Distance from the plan's left edge, in the unit")
    y: float | None = strawberry.field(description="Distance from the plan's top edge, in the unit")
    scale_missing: bool = strawberry.field(description="True when the plan has no usable scale, so x and y are null")
    height: float | None = strawberry.field(description="Mounting height, in the unit")
    azimuth: float | None = strawberry.field(description="Azimuth in degrees")
    mount: str | None = strawberry.field(description="Mount: ceiling, wall, rack or floor")
    status: str | None = strawberry.field(description="online or offline")
    unit: str = strawberry.field(description="Length unit of the result: metric or imperial")

    _identity = "id"
    _columns = ["name", "model", "status"]


@strawberry.type(description=DESCRIPTION)
class InnerSpaceSwitch(Projection):
    id: str | None = strawberry.field(description="InnerSpace device id")
    name: str | None = strawberry.field(description="Device name")
    model: str | None = strawberry.field(description="Device model")
    type: str | None = strawberry.field(description="Switch type")
    mac: str | None = strawberry.field(description="Device MAC address")
    serial: str | None = strawberry.field(description="Device serial number")
    floor_plan_id: str | None = strawberry.field(description="InnerSpace floor plan id")
    x: float | None = strawberry.field(description="Distance from the plan's left edge, in the unit")
    y: float | None = strawberry.field(description="Distance from the plan's top edge, in the unit")
    scale_missing: bool = strawberry.field(description="True when the plan has no usable scale, so x and y are null")
    status: str | None = strawberry.field(description="online or offline")
    unit: str = strawberry.field(description="Length unit of the result: metric or imperial")

    _identity = "id"
    _columns = ["name", "model", "status"]


@strawberry.type(description=DESCRIPTION)
class InnerSpaceInventoryDevice(Projection):
    id: str | None = strawberry.field(description="InnerSpace device id")
    name: str | None = strawberry.field(description="Device name")
    model: str | None = strawberry.field(description="Device model")
    mac: str | None = strawberry.field(description="Device MAC address")
    serial: str | None = strawberry.field(description="Device serial number")

    _identity = "id"
    _columns = ["name", "model", "serial"]
