"""Strawberry types for protect/chimes.

Phase 6 PR3 Task A migration target. The single read serializer
(``ChimeSerializer``) maps to one Strawberry class:

- ``Chime`` — protect_list_chimes (LIST). The manager helper
  ``_format_chime_summary`` shapes plain dicts; we mirror its keys with
  ``camera_ids`` renamed to ``paired_cameras`` per the spec, matching the
  prior serializer's contract.

Mutation ack (trigger/update) stays in the serializer module —
those tools dispatch via the manager's preview path.
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


@strawberry.type(description="A UniFi Protect chime (paired-camera doorbell ringer).")
class Chime:
    id: strawberry.ID | None
    mac: str | None
    name: str | None
    model: str | None
    type: str | None
    state: str | None
    is_connected: bool | None
    firmware_version: str | None
    volume: int | None
    repeat_times: int | None
    paired_cameras: list[str]
    ring_settings: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    available_tracks: strawberry.scalars.JSON | None  # type: ignore[name-defined]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "model", "state", "volume"],
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "Chime":
        return cls(
            id=_get(obj, "id"),
            mac=_get(obj, "mac"),
            name=_get(obj, "name"),
            model=_get(obj, "model"),
            type=_get(obj, "type"),
            state=_get(obj, "state"),
            is_connected=_get(obj, "is_connected"),
            firmware_version=_get(obj, "firmware_version"),
            volume=_get(obj, "volume"),
            repeat_times=_get(obj, "repeat_times"),
            paired_cameras=_get(obj, "camera_ids") or [],
            ring_settings=_get(obj, "ring_settings") or [],
            available_tracks=_get(obj, "available_tracks") or [],
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: v for k, v in out.items() if not k.startswith("_") and not callable(v)}
