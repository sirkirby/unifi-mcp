"""Unit tests for the Protect Camera shared field model."""

from __future__ import annotations

import pytest
from unifi_core.protect.models.cameras import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    Camera,
    from_controller,
    to_controller_update,
)

SAMPLE = {
    "id": "cam001",
    "mac": "AA:BB:CC:DD:EE:01",
    "name": "Front Door",
    "model": "G4 Doorbell Pro",
    "type": "doorbell",
    "state": "CONNECTED",
    "is_recording": True,
    "is_motion_detected": False,
    "is_smart_detected": False,
    "host": "10.0.1.42",
    "channels": {"0": {"resolution": "3840x2160"}},
    "ir_led_mode": "auto",
    "hdr_mode": "auto",
    "mic_enabled": True,
    "mic_volume": 80,
    "status_light_on": False,
    "speaker_volume": 50,
    "motion_detection": True,
}


class TestCameraModel:
    def test_mutable_fields_set(self) -> None:
        assert "name" in MUTABLE_FIELDS
        assert "ir_led_mode" in MUTABLE_FIELDS
        assert "mic_volume" in MUTABLE_FIELDS
        assert "motion_detection" in MUTABLE_FIELDS
        assert "id" not in MUTABLE_FIELDS
        assert "mac" not in MUTABLE_FIELDS

    def test_read_only_fields_set(self) -> None:
        assert "id" in READ_ONLY_FIELDS
        assert "mac" in READ_ONLY_FIELDS
        assert "is_recording" in READ_ONLY_FIELDS
        assert "channels" in READ_ONLY_FIELDS
        assert "name" not in READ_ONLY_FIELDS

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        assert not (MUTABLE_FIELDS & READ_ONLY_FIELDS)

    def test_from_controller_full_payload(self) -> None:
        cam = from_controller(SAMPLE)
        assert cam.id == "cam001"
        assert cam.name == "Front Door"
        assert cam.is_recording is True
        assert cam.ir_led_mode == "auto"
        assert cam.mic_volume == 80
        assert cam.channels == {"0": {"resolution": "3840x2160"}}

    def test_from_controller_handles_missing_fields(self) -> None:
        cam = from_controller({"id": "cam002"})
        assert cam.id == "cam002"
        assert cam.name is None
        assert cam.mic_volume is None
        assert cam.channels is None

    def test_from_controller_drops_non_dict_channels(self) -> None:
        cam = from_controller({"id": "cam003", "channels": "garbage"})
        assert cam.channels is None

    def test_to_controller_update_filters_read_only(self) -> None:
        out = to_controller_update({"id": "cam001", "name": "New", "mic_volume": 75})
        assert "id" not in out
        assert out == {"name": "New", "mic_volume": 75}

    def test_to_controller_update_drops_none_values(self) -> None:
        out = to_controller_update({"name": "New", "mic_volume": None})
        assert out == {"name": "New"}

    def test_to_controller_update_empty_input(self) -> None:
        assert to_controller_update({}) == {}

    def test_mic_volume_constraint_rejects_out_of_range(self) -> None:
        with pytest.raises(Exception):
            Camera(mic_volume=200)
        with pytest.raises(Exception):
            Camera(mic_volume=-1)

    def test_speaker_volume_constraint_rejects_out_of_range(self) -> None:
        with pytest.raises(Exception):
            Camera(speaker_volume=150)

    def test_ir_led_mode_accepts_any_string(self) -> None:
        # ir_led_mode is Optional[str] (not Literal) — controller emits values
        # beyond the documented set (e.g., "normal"); pydantic must not reject.
        assert Camera(ir_led_mode="auto").ir_led_mode == "auto"
        assert Camera(ir_led_mode="autoFilterOnly").ir_led_mode == "autoFilterOnly"
        assert Camera(ir_led_mode="anything").ir_led_mode == "anything"

    def test_hdr_mode_accepts_any_string(self) -> None:
        # hdr_mode is Optional[str] (not Literal) — controllers return "normal"
        # in addition to auto/off/always.
        assert Camera(hdr_mode="auto").hdr_mode == "auto"
        assert Camera(hdr_mode="normal").hdr_mode == "normal"
