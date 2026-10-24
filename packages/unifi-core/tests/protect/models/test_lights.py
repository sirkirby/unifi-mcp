"""Unit tests for the Protect Light shared field model."""

from __future__ import annotations

import pytest
from unifi_core.protect.models.lights import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    Light,
    from_controller,
    to_controller_update,
)

SAMPLE = {
    "id": "light001",
    "mac": "AA:BB:CC:DD:EE:01",
    "name": "Backyard",
    "model": "UFP-Floodlight-G2",
    "state": "CONNECTED",
    "is_pir_motion_detected": False,
    "is_light_on": True,
    "led_level": 4,
    "sensitivity": 75,
    "duration_seconds": 60,
    "status_light": False,
}


class TestLightModel:
    def test_mutable_fields_set(self) -> None:
        assert "name" in MUTABLE_FIELDS
        assert "is_light_on" in MUTABLE_FIELDS
        assert "led_level" in MUTABLE_FIELDS
        assert "sensitivity" in MUTABLE_FIELDS
        assert "duration_seconds" in MUTABLE_FIELDS
        assert "status_light" in MUTABLE_FIELDS
        assert "id" not in MUTABLE_FIELDS
        assert "mac" not in MUTABLE_FIELDS

    def test_read_only_fields_set(self) -> None:
        assert "id" in READ_ONLY_FIELDS
        assert "mac" in READ_ONLY_FIELDS
        assert "model" in READ_ONLY_FIELDS
        assert "state" in READ_ONLY_FIELDS
        assert "is_pir_motion_detected" in READ_ONLY_FIELDS
        assert "name" not in READ_ONLY_FIELDS
        assert "is_light_on" not in READ_ONLY_FIELDS

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        assert not (MUTABLE_FIELDS & READ_ONLY_FIELDS)

    def test_from_controller_full_payload(self) -> None:
        light = from_controller(SAMPLE)
        assert light.id == "light001"
        assert light.mac == "AA:BB:CC:DD:EE:01"
        assert light.name == "Backyard"
        assert light.model == "UFP-Floodlight-G2"
        assert light.state == "CONNECTED"
        assert light.is_pir_motion_detected is False
        assert light.is_light_on is True
        assert light.led_level == 4
        assert light.sensitivity == 75
        assert light.duration_seconds == 60
        assert light.status_light is False

    def test_from_controller_handles_missing_fields(self) -> None:
        light = from_controller({"id": "light002"})
        assert light.id == "light002"
        assert light.name is None
        assert light.led_level is None
        assert light.sensitivity is None
        assert light.duration_seconds is None

    @pytest.mark.parametrize(
        ("fields", "expected"),
        [
            ({"id": "light001", "name": "New Name", "led_level": 3}, {"name": "New Name", "led_level": 3}),
            ({"name": "New", "led_level": None}, {"name": "New"}),
            ({}, {}),
            ({"mac": "AA:BB:CC", "state": "CONNECTED", "name": "Porch"}, {"name": "Porch"}),
        ],
    )
    def test_to_controller_update(self, fields: dict, expected: dict) -> None:
        out = to_controller_update(fields)
        assert "id" not in out
        assert out == expected

    def test_to_controller_update_renames_is_light_on_to_light_on(self) -> None:
        out = to_controller_update({"is_light_on": True, "led_level": 2})
        assert "is_light_on" not in out
        assert out["light_on"] is True
        assert out["led_level"] == 2

    def test_led_level_constraint_rejects_out_of_range(self) -> None:
        with pytest.raises(Exception):
            Light(led_level=7)
        with pytest.raises(Exception):
            Light(led_level=0)

    def test_sensitivity_constraint_rejects_out_of_range(self) -> None:
        with pytest.raises(Exception):
            Light(sensitivity=101)
        with pytest.raises(Exception):
            Light(sensitivity=-1)

    def test_duration_seconds_constraint_rejects_out_of_range(self) -> None:
        with pytest.raises(Exception):
            Light(duration_seconds=901)
        with pytest.raises(Exception):
            Light(duration_seconds=14)
