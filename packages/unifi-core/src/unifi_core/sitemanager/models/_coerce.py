"""Tolerant readers for Site Manager payloads.

Several response fields (``reportedState``, ``meta``, ``statistics``) are not
specified and vary with the console's UniFi OS version, and documented fields
arrive as ``""`` or ``null`` when unset. These helpers read a value only when
it has the expected type, so a surprising payload yields an absent field
instead of a validation error.
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
    """An int or float; booleans are not numbers here."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def timestamp(value: Any) -> str | int | None:
    """A timestamp exactly as the API sent it: an RFC 3339 string or epoch milliseconds."""
    return text(value) if isinstance(value, str) else number(value)  # type: ignore[return-value]


def strings(value: Any) -> list[str]:
    return [item for item in as_list(value) if isinstance(item, str) and item]


def scalars(value: Any) -> dict[str, Any]:
    """The string, number and boolean entries of a mapping, dropping nested structures."""
    return {
        key: item
        for key, item in as_dict(value).items()
        if isinstance(key, str) and isinstance(item, (str, int, float, bool))
    }
