"""Strawberry types for UniFi Protect recognition resources."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry
from unifi_core.protect.models.recognition import from_controller as known_face_from_controller


@strawberry.type(description="A UniFi Protect Known Face / assigned face recognition group.")
class KnownFace:
    id: strawberry.ID | None
    name: str | None
    matched_name: str | None
    type: str | None
    image_path: str | None
    enhanced_path: str | None
    detections_count: int | None
    first_detected_at: str | None
    last_detected_at: str | None
    is_notification_enabled: bool | None
    is_degraded: bool | None
    tags: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    description: str | None
    created_at: str | None
    metadata: strawberry.scalars.JSON | None  # type: ignore[name-defined]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "matched_name", "detections_count", "last_detected_at"],
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "KnownFace":
        model = known_face_from_controller(obj)
        return cls(
            id=model.id,
            name=model.name,
            matched_name=model.matched_name,
            type=model.type,
            image_path=model.image_path,
            enhanced_path=model.enhanced_path,
            detections_count=model.detections_count,
            first_detected_at=model.first_detected_at,
            last_detected_at=model.last_detected_at,
            is_notification_enabled=model.is_notification_enabled,
            is_degraded=model.is_degraded,
            tags=model.tags,
            description=model.description,
            created_at=model.created_at,
            metadata=model.metadata,
        )

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if not k.startswith("_") and not callable(v)}
