"""Floor plans and the image geometry that turns plan units into real lengths."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from unifi_core.innerspace.models._coerce import as_dict, finite, text
from unifi_core.innerspace.units import FEET_PER_METRE, Unit, plan_units_to_metres

_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


@dataclass(frozen=True)
class PlanGeometry:
    """Pixels per metre and image size of one plan; ``None`` where the controller sent none."""

    ppm: float | None
    width_px: float | None
    height_px: float | None

    @property
    def usable(self) -> bool:
        return (
            plan_units_to_metres(1.0, self.ppm) is not None and self.width_px is not None and self.height_px is not None
        )


NO_GEOMETRY = PlanGeometry(ppm=None, width_px=None, height_px=None)


def plan_geometry_from_api(raw: Any) -> PlanGeometry:
    row = as_dict(raw)
    return PlanGeometry(
        ppm=finite(row.get("ppm")), width_px=finite(row.get("width")), height_px=finite(row.get("height"))
    )


def scale_per_unit(ppm: float | None, unit: Unit) -> float | None:
    """Plan units per metre (metric) or per foot (imperial); ``None`` without a usable scale."""
    if plan_units_to_metres(1.0, ppm) is None:
        return None
    return ppm / FEET_PER_METRE if unit == "imperial" else ppm  # type: ignore[operator]


class FloorPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    name: str | None = None
    floor_number: int | None = None
    scale_per_unit: float | None = Field(default=None, description="Plan units per metre, or per foot when imperial")
    width_px: float | None = None
    height_px: float | None = None
    origin_x: float | None = None
    origin_y: float | None = None
    site_id: str | None = None
    image_filename: str | None = Field(default=None, description="Asset file name taken from the image URL")
    unit: Unit


def _image_filename(url: Any) -> str | None:
    """The last path segment of the image URL, only when it is one plain file name."""
    if not isinstance(url, str):
        return None
    name = url.split("?", 1)[0].rsplit("/", 1)[-1]
    return name if _FILENAME.fullmatch(name) and ".." not in name else None


def floor_plan_from_api(raw: Any, *, unit: Unit) -> FloorPlan:
    row = as_dict(raw)
    floor = finite(row.get("floor_number"))
    return FloorPlan(
        id=text(row.get("id")),
        name=text(row.get("name")),
        floor_number=int(floor) if floor is not None else None,
        scale_per_unit=scale_per_unit(finite(row.get("ppm")), unit),
        width_px=finite(row.get("width")),
        height_px=finite(row.get("height")),
        origin_x=finite(row.get("origin_x")),
        origin_y=finite(row.get("origin_y")),
        site_id=text(row.get("site_id")),
        image_filename=_image_filename(row.get("image_url")),
        unit=unit,
    )
