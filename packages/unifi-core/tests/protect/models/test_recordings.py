"""Unit tests for the Protect Recording and RecordingStatusList read-only models."""

from __future__ import annotations

from datetime import datetime, timezone

from unifi_core.protect.models.recordings import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    Recording,
    RecordingStatusList,
    from_controller,
    status_list_from_controller,
)


class TestRecordingModelFields:
    def test_mutable_fields_empty(self) -> None:
        assert MUTABLE_FIELDS == frozenset()

    def test_read_only_fields_contains_all_recording_fields(self) -> None:
        for field_name in Recording.model_fields:
            assert field_name in READ_ONLY_FIELDS

    def test_read_only_fields_contains_all_status_list_fields(self) -> None:
        for field_name in RecordingStatusList.model_fields:
            assert field_name in READ_ONLY_FIELDS

    def test_read_only_fields_is_union_of_both_models(self) -> None:
        expected = frozenset(Recording.model_fields.keys()) | frozenset(RecordingStatusList.model_fields.keys())
        assert READ_ONLY_FIELDS == expected


class TestFromController:
    def test_full_dict(self) -> None:
        raw = {
            "id": "rec-001",
            "type": "motion",
            "camera": "cam-001",
            "start": "2026-05-13T10:00:00+00:00",
            "end": "2026-05-13T10:05:00+00:00",
            "file_size": 5242880,
        }
        rec = from_controller(raw)
        assert rec.id == "rec-001"
        assert rec.type == "motion"
        assert rec.camera == "cam-001"
        assert rec.start == "2026-05-13T10:00:00+00:00"
        assert rec.end == "2026-05-13T10:05:00+00:00"
        assert rec.file_size == 5242880

    def test_datetime_start_is_stringified(self) -> None:
        dt_start = datetime(2026, 5, 13, 10, 0, 0, tzinfo=timezone.utc)
        dt_end = datetime(2026, 5, 13, 10, 5, 0, tzinfo=timezone.utc)
        rec = from_controller({"id": "rec-002", "start": dt_start, "end": dt_end})
        assert rec.start == dt_start.isoformat()
        assert rec.end == dt_end.isoformat()

    def test_missing_fields_default_to_none(self) -> None:
        rec = from_controller({"id": "rec-003"})
        assert rec.id == "rec-003"
        assert rec.type is None
        assert rec.camera is None
        assert rec.start is None
        assert rec.end is None
        assert rec.file_size is None

    def test_camera_id_fallback_when_camera_absent(self) -> None:
        rec = from_controller({"id": "rec-004", "camera_id": "cam-fallback"})
        assert rec.camera == "cam-fallback"

    def test_camera_takes_precedence_over_camera_id(self) -> None:
        rec = from_controller({"id": "rec-005", "camera": "cam-direct", "camera_id": "cam-fallback"})
        assert rec.camera == "cam-direct"

    def test_empty_dict(self) -> None:
        rec = from_controller({})
        assert isinstance(rec, Recording)
        assert rec.id is None


class TestStatusListFromController:
    def test_full_dict(self) -> None:
        raw = {
            "cameras": {"cam-001": {"is_recording": True}, "cam-002": {"is_recording": False}},
            "count": 2,
        }
        status = status_list_from_controller(raw)
        assert status.cameras == {"cam-001": {"is_recording": True}, "cam-002": {"is_recording": False}}
        assert status.count == 2

    def test_non_dict_cameras_dropped_to_none(self) -> None:
        status = status_list_from_controller({"cameras": [{"camera_id": "cam-001"}], "count": 1})
        assert status.cameras is None
        assert status.count == 1

    def test_none_cameras_stays_none(self) -> None:
        status = status_list_from_controller({"cameras": None, "count": 0})
        assert status.cameras is None
        assert status.count == 0

    def test_missing_fields_default_to_none(self) -> None:
        status = status_list_from_controller({})
        assert isinstance(status, RecordingStatusList)
        assert status.cameras is None
        assert status.count is None
