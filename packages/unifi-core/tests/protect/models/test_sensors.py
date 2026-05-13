"""Unit tests for the Protect Sensor read-only model."""

from __future__ import annotations

from datetime import datetime, timezone

from unifi_core.protect.models.sensors import (
    Sensor,
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    from_controller,
)


class TestSensorModel:
    def test_no_mutable_fields(self) -> None:
        assert MUTABLE_FIELDS == frozenset()

    def test_all_fields_read_only(self) -> None:
        assert "id" in READ_ONLY_FIELDS
        assert "name" in READ_ONLY_FIELDS
        assert "motion_detected_at" in READ_ONLY_FIELDS
        assert len(READ_ONLY_FIELDS) == len(Sensor.model_fields)

    def test_from_controller_with_dict(self) -> None:
        s = from_controller({
            "id": "s1",
            "name": "Garage Motion",
            "type": "motion",
            "battery_status": "ok",
            "motion_detected_at": "2026-05-13T12:00:00Z",
        })
        assert s.id == "s1"
        assert s.name == "Garage Motion"
        assert s.motion_detected_at == "2026-05-13T12:00:00Z"

    def test_from_controller_with_datetime_value(self) -> None:
        dt = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
        s = from_controller({"id": "s2", "motion_detected_at": dt})
        assert s.motion_detected_at == dt.isoformat()

    def test_from_controller_handles_missing_fields(self) -> None:
        s = from_controller({"id": "s3"})
        assert s.id == "s3"
        assert s.name is None
        assert s.motion_detected_at is None
