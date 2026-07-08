"""Shared field model for Protect chimes (paired-camera doorbell ringers)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator


class Chime(BaseModel):
    """Canonical Protect chime model."""

    # Read-only
    id: Optional[str] = Field(default=None, description="Chime UUID", json_schema_extra={"mutable": False})
    mac: Optional[str] = Field(default=None, description="MAC address", json_schema_extra={"mutable": False})
    model: Optional[str] = Field(default=None, description="Chime model", json_schema_extra={"mutable": False})
    type: Optional[str] = Field(default=None, description="Device type", json_schema_extra={"mutable": False})
    state: Optional[str] = Field(default=None, description="Connection state", json_schema_extra={"mutable": False})
    is_connected: Optional[bool] = Field(
        default=None, description="Whether the chime is connected", json_schema_extra={"mutable": False}
    )
    firmware_version: Optional[str] = Field(
        default=None, description="Firmware version", json_schema_extra={"mutable": False}
    )
    paired_cameras: List[str] = Field(
        default_factory=list, description="Camera IDs this chime rings for", json_schema_extra={"mutable": False}
    )
    ring_settings: Optional[Any] = Field(
        default=None,
        description="Per-camera ring tone configuration (controller returns dict or list)",
        json_schema_extra={"mutable": False},
    )
    available_tracks: Optional[Any] = Field(
        default=None, description="Available chime tones (list of dicts)", json_schema_extra={"mutable": False}
    )

    # Mutable
    name: Optional[str] = Field(default=None, description="Display name")
    volume: Optional[int] = Field(default=None, ge=0, le=100, description="Speaker volume (0-100)")
    repeat_times: Optional[int] = Field(
        default=None, ge=1, le=6, description="Number of times to repeat the chime tone (1-6)"
    )


MUTABLE_FIELDS = frozenset(
    name for name, info in Chime.model_fields.items() if (info.json_schema_extra or {}).get("mutable") is not False
)
READ_ONLY_FIELDS = frozenset(
    name for name, info in Chime.model_fields.items() if (info.json_schema_extra or {}).get("mutable") is False
)
RING_SETTING_UPDATE_FIELDS = frozenset({"camera_id", "volume", "repeat_times"})


class _ChimeRingSettingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera_id: str = Field(min_length=1)
    volume: Optional[StrictInt] = Field(default=None, ge=0, le=100)
    repeat_times: Optional[StrictInt] = Field(default=None, ge=1, le=6)

    @model_validator(mode="after")
    def _require_change(self) -> "_ChimeRingSettingUpdate":
        if self.volume is None and self.repeat_times is None:
            raise ValueError("Chime ring setting updates require at least one of volume or repeat_times.")
        return self


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def from_controller(raw: Any) -> Chime:
    """Build a Chime from a uiprotect / manager dict or object."""
    # The manager serialises camera IDs as ``camera_ids``; the canonical
    # model field is ``paired_cameras``.  Accept either key.
    paired = _get(raw, "paired_cameras") or _get(raw, "camera_ids") or []
    if not isinstance(paired, list):
        paired = []
    ring_settings = _get(raw, "ring_settings")
    if ring_settings is not None and not isinstance(ring_settings, (dict, list)):
        ring_settings = None
    available_tracks = _get(raw, "available_tracks")
    if available_tracks is not None and not isinstance(available_tracks, list):
        available_tracks = None
    return Chime(
        id=_get(raw, "id"),
        mac=_get(raw, "mac"),
        name=_get(raw, "name"),
        model=_get(raw, "model"),
        type=_get(raw, "type"),
        state=_get(raw, "state"),
        is_connected=_get(raw, "is_connected"),
        firmware_version=_get(raw, "firmware_version"),
        volume=_get(raw, "volume"),
        paired_cameras=list(paired),
        ring_settings=ring_settings,
        available_tracks=available_tracks,
        repeat_times=_get(raw, "repeat_times"),
    )


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and filter a global chime update dict."""
    if not isinstance(fields, dict):
        raise ValueError("Chime settings must be a dictionary for protect_update_chime.")

    unsupported = sorted(set(fields) - MUTABLE_FIELDS)
    if unsupported:
        joined = ", ".join(unsupported)
        supported = ", ".join(sorted(MUTABLE_FIELDS))
        raise ValueError(
            f"Unsupported chime setting fields for protect_update_chime: {joined}. "
            f"Supported global fields: {supported}."
        )

    update = {k: v for k, v in fields.items() if k in MUTABLE_FIELDS and v is not None}
    if not update:
        return {}

    try:
        model = Chime(**update)
    except ValidationError as exc:
        raise ValueError(
            _first_validation_message(
                exc,
                field_label="chime setting",
                aggregate_label="chime settings",
            )
        ) from exc

    return {k: getattr(model, k) for k in update if getattr(model, k) is not None}


def to_ring_setting_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a per-camera chime ring setting update in agent-facing shape."""
    if not isinstance(fields, dict):
        raise ValueError("Chime ring settings must be a dictionary for protect_update_chime.")
    if not fields:
        raise ValueError("No chime ring settings provided. Specify camera_id and at least one setting to update.")

    keys = set(fields)
    if "ringtone_id" in keys:
        raise ValueError(
            "ringtone_id is not currently supported for protect_update_chime ring setting updates. "
            "Update volume or repeat_times only."
        )

    unknown = sorted(keys - RING_SETTING_UPDATE_FIELDS)
    if unknown:
        joined = ", ".join(unknown)
        supported = ", ".join(sorted(RING_SETTING_UPDATE_FIELDS))
        raise ValueError(
            f"Unsupported chime ring setting fields for protect_update_chime: {joined}. "
            f"Supported per-camera fields: {supported}."
        )

    try:
        model = _ChimeRingSettingUpdate(**fields)
    except ValidationError as exc:
        raise ValueError(_first_validation_message(exc)) from exc

    return model.model_dump(exclude_none=True)


def _first_validation_message(
    exc: ValidationError,
    *,
    field_label: str = "chime ring setting",
    aggregate_label: str = "chime ring settings",
) -> str:
    first = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(part) for part in first.get("loc", ()) if part != "__root__")
    message = first.get("msg", str(exc))
    if location:
        return f"Invalid {field_label} {location}: {message}"
    return f"Invalid {aggregate_label}: {message}"
