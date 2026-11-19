"""Tolerant readers for UniFi Drive payloads.

Drive reports unset fields as ``""``, ``0`` or ``null`` depending on the field
and firmware, and empty slots carry the same keys as populated ones. These
helpers read a value only when it has the expected type, so a surprising
payload yields an absent field instead of a validation error.
"""

from __future__ import annotations

from typing import Any


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def text(value: Any) -> str | None:
    """A non-empty string, or ``None``."""
    return value if isinstance(value, str) and value else None


def flag(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def number(value: Any) -> int | float | None:
    """An int or float that is not a bool, or ``None``."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def strings(value: Any) -> list[str]:
    return [item for item in as_list(value) if isinstance(item, str) and item]
