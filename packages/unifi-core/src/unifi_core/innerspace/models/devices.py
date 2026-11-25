"""Access points, switches and inventory devices from the documented API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from unifi_core.innerspace.models._coerce import as_dict, finite, length, text
from unifi_core.innerspace.units import UNIT_DESCRIPTION, Unit, plan_units_to_metres
from unifi_core.mac import canonical_mac

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
    scale_missing: bool = Field(description="True when the device's plan has no usable scale, so x and y are None")
    height: float | None = None
    azimuth: float | None = None
    mount: ApMount | str | None = None
    status: DeviceStatus | str | None = None
    unit: Unit = Field(description=UNIT_DESCRIPTION)


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
    scale_missing: bool = Field(description="True when the device's plan has no usable scale, so x and y are None")
    status: DeviceStatus | str | None = None
    unit: Unit = Field(description=UNIT_DESCRIPTION)


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


def _scale_missing(ppm: float | None) -> bool:
    return plan_units_to_metres(1.0, ppm) is None


def access_point_from_api(raw: Any, *, ppm: float | None, unit: Unit) -> AccessPoint:
    row = as_dict(raw)
    return AccessPoint(
        id=text(row.get("id")),
        name=text(row.get("name")),
        model=text(row.get("model")),
        mac=canonical_mac(row.get("mac")),
        serial=text(row.get("serial")),
        floor_plan_id=text(row.get("floor_plan_id")),
        x=_pixel_length(row.get("x"), ppm, unit),
        y=_pixel_length(row.get("y"), ppm, unit),
        scale_missing=_scale_missing(ppm),
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
        mac=canonical_mac(row.get("mac")),
        serial=text(row.get("serial")),
        floor_plan_id=text(row.get("floor_plan_id")),
        x=_pixel_length(row.get("x"), ppm, unit),
        y=_pixel_length(row.get("y"), ppm, unit),
        scale_missing=_scale_missing(ppm),
        status=text(row.get("status")),
        unit=unit,
    )


def inventory_device_from_api(raw: Any) -> InventoryDevice:
    row = as_dict(raw)
    return InventoryDevice(
        id=text(row.get("id")),
        name=text(row.get("name")),
        model=text(row.get("model")),
        mac=canonical_mac(row.get("mac")),
        serial=text(row.get("serial")),
    )
