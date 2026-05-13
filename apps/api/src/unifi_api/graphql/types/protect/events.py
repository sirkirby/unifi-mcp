"""Strawberry types for protect/events (Phase 6 PR3 Task B).

Read serializers migrated from ``unifi_api.serializers.protect.events``:

- ``Event`` — protect_list_events (EVENT_LOG, resource-registered) AND
  protect_get_event (DETAIL). Both old serializers shared the
  ``_event_payload`` projection; one typed class covers both. The
  manager helper renames ``camera_id`` -> ``camera`` and
  ``thumbnail_id`` -> ``thumbnail`` per the prior contract.
- ``SmartDetection`` — protect_list_smart_detections (EVENT_LOG). Same
  projection as ``Event`` but with a richer ``display_columns`` hint
  (adds ``smart_detect_types``); split into its own type so the render
  hint differs cleanly.
- ``EventThumbnail`` — protect_get_event_thumbnail (DETAIL). Pass-through
  for the manager dict (``event_id, thumbnail_id, thumbnail_available,
  image_base64, content_type, message, url``) with a defensive bytes
  branch that surfaces metadata only.

Serializers that stay in the dict registry (NOT migrated):

- ``RecentEventsSerializer`` (``protect_recent_events``) — the SSE stream
  generator at ``routes/streams/protect.py`` calls
  ``serializer.serialize`` directly per broadcast event; can't move to a
  type without rewriting the streamer.
- ``ProtectStreamSubscriptionSerializer`` (``protect_subscribe_events``) —
  STREAM kind; thin shim returning the SSE URL metadata.
- ``EventMutationAckSerializer`` (``protect_acknowledge_event``) — preview
  ack; mutation path stays as a serializer.
"""

from __future__ import annotations

from typing import Any

import strawberry


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


@strawberry.type(description="A UniFi Protect event row (list + detail share this shape).")
class Event:
    """Mirrors ``EventManager._event_to_dict`` projection.

    Fields are renamed at the dict boundary to match the prior
    ``EventSerializer`` contract: ``camera_id`` -> ``camera``,
    ``thumbnail_id`` -> ``thumbnail``.
    """

    id: strawberry.ID | None
    type: str | None
    start: str | None
    end: str | None
    score: int | None
    smart_detect_types: list[str]
    camera: strawberry.ID | None
    thumbnail: strawberry.ID | None
    recognized_person_id: strawberry.ID | None
    recognized_person_name: str | None
    recognized_person_confidence: int | None
    detected_thumbnail_id: strawberry.ID | None

    # Context for relationship edges — NOT in SDL, NOT in to_dict().
    _controller_id: strawberry.Private[str | None] = None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["type", "start", "score"],
            "sort_default": "start:desc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "Event":
        return cls(
            id=_get(obj, "id"),
            type=_get(obj, "type"),
            start=_get(obj, "start"),
            end=_get(obj, "end"),
            score=_get(obj, "score"),
            smart_detect_types=_get(obj, "smart_detect_types") or [],
            camera=_get(obj, "camera_id"),
            thumbnail=_get(obj, "thumbnail_id"),
            recognized_person_id=_get(obj, "recognized_person_id"),
            recognized_person_name=_get(obj, "recognized_person_name"),
            recognized_person_confidence=_get(obj, "recognized_person_confidence"),
            detected_thumbnail_id=_get(obj, "detected_thumbnail_id"),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "start": self.start,
            "end": self.end,
            "score": self.score,
            "smart_detect_types": list(self.smart_detect_types),
            "camera": self.camera,
            "thumbnail": self.thumbnail,
            "recognized_person_id": self.recognized_person_id,
            "recognized_person_name": self.recognized_person_name,
            "recognized_person_confidence": self.recognized_person_confidence,
            "detected_thumbnail_id": self.detected_thumbnail_id,
        }


