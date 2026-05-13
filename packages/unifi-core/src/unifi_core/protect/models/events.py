"""Shared field models for Protect events (read-only).

``protect_acknowledge_event`` is an action tool; its input model lives in
``_actions.py`` (Task 11). ``protect_subscribe_events`` is a streaming
subscription tool and has no domain model here. The three classes below
cover the read shapes returned by the event query and thumbnail tools.
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class Event(BaseModel):
    """Canonical Protect event row (list + detail share this shape, read-only)."""

    id: Optional[str] = Field(default=None, description="Event UUID", json_schema_extra={"mutable": False})
    type: Optional[str] = Field(
        default=None,
        description="Event type (motion, smartDetectZone, ring, etc.)",
        json_schema_extra={"mutable": False},
    )
    start: Optional[str] = Field(default=None, description="ISO start timestamp", json_schema_extra={"mutable": False})
    end: Optional[str] = Field(default=None, description="ISO end timestamp", json_schema_extra={"mutable": False})
    score: Optional[int] = Field(
        default=None, description="Detection confidence score (0-100)", json_schema_extra={"mutable": False}
    )
    smart_detect_types: List[str] = Field(
        default_factory=list,
        description="Smart detection sub-types (person, vehicle, etc.)",
        json_schema_extra={"mutable": False},
    )
    camera: Optional[str] = Field(
        default=None, description="Camera UUID this event belongs to", json_schema_extra={"mutable": False}
    )
    thumbnail: Optional[str] = Field(
        default=None, description="Thumbnail ID for this event", json_schema_extra={"mutable": False}
    )
    recognized_person_id: Optional[str] = Field(
        default=None, description="Recognized Known Face group UUID when present", json_schema_extra={"mutable": False}
    )
    recognized_person_name: Optional[str] = Field(
        default=None,
        description="Recognized Known Face display name when present",
        json_schema_extra={"mutable": False},
    )
    recognized_person_confidence: Optional[int] = Field(
        default=None, description="Known Face match confidence when present", json_schema_extra={"mutable": False}
    )
    detected_thumbnail_id: Optional[str] = Field(
        default=None,
        description="Detected thumbnail/crop reference ID when present",
        json_schema_extra={"mutable": False},
    )


class SmartDetection(BaseModel):
    """Canonical Protect smart-detection event row (read-only).

    Same projection as ``Event`` but split into its own type so the
    render hint can surface ``smart_detect_types`` as a display column.
    """

    id: Optional[str] = Field(default=None, description="Event UUID", json_schema_extra={"mutable": False})
    type: Optional[str] = Field(
        default=None, description="Event type (smartDetectZone)", json_schema_extra={"mutable": False}
    )
    start: Optional[str] = Field(default=None, description="ISO start timestamp", json_schema_extra={"mutable": False})
    end: Optional[str] = Field(default=None, description="ISO end timestamp", json_schema_extra={"mutable": False})
    score: Optional[int] = Field(
        default=None, description="Detection confidence score (0-100)", json_schema_extra={"mutable": False}
    )
    smart_detect_types: List[str] = Field(
        default_factory=list,
        description="Smart detection sub-types (person, vehicle, etc.)",
        json_schema_extra={"mutable": False},
    )
    camera: Optional[str] = Field(
        default=None, description="Camera UUID this event belongs to", json_schema_extra={"mutable": False}
    )
    thumbnail: Optional[str] = Field(
        default=None, description="Thumbnail ID for this event", json_schema_extra={"mutable": False}
    )
    recognized_person_id: Optional[str] = Field(
        default=None, description="Recognized Known Face group UUID when present", json_schema_extra={"mutable": False}
    )
    recognized_person_name: Optional[str] = Field(
        default=None,
        description="Recognized Known Face display name when present",
        json_schema_extra={"mutable": False},
    )
    recognized_person_confidence: Optional[int] = Field(
        default=None, description="Known Face match confidence when present", json_schema_extra={"mutable": False}
    )
    detected_thumbnail_id: Optional[str] = Field(
        default=None,
        description="Detected thumbnail/crop reference ID when present",
        json_schema_extra={"mutable": False},
    )


class EventThumbnail(BaseModel):
    """Thumbnail metadata for a Protect event (read-only)."""

    event_id: Optional[str] = Field(
        default=None, description="Event UUID this thumbnail belongs to", json_schema_extra={"mutable": False}
    )
    thumbnail_id: Optional[str] = Field(
        default=None, description="Thumbnail asset ID", json_schema_extra={"mutable": False}
    )
    thumbnail_available: Optional[bool] = Field(
        default=None, description="Whether the thumbnail is available", json_schema_extra={"mutable": False}
    )
    image_base64: Optional[str] = Field(
        default=None, description="Base64-encoded JPEG thumbnail data", json_schema_extra={"mutable": False}
    )
    content_type: Optional[str] = Field(
        default=None, description="MIME type of the thumbnail (e.g. image/jpeg)", json_schema_extra={"mutable": False}
    )
    message: Optional[str] = Field(
        default=None, description="Status or error message", json_schema_extra={"mutable": False}
    )
    url: Optional[str] = Field(
        default=None, description="URL to the thumbnail resource", json_schema_extra={"mutable": False}
    )
    size_bytes: Optional[int] = Field(
        default=None, description="Thumbnail size in bytes", json_schema_extra={"mutable": False}
    )


MUTABLE_FIELDS = frozenset()
READ_ONLY_FIELDS = (
    frozenset(Event.model_fields.keys())
    | frozenset(SmartDetection.model_fields.keys())
    | frozenset(EventThumbnail.model_fields.keys())
)


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


def _coerce_id(raw: Any, key: str) -> Optional[str]:
    """Extract a string ID from a raw value that may be a bare string or a dict
    containing an ``id`` key (object reference pattern)."""
    value = _get(raw, key)
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get("id")
    return str(value)


def _get_any(raw: Any, *keys: str) -> Any:
    for key in keys:
        value = _get(raw, key)
        if value is not None:
            return value
    return None


def from_controller(raw: Any) -> Event:
    """Build an Event from a uiprotect / manager dict or object."""
    sdt = _get(raw, "smart_detect_types")
    if not isinstance(sdt, list):
        sdt = []

    camera = _coerce_id(raw, "camera") or _coerce_id(raw, "camera_id")
    thumbnail = _coerce_id(raw, "thumbnail") or _coerce_id(raw, "thumbnail_id")

    return Event(
        id=_get(raw, "id"),
        type=_get(raw, "type"),
        start=_stringify_dt(_get(raw, "start")),
        end=_stringify_dt(_get(raw, "end")),
        score=_get(raw, "score"),
        smart_detect_types=sdt,
        camera=camera,
        thumbnail=thumbnail,
        recognized_person_id=_get(raw, "recognized_person_id"),
        recognized_person_name=_get(raw, "recognized_person_name"),
        recognized_person_confidence=_get(raw, "recognized_person_confidence"),
        detected_thumbnail_id=_get_any(raw, "detected_thumbnail_id", "detectedThumbnailId"),
    )


def smart_detection_from_controller(raw: Any) -> SmartDetection:
    """Build a SmartDetection from a uiprotect / manager dict or object."""
    sdt = _get(raw, "smart_detect_types")
    if not isinstance(sdt, list):
        sdt = []

    camera = _coerce_id(raw, "camera") or _coerce_id(raw, "camera_id")
    thumbnail = _coerce_id(raw, "thumbnail") or _coerce_id(raw, "thumbnail_id")

    return SmartDetection(
        id=_get(raw, "id"),
        type=_get(raw, "type"),
        start=_stringify_dt(_get(raw, "start")),
        end=_stringify_dt(_get(raw, "end")),
        score=_get(raw, "score"),
        smart_detect_types=sdt,
        camera=camera,
        thumbnail=thumbnail,
        recognized_person_id=_get(raw, "recognized_person_id"),
        recognized_person_name=_get(raw, "recognized_person_name"),
        recognized_person_confidence=_get(raw, "recognized_person_confidence"),
        detected_thumbnail_id=_get_any(raw, "detected_thumbnail_id", "detectedThumbnailId"),
    )


def thumbnail_from_controller(raw: Any) -> EventThumbnail:
    """Build an EventThumbnail from a manager dict or object."""
    return EventThumbnail(
        event_id=_get(raw, "event_id"),
        thumbnail_id=_get(raw, "thumbnail_id"),
        thumbnail_available=_get(raw, "thumbnail_available"),
        image_base64=_get(raw, "image_base64"),
        content_type=_get(raw, "content_type"),
        message=_get(raw, "message"),
        url=_get(raw, "url"),
        size_bytes=_get(raw, "size_bytes"),
    )
