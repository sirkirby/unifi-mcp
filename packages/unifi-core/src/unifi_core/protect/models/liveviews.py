"""Shared field model for Protect liveviews (multi-camera grid layouts)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Liveview(BaseModel):
    """Canonical Protect liveview model."""

    # Read-only
    id: Optional[str] = Field(default=None, description="Liveview UUID", json_schema_extra={"mutable": False})
    layout: Optional[int] = Field(default=None, description="Layout type/index", json_schema_extra={"mutable": False})
    is_default: Optional[bool] = Field(
        default=None, description="Whether this is the user's default liveview", json_schema_extra={"mutable": False}
    )
    is_global: Optional[bool] = Field(
        default=None, description="Whether this liveview is shared", json_schema_extra={"mutable": False}
    )
    owner_id: Optional[str] = Field(
        default=None, description="User ID of the liveview owner", json_schema_extra={"mutable": False}
    )
    slots: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Per-slot layout configuration (JSON)", json_schema_extra={"mutable": False}
    )
    slot_count: Optional[int] = Field(
        default=None, description="Number of slots in the layout", json_schema_extra={"mutable": False}
    )
    camera_count: Optional[int] = Field(
        default=None, description="Number of cameras referenced", json_schema_extra={"mutable": False}
    )

    # Mutable (inputs accepted by protect_create_liveview)
    name: Optional[str] = Field(default=None, description="Display name for the liveview")
    cameras: List[str] = Field(default_factory=list, description="Camera UUIDs included in the liveview")


MUTABLE_FIELDS = frozenset(
    name for name, info in Liveview.model_fields.items() if (info.json_schema_extra or {}).get("mutable") is not False
)
READ_ONLY_FIELDS = frozenset(
    name for name, info in Liveview.model_fields.items() if (info.json_schema_extra or {}).get("mutable") is False
)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def from_controller(raw: Any) -> Liveview:
    """Build a Liveview from a uiprotect / manager dict or object.

    The manager may return camera references under either ``cameras`` or
    ``camera_ids`` depending on the path; coalesce both.
    """
    cameras = _get(raw, "cameras")
    if not isinstance(cameras, list):
        cameras = _get(raw, "camera_ids")
    if not isinstance(cameras, list):
        cameras = []
    slots = _get(raw, "slots")
    if slots is not None and not isinstance(slots, list):
        slots = None
    return Liveview(
        id=_get(raw, "id"),
        name=_get(raw, "name"),
        layout=_get(raw, "layout"),
        is_default=_get(raw, "is_default"),
        is_global=_get(raw, "is_global"),
        owner_id=_get(raw, "owner_id"),
        cameras=list(cameras),
        slots=slots,
        slot_count=_get(raw, "slot_count"),
        camera_count=_get(raw, "camera_count"),
    )


def to_controller_create(model: Liveview) -> Dict[str, Any]:
    """Build the create-payload kwargs the manager expects.

    The liveview manager's ``create_liveview(name, camera_ids)`` uses
    ``camera_ids`` (controller-side key) for the list of cameras.
    """
    return {
        "name": model.name or "",
        "camera_ids": list(model.cameras or []),
    }
