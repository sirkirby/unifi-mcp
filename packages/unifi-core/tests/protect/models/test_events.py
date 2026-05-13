"""Unit tests for the Protect Event, SmartDetection, and EventThumbnail read-only models."""

from __future__ import annotations

from datetime import datetime, timezone

from unifi_core.protect.models.events import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    Event,
    EventThumbnail,
    SmartDetection,
    from_controller,
    smart_detection_from_controller,
    thumbnail_from_controller,
)


class TestEventModelFields:
    def test_mutable_fields_empty(self) -> None:
        assert MUTABLE_FIELDS == frozenset()

    def test_read_only_fields_contains_all_event_fields(self) -> None:
        for field_name in Event.model_fields:
            assert field_name in READ_ONLY_FIELDS

    def test_read_only_fields_contains_all_smart_detection_fields(self) -> None:
        for field_name in SmartDetection.model_fields:
            assert field_name in READ_ONLY_FIELDS

    def test_read_only_fields_contains_all_thumbnail_fields(self) -> None:
        for field_name in EventThumbnail.model_fields:
            assert field_name in READ_ONLY_FIELDS

    def test_read_only_fields_is_union_of_all_three_models(self) -> None:
        expected = (
            frozenset(Event.model_fields.keys())
            | frozenset(SmartDetection.model_fields.keys())
            | frozenset(EventThumbnail.model_fields.keys())
        )
        assert READ_ONLY_FIELDS == expected


class TestFromController:
    def test_full_dict(self) -> None:
        raw = {
            "id": "evt-001",
            "type": "motion",
            "start": "2026-05-13T10:00:00+00:00",
            "end": "2026-05-13T10:05:00+00:00",
            "score": 85,
            "smart_detect_types": ["person"],
            "camera": "cam-001",
            "thumbnail": "thumb-001",
            "recognized_person_id": "face-group-1",
            "recognized_person_name": "Assigned Person",
            "recognized_person_confidence": 94,
            "detected_thumbnail_id": "crop-1",
        }
        evt = from_controller(raw)
        assert evt.id == "evt-001"
        assert evt.type == "motion"
        assert evt.start == "2026-05-13T10:00:00+00:00"
        assert evt.end == "2026-05-13T10:05:00+00:00"
        assert evt.score == 85
        assert evt.smart_detect_types == ["person"]
        assert evt.camera == "cam-001"
        assert evt.thumbnail == "thumb-001"
        assert evt.recognized_person_id == "face-group-1"
        assert evt.recognized_person_name == "Assigned Person"
        assert evt.recognized_person_confidence == 94
        assert evt.detected_thumbnail_id == "crop-1"

    def test_missing_fields_default_to_none_or_empty(self) -> None:
        evt = from_controller({"id": "evt-002"})
        assert evt.id == "evt-002"
        assert evt.type is None
        assert evt.start is None
        assert evt.end is None
        assert evt.score is None
        assert evt.smart_detect_types == []
        assert evt.camera is None
        assert evt.thumbnail is None

    def test_empty_dict(self) -> None:
        evt = from_controller({})
        assert isinstance(evt, Event)
        assert evt.id is None
        assert evt.smart_detect_types == []

    def test_datetime_start_end_stringified(self) -> None:
        dt_start = datetime(2026, 5, 13, 10, 0, 0, tzinfo=timezone.utc)
        dt_end = datetime(2026, 5, 13, 10, 5, 0, tzinfo=timezone.utc)
        evt = from_controller({"id": "evt-003", "start": dt_start, "end": dt_end})
        assert evt.start == dt_start.isoformat()
        assert evt.end == dt_end.isoformat()

    def test_non_list_smart_detect_types_coerced_to_empty(self) -> None:
        evt = from_controller({"id": "evt-004", "smart_detect_types": "person"})
        assert evt.smart_detect_types == []

    def test_none_smart_detect_types_coerced_to_empty(self) -> None:
        evt = from_controller({"id": "evt-005", "smart_detect_types": None})
        assert evt.smart_detect_types == []

    def test_int_smart_detect_types_coerced_to_empty(self) -> None:
        evt = from_controller({"id": "evt-006", "smart_detect_types": 42})
        assert evt.smart_detect_types == []

    def test_camera_id_fallback(self) -> None:
        evt = from_controller({"id": "evt-007", "camera_id": "cam-fallback"})
        assert evt.camera == "cam-fallback"

    def test_camera_takes_precedence_over_camera_id(self) -> None:
        evt = from_controller({"id": "evt-008", "camera": "cam-direct", "camera_id": "cam-fallback"})
        assert evt.camera == "cam-direct"

    def test_camera_as_dict_with_id(self) -> None:
        evt = from_controller({"id": "evt-009", "camera": {"id": "cam-dict"}})
        assert evt.camera == "cam-dict"

    def test_thumbnail_id_fallback(self) -> None:
        evt = from_controller({"id": "evt-010", "thumbnail_id": "thumb-fallback"})
        assert evt.thumbnail == "thumb-fallback"

    def test_thumbnail_as_dict_with_id(self) -> None:
        evt = from_controller({"id": "evt-011", "thumbnail": {"id": "thumb-dict"}})
        assert evt.thumbnail == "thumb-dict"

    def test_multiple_smart_detect_types(self) -> None:
        evt = from_controller({"id": "evt-012", "smart_detect_types": ["person", "vehicle"]})
        assert evt.smart_detect_types == ["person", "vehicle"]

    def test_detected_thumbnail_id_camel_case(self) -> None:
        evt = from_controller({"id": "evt-013", "detectedThumbnailId": "crop-camel"})
        assert evt.detected_thumbnail_id == "crop-camel"


