"""Shared field model for Protect cameras."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class Camera(BaseModel):
    """Canonical Protect camera model.

    Field metadata ``json_schema_extra={"mutable": False}`` marks fields
    that appear in list/get output but are not accepted by update tools.
    """

    # Read-only (output only)
    id: Optional[str] = Field(default=None, description="Camera UUID", json_schema_extra={"mutable": False})
    mac: Optional[str] = Field(default=None, description="MAC address", json_schema_extra={"mutable": False})
    model: Optional[str] = Field(default=None, description="Camera model", json_schema_extra={"mutable": False})
    type: Optional[str] = Field(default=None, description="Camera type", json_schema_extra={"mutable": False})
    state: Optional[str] = Field(default=None, description="Connection state", json_schema_extra={"mutable": False})
    is_recording: Optional[bool] = Field(
        default=None, description="Whether camera is currently recording", json_schema_extra={"mutable": False}
    )
    is_motion_detected: Optional[bool] = Field(
        default=None, description="Whether motion is currently detected", json_schema_extra={"mutable": False}
    )
    is_smart_detected: Optional[bool] = Field(
        default=None, description="Whether a smart detection is active", json_schema_extra={"mutable": False}
    )
    host: Optional[str] = Field(default=None, description="Camera IP/host", json_schema_extra={"mutable": False})
    channels: Optional[Any] = Field(
        default=None,
        description="Channel configuration — controller returns dict or list of channel descriptors",
        json_schema_extra={"mutable": False},
    )

    # Mutable (accepted by protect_update_camera_settings)
    name: Optional[str] = Field(default=None, description="Display name for the camera")
    ir_led_mode: Optional[str] = Field(default=None, description="IR LED mode (e.g., auto, on, off, autoFilterOnly)")
    hdr_mode: Optional[str] = Field(default=None, description="HDR mode (e.g., auto, off, always, normal)")
    mic_enabled: Optional[bool] = Field(default=None, description="Whether the microphone is enabled")
    mic_volume: Optional[int] = Field(default=None, ge=0, le=100, description="Microphone volume (0-100)")
    status_light_on: Optional[bool] = Field(default=None, description="Whether the status LED is on")
    speaker_volume: Optional[int] = Field(default=None, ge=0, le=100, description="Speaker volume (0-100)")
    motion_detection: Optional[bool] = Field(default=None, description="Whether motion detection is enabled")


MUTABLE_FIELDS = frozenset(
    name for name, info in Camera.model_fields.items() if (info.json_schema_extra or {}).get("mutable") is not False
)
READ_ONLY_FIELDS = frozenset(
    name for name, info in Camera.model_fields.items() if (info.json_schema_extra or {}).get("mutable") is False
)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def from_controller(raw: Any) -> Camera:
    """Build a Camera from a uiprotect / manager dict or object."""
    channels = _get(raw, "channels")
    if channels is not None and not isinstance(channels, (dict, list)):
        channels = None
    return Camera(
        id=_get(raw, "id"),
        mac=_get(raw, "mac"),
        name=_get(raw, "name"),
        model=_get(raw, "model"),
        type=_get(raw, "type"),
        state=_get(raw, "state"),
        is_recording=_get(raw, "is_recording"),
        is_motion_detected=_get(raw, "is_motion_detected"),
        is_smart_detected=_get(raw, "is_smart_detected"),
        host=_get(raw, "host"),
        channels=channels,
        ir_led_mode=_get(raw, "ir_led_mode"),
        hdr_mode=_get(raw, "hdr_mode"),
        mic_enabled=_get(raw, "mic_enabled"),
        mic_volume=_get(raw, "mic_volume"),
        status_light_on=_get(raw, "status_light_on"),
        speaker_volume=_get(raw, "speaker_volume"),
        motion_detection=_get(raw, "motion_detection"),
    )


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to only the mutable, recognised keys.

    The Protect manager already accepts a settings dict in this shape;
    this helper centralises mutability enforcement so callers cannot
    silently include read-only field names.
    """
    return {k: v for k, v in fields.items() if k in MUTABLE_FIELDS and v is not None}
