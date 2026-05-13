"""Shared field model for Protect sensors (motion / leak / temperature).

All fields are read-only: there is no update_sensor tool. The model
exists so list/get tools can shape output through a typed contract and
the cross-layer symmetry test can verify the Strawberry type's field
set against this single source of truth.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class Sensor(BaseModel):
    """Canonical Protect sensor model (read-only)."""

    id: Optional[str] = Field(default=None, description="Sensor UUID", json_schema_extra={"mutable": False})
    mac: Optional[str] = Field(default=None, description="MAC address", json_schema_extra={"mutable": False})
    name: Optional[str] = Field(default=None, description="Display name", json_schema_extra={"mutable": False})
    type: Optional[str] = Field(default=None, description="Sensor type (motion, leak, temperature, etc.)", json_schema_extra={"mutable": False})
    battery_status: Optional[str] = Field(default=None, description="Battery state summary", json_schema_extra={"mutable": False})
    humidity_status: Optional[str] = Field(default=None, description="Humidity reading summary", json_schema_extra={"mutable": False})
    light_status: Optional[str] = Field(default=None, description="Ambient light reading summary", json_schema_extra={"mutable": False})
    motion_detected_at: Optional[str] = Field(default=None, description="ISO timestamp of last motion event", json_schema_extra={"mutable": False})


MUTABLE_FIELDS = frozenset(
    name for name, info in Sensor.model_fields.items()
    if (info.json_schema_extra or {}).get("mutable") is not False
)
READ_ONLY_FIELDS = frozenset(
    name for name, info in Sensor.model_fields.items()
    if (info.json_schema_extra or {}).get("mutable") is False
)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _stringify_dt(value: Any) -> Optional[str]:
    """Coerce a datetime-ish value to ISO 8601 string for serialization."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:
            return None
    return str(value)


def from_controller(raw: Any) -> Sensor:
    """Build a Sensor from a uiprotect / manager dict or object."""
    return Sensor(
        id=_get(raw, "id"),
        mac=_get(raw, "mac"),
        name=_get(raw, "name"),
        type=_get(raw, "type"),
        battery_status=_get(raw, "battery_status"),
        humidity_status=_get(raw, "humidity_status"),
        light_status=_get(raw, "light_status"),
        motion_detected_at=_stringify_dt(_get(raw, "motion_detected_at")),
    )
