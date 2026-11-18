"""Access points, switches and inventory devices from the documented API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from unifi_core.innerspace.models._coerce import as_dict, finite, length, text
from unifi_core.innerspace.units import Unit, plan_units_to_metres

ApMount = Literal["ceiling", "wall", "rack", "floor"]
DeviceStatus = Literal["online", "offline"]


class AccessPoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    name: str | None = None
    model: str | None = None
    mac: str | None = None
    serial: str | None = None
    floor_plan_id: str | None = None
    x: float | None = None
    y: float | None = None
    height: float | None = None
    azimuth: float | None = None
    mount: ApMount | str | None = None
    status: DeviceStatus | str | None = None
    unit: Unit


class Switch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    name: str | None = None
    model: str | None = None
    type: str | None = None
    mac: str | None = None
    serial: str | None = None
    floor_plan_id: str | None = None
    x: float | None = None
    y: float | None = None
    status: DeviceStatus | str | None = None
    unit: Unit


class InventoryDevice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    name: str | None = None
    model: str | None = None
    mac: str | None = None
    serial: str | None = None


def _pixel_length(pixels: Any, ppm: float | None, unit: Unit) -> float | None:
    value = finite(pixels)
    return None if value is None else length(plan_units_to_metres(value, ppm), unit)


def access_point_from_api(raw: Any, *, ppm: float | None, unit: Unit) -> AccessPoint:
    row = as_dict(raw)
    return AccessPoint(
        id=text(row.get("id")),
        name=text(row.get("name")),
        model=text(row.get("model")),
        mac=text(row.get("mac")),
        serial=text(row.get("serial")),
        floor_plan_id=text(row.get("floor_plan_id")),
        x=_pixel_length(row.get("x"), ppm, unit),
        y=_pixel_length(row.get("y"), ppm, unit),
        height=length(finite(row.get("height")), unit),
        azimuth=finite(row.get("azimuth")),
        mount=text(row.get("mount")),
        status=text(row.get("status")),
        unit=unit,
    )


def switch_from_api(raw: Any, *, ppm: float | None, unit: Unit) -> Switch:
    row = as_dict(raw)
    return Switch(
        id=text(row.get("id")),
        name=text(row.get("name")),
        model=text(row.get("model")),
        type=text(row.get("type")),
        mac=text(row.get("mac")),
        serial=text(row.get("serial")),
        floor_plan_id=text(row.get("floor_plan_id")),
        x=_pixel_length(row.get("x"), ppm, unit),
        y=_pixel_length(row.get("y"), ppm, unit),
        status=text(row.get("status")),
        unit=unit,
    )


def inventory_device_from_api(raw: Any) -> InventoryDevice:
    row = as_dict(raw)
    return InventoryDevice(
        id=text(row.get("id")),
        name=text(row.get("name")),
        model=text(row.get("model")),
        mac=text(row.get("mac")),
        serial=text(row.get("serial")),
    )
