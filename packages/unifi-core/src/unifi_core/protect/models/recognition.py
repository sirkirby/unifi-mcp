"""Shared models for UniFi Protect recognition groups."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class RecognitionLinks(BaseModel):
    """Pagination links returned by Protect recognition endpoints."""

    prev: Optional[str] = Field(default=None, description="Previous page link", json_schema_extra={"mutable": False})
    next: Optional[str] = Field(default=None, description="Next page link", json_schema_extra={"mutable": False})


class KnownFace(BaseModel):
    """Canonical Protect Known Face / assigned face group row."""

    id: Optional[str] = Field(default=None, description="Face group UUID", json_schema_extra={"mutable": False})
    name: Optional[str] = Field(default=None, description="Assigned face name")
    matched_name: Optional[str] = Field(
        default=None, description="Matched display name", json_schema_extra={"mutable": False}
    )
    type: Optional[str] = Field(
        default=None, description="Recognition group type", json_schema_extra={"mutable": False}
    )
    image_path: Optional[str] = Field(
        default=None, description="Controller image reference path", json_schema_extra={"mutable": False}
    )
    enhanced_path: Optional[str] = Field(
        default=None, description="Controller enhanced image reference path", json_schema_extra={"mutable": False}
    )
    detections_count: Optional[int] = Field(
        default=None, description="Number of detections in this group", json_schema_extra={"mutable": False}
    )
    first_detected_at: Optional[str] = Field(
        default=None,
        description="First detection timestamp in epoch milliseconds",
        json_schema_extra={"mutable": False},
    )
    last_detected_at: Optional[str] = Field(
        default=None, description="Last detection timestamp in epoch milliseconds", json_schema_extra={"mutable": False}
    )
    is_notification_enabled: Optional[bool] = Field(
        default=None,
        description="Whether notifications are enabled for this group",
    )
    is_degraded: Optional[bool] = Field(
        default=None, description="Whether Protect marks this group as degraded", json_schema_extra={"mutable": False}
    )
    tags: list[Any] = Field(default_factory=list, description="Recognition tags", json_schema_extra={"mutable": False})
    description: Optional[str] = Field(default=None, description="Optional group description")
    created_at: Optional[str] = Field(
        default=None, description="Creation timestamp in epoch milliseconds", json_schema_extra={"mutable": False}
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional controller metadata", json_schema_extra={"mutable": False}
    )


class KnownFaceUpdate(BaseModel):
    """Mutable fields accepted by Known Face update operations."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, description="Assigned face name")
    description: Optional[str] = Field(default=None, description="Optional group description")
    is_notification_enabled: Optional[bool] = Field(
        default=None,
        description="Whether notifications are enabled for this group",
    )


MUTABLE_FIELDS = frozenset(KnownFaceUpdate.model_fields.keys())
READ_ONLY_FIELDS = frozenset(KnownFace.model_fields.keys()) - MUTABLE_FIELDS

_TO_CONTROLLER_UPDATE = {
    "name": "name",
    "description": "description",
    "is_notification_enabled": "isNotificationEnabled",
}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _get_any(obj: Any, *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = _get(obj, key)
        if value is not None:
            return value
    return default


def _stringify(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def from_controller(raw: Any) -> KnownFace:
    """Build a KnownFace from a Protect recognition group object."""
    tags = _get(raw, "tags")
    if not isinstance(tags, list):
        tags = []

    metadata = _get(raw, "metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    return KnownFace(
        id=_get(raw, "id"),
        name=_get(raw, "name"),
        matched_name=_get_any(raw, "matched_name", "matchedName"),
        type=_get(raw, "type"),
        image_path=_get_any(raw, "image_path", "imagePath"),
        enhanced_path=_get_any(raw, "enhanced_path", "enhancedPath"),
        detections_count=_get_any(raw, "detections_count", "detectionsCount"),
        first_detected_at=_stringify(_get_any(raw, "first_detected_at", "firstDetectedAt")),
        last_detected_at=_stringify(_get_any(raw, "last_detected_at", "lastDetectedAt")),
        is_notification_enabled=_get_any(raw, "is_notification_enabled", "isNotificationEnabled"),
        is_degraded=_get_any(raw, "is_degraded", "isDegraded"),
        tags=tags,
        description=_get(raw, "description"),
        created_at=_stringify(_get_any(raw, "created_at", "createdAt")),
        metadata=metadata,
    )


def links_from_controller(raw: Any) -> RecognitionLinks:
    """Build pagination links from a Protect recognition response."""
    if not isinstance(raw, dict):
        raw = {}
    return RecognitionLinks(prev=raw.get("prev"), next=raw.get("next"))


def to_controller_update(fields: dict[str, Any]) -> dict[str, Any]:
    """Translate a partial Known Face update into Protect API field names."""
    if not fields:
        raise ValueError("fields must include at least one supported mutable field")

    unknown = set(fields) - MUTABLE_FIELDS - READ_ONLY_FIELDS
    if unknown:
        raise ValueError(f"Unsupported known face fields: {sorted(unknown)}")

    read_only = set(fields) & READ_ONLY_FIELDS
    if read_only:
        raise ValueError(f"Read-only known face fields cannot be updated: {sorted(read_only)}")

    update = KnownFaceUpdate(**fields)
    supplied = update.model_dump(exclude_unset=True)
    if not supplied:
        raise ValueError("fields must include at least one supported mutable field")

    return {_TO_CONTROLLER_UPDATE[key]: value for key, value in supplied.items()}