@strawberry.type(description="A UniFi Protect smart-detection event row.")
class SmartDetection:
    """Same projection as ``Event``, but render-hint surfaces
    ``smart_detect_types`` as a display column. Mirrors
    ``SmartDetectionsSerializer`` exactly.
    """

    id: strawberry.ID | None
    type: str | None
    start: str | None
    end: str | None
    score: int | None
    smart_detect_types: list[str]
    camera: strawberry.ID | None
    thumbnail: strawberry.ID | None
    recognized_person_id: strawberry.ID | None
    recognized_person_name: str | None
    recognized_person_confidence: int | None
    detected_thumbnail_id: strawberry.ID | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["type", "start", "score", "smart_detect_types", "recognized_person_name"],
            "sort_default": "start:desc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "SmartDetection":
        return cls(
            id=_get(obj, "id"),
            type=_get(obj, "type"),
            start=_get(obj, "start"),
            end=_get(obj, "end"),
            score=_get(obj, "score"),
            smart_detect_types=_get(obj, "smart_detect_types") or [],
            camera=_get(obj, "camera_id"),
            thumbnail=_get(obj, "thumbnail_id"),
            recognized_person_id=_get(obj, "recognized_person_id"),
            recognized_person_name=_get(obj, "recognized_person_name"),
            recognized_person_confidence=_get(obj, "recognized_person_confidence"),
            detected_thumbnail_id=_get(obj, "detected_thumbnail_id"),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "start": self.start,
            "end": self.end,
            "score": self.score,
            "smart_detect_types": list(self.smart_detect_types),
            "camera": self.camera,
            "thumbnail": self.thumbnail,
            "recognized_person_id": self.recognized_person_id,
            "recognized_person_name": self.recognized_person_name,
            "recognized_person_confidence": self.recognized_person_confidence,
            "detected_thumbnail_id": self.detected_thumbnail_id,
        }


@strawberry.type(description="Thumbnail metadata for a Protect event.")
class EventThumbnail:
    """DETAIL pass-through for the thumbnail manager dict.

    The dict branch mirrors the prior serializer's seven-key shape
    (``event_id, thumbnail_id, thumbnail_available, image_base64,
    content_type, message, url``); the bytes branch (defensive — manager
    today returns a dict) surfaces metadata only.
    """

    event_id: strawberry.ID | None
    thumbnail_id: strawberry.ID | None
    thumbnail_available: bool | None
    image_base64: str | None
    content_type: str | None
    message: str | None
    url: str | None
    size_bytes: int | None
    # Tracks which branch produced the instance so to_dict() can re-emit
    # the exact original dict shape — dict -> 7-key dict; bytes -> 4-key
    # metadata dict; other -> 3-key fallback.
    _source: strawberry.Private[str] = "dict"
    _fallback: strawberry.Private[str | None] = None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "EventThumbnail":
        if isinstance(obj, dict):
            inst = cls(
                event_id=obj.get("event_id"),
                thumbnail_id=obj.get("thumbnail_id"),
                thumbnail_available=obj.get("thumbnail_available", False),
                image_base64=obj.get("image_base64"),
                content_type=obj.get("content_type"),
                message=obj.get("message"),
                url=obj.get("url"),
                size_bytes=None,
            )
            inst._source = "dict"
            return inst
        if isinstance(obj, (bytes, bytearray)):
            inst = cls(
                event_id=None,
                thumbnail_id=None,
                thumbnail_available=True,
                image_base64=None,
                content_type="image/jpeg",
                message=None,
                url=None,
                size_bytes=len(obj),
            )
            inst._source = "bytes"
            return inst
        inst = cls(
            event_id=None,
            thumbnail_id=None,
            thumbnail_available=False,
            image_base64=None,
            content_type=None,
            message=None,
            url=None,
            size_bytes=None,
        )
        inst._source = "other"
        inst._fallback = str(obj)
        return inst

    def to_dict(self) -> dict:
        if self._source == "dict":
            return {
                "event_id": self.event_id,
                "thumbnail_id": self.thumbnail_id,
                "thumbnail_available": self.thumbnail_available,
                "image_base64": self.image_base64,
                "content_type": self.content_type,
                "message": self.message,
                "url": self.url,
            }
        if self._source == "bytes":
            return {
                "event_id": None,
                "thumbnail_available": True,
                "size_bytes": self.size_bytes,
                "content_type": self.content_type,
            }
        return {
            "event_id": None,
            "thumbnail_available": False,
            "result": self._fallback,
        }
