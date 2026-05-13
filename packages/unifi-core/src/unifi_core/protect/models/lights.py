"""Shared field model for Protect lights (PIR-triggered floodlights)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class Light(BaseModel):
    """Canonical Protect light model."""

    # Read-only
    id: Optional[str] = Field(default=None, description="Light UUID", json_schema_extra={"mutable": False})
    mac: Optional[str] = Field(default=None, description="MAC address", json_schema_extra={"mutable": False})
    model: Optional[str] = Field(default=None, description="Light model", json_schema_extra={"mutable": False})
    state: Optional[str] = Field(default=None, description="Connection state", json_schema_extra={"mutable": False})
    is_pir_motion_detected: Optional[bool] = Field(default=None, description="Whether PIR sees motion now", json_schema_extra={"mutable": False})

    # Mutable
    name: Optional[str] = Field(default=None, description="Display name")
    is_light_on: Optional[bool] = Field(default=None, description="Whether the light is currently on (writable: turns light on/off)")
    led_level: Optional[int] = Field(default=None, ge=1, le=6, description="LED brightness level (1-6)")
    sensitivity: Optional[int] = Field(default=None, ge=0, le=100, description="PIR motion sensitivity (0-100)")
    duration_seconds: Optional[int] = Field(default=None, ge=15, le=900, description="How long the light stays on after motion (15-900s)")
    status_light: Optional[bool] = Field(default=None, description="Whether the status indicator LED is on")


MUTABLE_FIELDS = frozenset(
    name for name, info in Light.model_fields.items()
    if (info.json_schema_extra or {}).get("mutable") is not False
)
READ_ONLY_FIELDS = frozenset(
    name for name, info in Light.model_fields.items()
    if (info.json_schema_extra or {}).get("mutable") is False
)

# Map model field names that differ from controller-side keys for update payloads.
_CONTROLLER_KEY_MAP: Dict[str, str] = {
    "is_light_on": "light_on",
}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def from_controller(raw: Any) -> Light:
    """Build a Light from a uiprotect / manager dict or object."""
    return Light(
        id=_get(raw, "id"),
        mac=_get(raw, "mac"),
        name=_get(raw, "name"),
        model=_get(raw, "model"),
        state=_get(raw, "state"),
        is_pir_motion_detected=_get(raw, "is_pir_motion_detected"),
        is_light_on=_get(raw, "is_light_on"),
        led_level=_get(raw, "led_level"),
        sensitivity=_get(raw, "sensitivity"),
        duration_seconds=_get(raw, "duration_seconds"),
        status_light=_get(raw, "status_light"),
    )


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Translate a partial update dict to the controller's settings shape.

    Renames model-side field names that differ from controller-side keys
    (currently only ``is_light_on`` → ``light_on``).
    """
    out: Dict[str, Any] = {}
    for k, v in fields.items():
        if k not in MUTABLE_FIELDS or v is None:
            continue
        out[_CONTROLLER_KEY_MAP.get(k, k)] = v
    return out
