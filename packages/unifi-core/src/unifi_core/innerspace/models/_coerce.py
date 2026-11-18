"""Tolerant readers for InnerSpace payloads: a value is read only when it has the expected type."""

from __future__ import annotations

import math
from typing import Any

from unifi_core.innerspace.units import Unit, from_metres


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def text(value: Any) -> str | None:
    """A non-empty string, or ``None``."""
    return value if isinstance(value, str) and value else None


def flag(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def finite(value: Any) -> float | None:
    """A finite number, accepting a numeric string; booleans, NaN and infinity give ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def length(metres: float | None, unit: Unit) -> float | None:
    """A length in metres as a rounded value in the project unit."""
    converted = from_metres(metres, unit)
    return None if converted is None else round(converted, 4)
