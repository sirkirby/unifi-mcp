"""Length conversion between the app's native metres and the project's display unit."""

from __future__ import annotations

import math
from typing import Any, Literal, get_args

from unifi_core.exceptions import UniFiMalformedResponseError

Unit = Literal["metric", "imperial"]

# The app's own factors.
FEET_PER_METRE = 3.2808
SQ_FEET_PER_SQ_METRE = 10.7639


def from_metres(value: float | None, unit: Unit) -> float | None:
    if value is None:
        return None
    return value * FEET_PER_METRE if unit == "imperial" else value


def to_metres(value: float | None, unit: Unit) -> float | None:
    if value is None:
        return None
    return value / FEET_PER_METRE if unit == "imperial" else value


def plan_units_to_metres(value: float, ppm: float | None) -> float | None:
    """Pixels to metres, or ``None`` unless ``ppm`` is finite and positive."""
    if ppm is None or not math.isfinite(ppm) or ppm <= 0:
        return None
    return value / ppm


def parse_unit(raw: Any) -> Unit:
    """Validate a project unit; an unknown or missing value is never defaulted."""
    if isinstance(raw, str) and raw in get_args(Unit):
        return raw  # type: ignore[return-value]
    raise UniFiMalformedResponseError("InnerSpace project unit is missing or not recognised")
