"""Unit tests for the Protect Sensor shared field model."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from unifi_core.protect.models.sensors import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    Sensor,
    from_controller,
    to_agent_update,
    to_public_update,
)


class TestSensorModel:
    def test_mutable_fields_set(self) -> None:
        assert MUTABLE_FIELDS == frozenset({"name"})

    def test_read_only_fields_set(self) -> None:
        assert "id" in READ_ONLY_FIELDS
        assert "mac" in READ_ONLY_FIELDS
        assert "motion_detected_at" in READ_ONLY_FIELDS
        assert "name" not in READ_ONLY_FIELDS
        assert len(READ_ONLY_FIELDS) == len(Sensor.model_fields) - len(MUTABLE_FIELDS)

    def test_from_controller_with_dict(self) -> None:
        s = from_controller(
            {
                "id": "s1",
                "name": "Garage Motion",
                "type": "motion",
                "battery_status": "ok",
                "motion_detected_at": "2026-05-13T12:00:00Z",
            }
        )
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

    def test_to_public_update_accepts_supported_settings(self) -> None:
        update = to_public_update(
            {
                "name": "Garage Door",
                "light_settings": {"is_enabled": True, "low_threshold": 10},
                "motion_settings": {"sensitivity": 65, "sensitivity_when_armed": 80},
                "schedule_mode": "always",
                "arm_profile_ids": ["profile-1"],
                "has_custom_sensitivity_when_armed": False,
            }
        )

        assert update == {
            "name": "Garage Door",
            "light_settings": {"isEnabled": True, "lowThreshold": 10},
            "motion_settings": {"sensitivity": 65, "sensitivityWhenArmed": 80},
            "schedule_mode": "always",
            "arm_profile_ids": ["profile-1"],
            "has_custom_sensitivity_when_armed": False,
        }

    def test_to_public_update_translates_nested_snake_case_fields_for_uiprotect(self) -> None:
        update = to_public_update(
            {
                "temperature_settings": {
                    "is_enabled": True,
                    "low_threshold": 35.0,
                    "high_threshold": 80.0,
                }
            }
        )

        assert update["temperature_settings"] == {
            "isEnabled": True,
            "lowThreshold": 35.0,
            "highThreshold": 80.0,
        }
        assert "temperatureSettings" not in update

    def test_to_public_update_rejects_nested_camel_case_backend_fields(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            to_public_update({"light_settings": {"isEnabled": True}})

        message = str(exc_info.value)
        assert "isEnabled" in message
        assert "Invalid sensor setting light_settings" in message

    def test_to_agent_update_translates_public_api_casing_back_to_snake_case(self) -> None:
        update = to_agent_update(
            {
                "motion_settings": {
                    "isEnabled": True,
                    "sensitivity": 65,
                    "sensitivityWhenArmed": 80,
                },
                "schedule_mode": "always",
            }
        )

        assert update == {
            "motion_settings": {
                "is_enabled": True,
                "sensitivity": 65,
                "sensitivity_when_armed": 80,
            },
            "schedule_mode": "always",
        }

    def test_to_public_update_rejects_invalid_scalar_types(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            to_public_update({"arm_profile_ids": "profile-1"})

        assert "arm_profile_ids" in str(exc_info.value)

        with pytest.raises(ValueError) as exc_info:
            to_public_update({"has_custom_sensitivity_when_armed": "yes"})

        assert "has_custom_sensitivity_when_armed" in str(exc_info.value)

        with pytest.raises(ValueError) as exc_info:
            to_public_update({"motion_settings": {"sensitivity": "80"}})

        assert "motion_settings.sensitivity" in str(exc_info.value)

        with pytest.raises(ValueError) as exc_info:
            to_public_update({"light_settings": {"low_threshold": True}})

        assert "light_settings.low_threshold" in str(exc_info.value)

        with pytest.raises(ValueError) as exc_info:
            to_public_update({"humidity_settings": {"high_threshold": "70"}})

        assert "humidity_settings.high_threshold" in str(exc_info.value)

    def test_to_public_update_rejects_out_of_range_sensitivity(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            to_public_update({"motion_settings": {"sensitivity": 101}})

        message = str(exc_info.value)
        assert "motion_settings.sensitivity" in message
        assert "less than or equal to 100" in message

    def test_to_public_update_rejects_invalid_schedule_mode(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            to_public_update({"schedule_mode": "weekends"})

        message = str(exc_info.value)
        assert "schedule_mode" in message
        assert "always" in message
        assert "when_armed" in message

    def test_to_public_update_rejects_unknown_keys(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            to_public_update({"unsupported": True})

        message = str(exc_info.value)
        assert "Unsupported sensor setting fields" in message
        assert "unsupported" in message
        assert "protect_update_sensor_settings" in message

    def test_to_public_update_rejects_read_only_fields(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            to_public_update({"id": "sensor-1", "name": "Allowed"})

        message = str(exc_info.value)
        assert "read-only sensor fields" in message
        assert "id" in message
        assert "protect_list_sensors" in message

    def test_to_public_update_rejects_empty_input(self) -> None:
        with pytest.raises(ValueError, match="No sensor settings provided"):
            to_public_update({})