class TestSmartDetectionFromController:
    def test_full_dict(self) -> None:
        raw = {
            "id": "sd-001",
            "type": "smartDetectZone",
            "start": "2026-05-13T09:00:00+00:00",
            "end": "2026-05-13T09:01:00+00:00",
            "score": 92,
            "smart_detect_types": ["person", "animal"],
            "camera": "cam-002",
            "thumbnail": "thumb-002",
            "recognized_person_id": "face-group-2",
            "recognized_person_name": "Another Person",
            "recognized_person_confidence": 91,
            "detected_thumbnail_id": "crop-2",
        }
        sd = smart_detection_from_controller(raw)
        assert isinstance(sd, SmartDetection)
        assert sd.id == "sd-001"
        assert sd.type == "smartDetectZone"
        assert sd.start == "2026-05-13T09:00:00+00:00"
        assert sd.end == "2026-05-13T09:01:00+00:00"
        assert sd.score == 92
        assert sd.smart_detect_types == ["person", "animal"]
        assert sd.camera == "cam-002"
        assert sd.thumbnail == "thumb-002"
        assert sd.recognized_person_id == "face-group-2"
        assert sd.recognized_person_name == "Another Person"
        assert sd.recognized_person_confidence == 91
        assert sd.detected_thumbnail_id == "crop-2"

    def test_missing_fields_default_to_none_or_empty(self) -> None:
        sd = smart_detection_from_controller({"id": "sd-002"})
        assert sd.id == "sd-002"
        assert sd.type is None
        assert sd.smart_detect_types == []

    def test_datetime_stringified(self) -> None:
        dt = datetime(2026, 5, 13, 9, 0, 0, tzinfo=timezone.utc)
        sd = smart_detection_from_controller({"start": dt})
        assert sd.start == dt.isoformat()

    def test_non_list_smart_detect_types_coerced_to_empty(self) -> None:
        sd = smart_detection_from_controller({"smart_detect_types": "vehicle"})
        assert sd.smart_detect_types == []

    def test_empty_dict(self) -> None:
        sd = smart_detection_from_controller({})
        assert isinstance(sd, SmartDetection)
        assert sd.id is None
        assert sd.smart_detect_types == []

    def test_camera_id_fallback(self) -> None:
        sd = smart_detection_from_controller({"camera_id": "cam-003"})
        assert sd.camera == "cam-003"

    def test_thumbnail_id_fallback(self) -> None:
        sd = smart_detection_from_controller({"thumbnail_id": "thumb-003"})
        assert sd.thumbnail == "thumb-003"


class TestThumbnailFromController:
    def test_full_dict(self) -> None:
        raw = {
            "event_id": "evt-001",
            "thumbnail_id": "thumb-001",
            "thumbnail_available": True,
            "image_base64": "base64encodeddata==",
            "content_type": "image/jpeg",
            "message": None,
            "url": "https://nvr.local/thumb/001",
            "size_bytes": 8192,
        }
        thumb = thumbnail_from_controller(raw)
        assert isinstance(thumb, EventThumbnail)
        assert thumb.event_id == "evt-001"
        assert thumb.thumbnail_id == "thumb-001"
        assert thumb.thumbnail_available is True
        assert thumb.image_base64 == "base64encodeddata=="
        assert thumb.content_type == "image/jpeg"
        assert thumb.message is None
        assert thumb.url == "https://nvr.local/thumb/001"
        assert thumb.size_bytes == 8192

    def test_partial_dict(self) -> None:
        raw = {
            "event_id": "evt-002",
            "thumbnail_available": False,
        }
        thumb = thumbnail_from_controller(raw)
        assert thumb.event_id == "evt-002"
        assert thumb.thumbnail_available is False
        assert thumb.thumbnail_id is None
        assert thumb.image_base64 is None
        assert thumb.content_type is None
        assert thumb.message is None
        assert thumb.url is None
        assert thumb.size_bytes is None

    def test_empty_dict(self) -> None:
        thumb = thumbnail_from_controller({})
        assert isinstance(thumb, EventThumbnail)
        assert thumb.event_id is None
        assert thumb.thumbnail_available is None

    def test_model_dump_excludes_none(self) -> None:
        raw = {"event_id": "evt-003", "thumbnail_available": True, "content_type": "image/jpeg"}
        thumb = thumbnail_from_controller(raw)
        dumped = thumb.model_dump(exclude_none=True)
        assert "event_id" in dumped
        assert "thumbnail_available" in dumped
        assert "content_type" in dumped
        # Fields with None should be excluded
        assert "thumbnail_id" not in dumped
        assert "image_base64" not in dumped
