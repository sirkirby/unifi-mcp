"""Floor plans and the image geometry that turns plan units into real lengths.

Positions use the documented API's plan frame: distance from the plan's
top-left in the vendor's coordinates, x to the right and y downward. It lines
up with the plan image only when ``image_scale`` is 1 and ``image_offset`` is
(0, 0); otherwise convert as described on :class:`FloorPlan`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from unifi_core.innerspace.models._coerce import as_dict, finite, number, text, whole_or_number
from unifi_core.innerspace.units import FEET_PER_METRE, UNIT_DESCRIPTION, Unit, plan_units_to_metres

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


def image_transform(image_map: Any) -> tuple[float | None, tuple[float, float] | None]:
    """The map shape's image scale and offset (x, y) as the console sent them; ``None`` where absent.

    The scale is one number: it is the x scale when the map sends no y scale or the same one, and
    ``None`` when the y scale differs, rather than a scale that would skew every y placed with it.
    ``None`` therefore means either case; positions can't be placed on the image in either.
    """
    shape = as_dict(image_map)
    offset = as_dict(shape.get("imageOffset"))
    ox, oy = number(offset.get("x")), number(offset.get("y"))
    scales = as_dict(shape.get("imageScale"))
    scale, scale_y = number(scales.get("x")), number(scales.get("y"))
    if scale is not None and scale_y is not None and not math.isclose(scale, scale_y):
        scale = None
    return scale, None if ox is None or oy is None else (ox, oy)


class FloorPlan(BaseModel):
    """One floor plan, with lengths in the project unit.

    To place a returned position (x, y) on the plan image of ``width_px`` W and
    ``height_px`` H, with s = ``image_scale``, (ox, oy) = ``image_offset`` and
    k = ``scale_per_unit``: back to vendor plan units, plan_x = x*k - W/2 and
    plan_y = H/2 - y*k; then px_img = (plan_x - ox)/s + W/2 and
    py_img = H/2 - (plan_y - oy)/s. With s = 1 and (0, 0) this is px_img = x*k
    and py_img = y*k.
    """

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    name: str | None = None
    floor_number: int | float | None = None
    scale_per_unit: float | None = Field(default=None, description="Plan units per metre, or per foot when imperial")
    width_px: float | None = None
    height_px: float | None = None
    origin_x: float | None = None
    origin_y: float | None = None
    site_id: str | None = None
    image_filename: str | None = Field(default=None, description="Asset file name taken from the image URL")
    image_scale: float | None = Field(
        default=None, description="The plan map's image scale, or None when not sent or when its y scale differs from x"
    )
    image_offset: tuple[float, float] | None = Field(default=None, description="The plan map's image offset (x, y)")
    unit: Unit = Field(description=UNIT_DESCRIPTION)


def _image_filename(url: Any) -> str | None:
    """The last path segment of the image URL, only when it is one plain file name."""
    if not isinstance(url, str):
        return None
    name = url.split("?", 1)[0].rsplit("/", 1)[-1]
    return name if _FILENAME.fullmatch(name) and ".." not in name else None


def floor_plan_from_api(raw: Any, *, unit: Unit, image_map: Any = None) -> FloorPlan:
    """Build a plan from its floor-plan row and, when given, its map shape from the project."""
    row = as_dict(raw)
    image_scale, image_offset = image_transform(image_map)
    return FloorPlan(
        id=text(row.get("id")),
        name=text(row.get("name")),
        floor_number=whole_or_number(row.get("floor_number")),
        scale_per_unit=scale_per_unit(finite(row.get("ppm")), unit),
        width_px=finite(row.get("width")),
        height_px=finite(row.get("height")),
        origin_x=finite(row.get("origin_x")),
        origin_y=finite(row.get("origin_y")),
        site_id=text(row.get("site_id")),
        image_filename=_image_filename(row.get("image_url")),
        image_scale=image_scale,
        image_offset=image_offset,
        unit=unit,
    )
