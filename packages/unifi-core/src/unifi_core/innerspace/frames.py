"""Coordinates for writes: the read frame back to the console's plan units.

Reads return positions in the project unit, measured from the plan's top-left
with y downward (see :class:`~unifi_core.innerspace.models.floor_plans.FloorPlan`).
The console stores walls, attenuation objects and scale lines in plan units:
image pixels with the origin at the image centre and y upward. With ``s``
plan units per metre, image width ``W`` and height ``H``, a frame point
(X, Y) in metres is ``x = X*s - W/2`` and ``y = H/2 - Y*s``.

Frame input lines up with the image only on an unshifted, unscaled map, so it
is refused on any other map, without a usable scale or image size, and outside
the image. ``coordinates="plan_units"`` takes the console's own values as
they are, with no unit conversion and no bounds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from unifi_core.exceptions import UniFiValidationError
from unifi_core.innerspace.models._coerce import as_dict, length, number
from unifi_core.innerspace.models.floor_plans import PlanGeometry, plan_geometry_from_api
from unifi_core.innerspace.models.project import _wall_metres
from unifi_core.innerspace.units import Unit, from_metres, to_metres

Coordinates = Literal["frame", "plan_units"]

# Plan units of slack at the image edge, for floating-point round-off of exact edge values.
_EDGE_SLACK = 1e-6


@dataclass(frozen=True)
class PlanFrame:
    """A plan's geometry and whether its map lines the frame up with the image."""

    geometry: PlanGeometry
    aligned: bool

    @classmethod
    def from_api(cls, floor_plan_row: Any, map_shape: Any) -> PlanFrame:
        """From the plan's documented floor-plan row and its map shape (``None`` when it has none)."""
        return cls(geometry=plan_geometry_from_api(floor_plan_row), aligned=map_is_plain(map_shape))


def map_is_plain(map_shape: Any) -> bool:
    """Whether the map has image scale (1, 1) and offset (0, 0); anything unreadable is not plain."""
    shape = as_dict(map_shape)
    scale, offset = as_dict(shape.get("imageScale")), as_dict(shape.get("imageOffset"))
    values = [number(scale.get("x")), number(scale.get("y")), number(offset.get("x")), number(offset.get("y"))]
    return bool(shape) and values == [1.0, 1.0, 0.0, 0.0]


def to_plan_point(
    x: float, y: float, *, frame: PlanFrame, unit: Unit, coordinates: Coordinates, operation: str
) -> tuple[float, float]:
    """A caller's point as console plan units; raises with fixed text when frame input cannot be placed."""
    if coordinates == "plan_units":
        return x, y
    geometry = frame.geometry
    if not frame.aligned:
        raise UniFiValidationError(
            f"{operation}: this plan's map is shifted or scaled, so frame coordinates do not line up with the "
            'image; pass coordinates="plan_units" with the console\'s own values instead'
        )
    if not geometry.usable:
        raise UniFiValidationError(
            f"{operation}: this plan has no usable scale or image size, so frame coordinates cannot be converted; "
            'pass coordinates="plan_units" instead'
        )
    ppm, width, height = geometry.ppm, geometry.width_px, geometry.height_px
    px = to_metres(x, unit) * ppm - width / 2  # type: ignore[operator]
    py = height / 2 - to_metres(y, unit) * ppm  # type: ignore[operator]
    if abs(px) > width / 2 + _EDGE_SLACK or abs(py) > height / 2 + _EDGE_SLACK:  # type: ignore[operator]
        raise UniFiValidationError(f"{operation}: a point lies outside the plan image")
    return px, py


def from_plan_point(
    x: float, y: float, *, geometry: PlanGeometry, unit: Unit, exact: bool = False
) -> tuple[float, float] | None:
    """Console plan units as a frame point in ``unit``, or ``None`` without geometry.

    Rounded like the reads, unless ``exact``: a value a caller sends back unchanged keeps full precision.
    """
    metres = _wall_metres(x, y, geometry)
    if metres is None:
        return None
    if exact:
        return from_metres(metres[0], unit), from_metres(metres[1], unit)  # type: ignore[return-value]
    return length(metres[0], unit), length(metres[1], unit)  # type: ignore[return-value]
