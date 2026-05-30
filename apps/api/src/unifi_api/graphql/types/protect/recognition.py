"""Strawberry types for UniFi Protect recognition resources."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry
from unifi_core.protect.models.recognition import from_controller as known_face_from_controller
from unifi_core.protect.models.recognition import license_plate_from_controller


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


@strawberry.type(
    description="Detection-search filter vocabulary (the 'Find Anything' label groups).",
)
class DetectionSearchLabels:
    """Wrapper-dict pass-through for ``protect_detection_search_labels``.

    The manager hands back the already-``model_dump``-ed
    :class:`unifi_core.protect.models.detection_search.DetectionSearchLabels`
    dict — snake_case group lists (``colors``, ``vehicle_types``,
    ``smart_detect_types``, ``event_types``, ``group_type``, ``devices``,
    ``door_access``), each a list of ``{label, value}`` items. The groups are
    surfaced as JSON sub-maps and ``to_dict`` re-emits the verbatim dict so the
    response round-trips byte-for-byte (mirrors the ``RecordingStatusList``
    pass-through pattern).
    """

    colors: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    vehicle_types: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    smart_detect_types: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    event_types: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    group_type: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    devices: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    door_access: strawberry.scalars.JSON | None  # type: ignore[name-defined]

    _raw: strawberry.Private[dict[str, Any] | None] = None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "DetectionSearchLabels":
        if isinstance(obj, dict):
            payload = obj
        elif hasattr(obj, "model_dump"):
            payload = obj.model_dump()
        else:
            payload = {}
        inst = cls(
            colors=payload.get("colors"),
            vehicle_types=payload.get("vehicle_types"),
            smart_detect_types=payload.get("smart_detect_types"),
            event_types=payload.get("event_types"),
            group_type=payload.get("group_type"),
            devices=payload.get("devices"),
            door_access=payload.get("door_access"),
        )
        inst._raw = dict(payload)
        return inst

    def to_dict(self) -> dict:
        if self._raw is not None:
            return self._raw
        return {}


@strawberry.type(
    description="A UniFi Protect license-plate identity (vehicle recognition group).",
)
class KnownLicensePlate:
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
    def from_manager_output(cls, obj: Any) -> "KnownLicensePlate":
        model = license_plate_from_controller(obj)
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
