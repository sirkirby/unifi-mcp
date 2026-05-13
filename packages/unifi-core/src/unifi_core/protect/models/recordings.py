"""Shared field models for Protect recordings (read-only).

`protect_export_clip` and `protect_delete_recording` are action tools;
their input models live in ``_actions.py`` (Task 11). The domain models
here cover the read shape returned by `protect_list_recordings` and
`protect_get_recording_status`.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class Recording(BaseModel):
    """Canonical Protect recording window for a camera (read-only)."""

    id: Optional[str] = Field(default=None, description="Recording UUID", json_schema_extra={"mutable": False})
    type: Optional[str] = Field(default=None, description="Recording type (timelapse, motion, etc.)", json_schema_extra={"mutable": False})
    camera: Optional[str] = Field(default=None, description="Camera UUID this recording belongs to", json_schema_extra={"mutable": False})
    start: Optional[str] = Field(default=None, description="ISO start timestamp", json_schema_extra={"mutable": False})
    end: Optional[str] = Field(default=None, description="ISO end timestamp", json_schema_extra={"mutable": False})
    file_size: Optional[int] = Field(default=None, description="Recording size in bytes", json_schema_extra={"mutable": False})


class RecordingStatusList(BaseModel):
    """Wrapper shape returned by `protect_get_recording_status` (read-only)."""

    cameras: Optional[Dict[str, Any]] = Field(default=None, description="Per-camera recording status map", json_schema_extra={"mutable": False})
    count: Optional[int] = Field(default=None, description="Number of cameras in the status map", json_schema_extra={"mutable": False})


MUTABLE_FIELDS = frozenset()
READ_ONLY_FIELDS = frozenset(Recording.model_fields.keys()) | frozenset(RecordingStatusList.model_fields.keys())


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _stringify_dt(value: Any) -> Optional[str]:
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


def from_controller(raw: Any) -> Recording:
    """Build a Recording from a uiprotect / manager dict or object."""
    return Recording(
        id=_get(raw, "id"),
        type=_get(raw, "type"),
        camera=_get(raw, "camera") or _get(raw, "camera_id"),
        start=_stringify_dt(_get(raw, "start")),
        end=_stringify_dt(_get(raw, "end")),
        file_size=_get(raw, "file_size"),
    )


def status_list_from_controller(raw: Any) -> RecordingStatusList:
    """Build a RecordingStatusList from the manager's status payload."""
    cameras = _get(raw, "cameras")
    if cameras is not None and not isinstance(cameras, dict):
        cameras = None
    return RecordingStatusList(
        cameras=cameras,
        count=_get(raw, "count"),
    )
