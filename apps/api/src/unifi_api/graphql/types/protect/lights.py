"""Strawberry types for protect/lights (Phase 6 PR3 Task C).

The single read serializer (``LightSerializer``) maps to one Strawberry
class:

- ``Light`` — protect_list_lights (LIST). The manager helper
  ``_format_light_summary`` shapes plain dicts; we mirror its keys
  byte-for-byte.

Mutation ack (``protect_update_light``) stays in the serializer module —
that tool dispatches via the manager's preview path.
"""

from __future__ import annotations

from typing import Any

import strawberry


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


@strawberry.type(description="A UniFi Protect light (PIR-triggered floodlight).")
class Light:
    """Mirrors ``LightSerializer.serialize`` projection byte-for-byte."""

    id: strawberry.ID | None
    mac: str | None
    name: str | None
    model: str | None
    state: str | None
    is_pir_motion_detected: bool | None
    is_light_on: bool | None
    led_level: int | None
    sensitivity: int | None
    duration_seconds: int | None
    status_light: bool | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "model", "state", "is_light_on"],
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "Light":
        return cls(
            id=_get(obj, "id"),
            mac=_get(obj, "mac"),
            name=_get(obj, "name"),
            model=_get(obj, "model"),
            state=_get(obj, "state"),
            is_pir_motion_detected=_get(obj, "is_pir_motion_detected"),
            is_light_on=_get(obj, "is_light_on"),
            led_level=_get(obj, "led_level"),
            sensitivity=_get(obj, "sensitivity"),
            duration_seconds=_get(obj, "duration_seconds"),
            status_light=_get(obj, "status_light"),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "mac": self.mac,
            "name": self.name,
            "model": self.model,
            "state": self.state,
            "is_pir_motion_detected": self.is_pir_motion_detected,
            "is_light_on": self.is_light_on,
            "led_level": self.led_level,
            "sensitivity": self.sensitivity,
            "duration_seconds": self.duration_seconds,
            "status_light": self.status_light,
        }
