"""Strawberry types for access/schedules.

Phase 6 PR4 Task B migration target. The single read serializer
(``ScheduleSerializer``) maps to one Strawberry class:

- ``Schedule`` — access_list_schedules

Tool-keyed only (the schedule serializer never registered a resource
path; LIST only — there is no detail/get tool for schedules in Phase
4A). The access manifest has no schedule mutation tools today, so the
serializer module ``serializers/access/schedules.py`` is removed
entirely once this migration lands.

PolicyManager.list_schedules returns dicts from the proxy
``schedules?expand[]=week_schedule`` endpoint. The ``week_schedule``
field is surfaced as ``weekly_pattern`` for a stable catalog field name
(mirrors the prior serializer byte-for-byte).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


def _is_enabled(obj: Any) -> bool:
    explicit = _get(obj, "enabled")
    if isinstance(explicit, bool):
        return explicit
    status = _get(obj, "status")
    if isinstance(status, str):
        return status.lower() in {"active", "enabled", "on"}
    return True


@strawberry.type(description="A UniFi Access schedule (weekly access window).")
class Schedule:
    """Mirrors ``ScheduleSerializer.serialize`` projection byte-for-byte."""

    id: strawberry.ID | None
    name: str | None
    weekly_pattern: strawberry.scalars.JSON  # type: ignore[name-defined]
    enabled: bool

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "enabled"],
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "Schedule":
        return cls(
            id=_get(obj, "id"),
            name=_get(obj, "name"),
            weekly_pattern=_get(obj, "weekly_pattern") or _get(obj, "week_schedule") or {},
            enabled=_is_enabled(obj),
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: v for k, v in out.items() if not k.startswith("_") and not callable(v)}
