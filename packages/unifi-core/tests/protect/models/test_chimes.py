"""Unit tests for the Protect Chime shared field model."""

from __future__ import annotations

import pytest

from unifi_core.protect.models.chimes import (
    Chime,
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    from_controller,
    to_controller_update,
)


SAMPLE = {
    "id": "chime001",
    "mac": "AA:BB:CC:DD:EE:02",
    "name": "Front Chime",
    "model": "UFP-Chime",
    "type": "chime",
    "state": "CONNECTED",
    "is_connected": True,
    "firmware_version": "1.2.3",
    "volume": 75,
    "paired_cameras": ["cam001", "cam002"],
    "ring_settings": {"cam001": {"track_no": 1, "volume": 50}},
    "available_tracks": [{"name": "Default", "track_no": 0}],
    "repeat_times": 2,
}


class TestChimeModel:
    def test_mutable_fields_set(self) -> None:
        assert "name" in MUTABLE_FIELDS
        assert "volume" in MUTABLE_FIELDS
        assert "repeat_times" in MUTABLE_FIELDS
        assert "id" not in MUTABLE_FIELDS
        assert "mac" not in MUTABLE_FIELDS
        assert "paired_cameras" not in MUTABLE_FIELDS

    def test_read_only_fields_set(self) -> None:
        assert "id" in READ_ONLY_FIELDS
        assert "mac" in READ_ONLY_FIELDS
        assert "model" in READ_ONLY_FIELDS
        assert "type" in READ_ONLY_FIELDS
        assert "state" in READ_ONLY_FIELDS
        assert "is_connected" in READ_ONLY_FIELDS
        assert "firmware_version" in READ_ONLY_FIELDS
        assert "paired_cameras" in READ_ONLY_FIELDS
        assert "ring_settings" in READ_ONLY_FIELDS
        assert "available_tracks" in READ_ONLY_FIELDS
        assert "name" not in READ_ONLY_FIELDS
        assert "volume" not in READ_ONLY_FIELDS
        assert "repeat_times" not in READ_ONLY_FIELDS

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        assert not (MUTABLE_FIELDS & READ_ONLY_FIELDS)

    def test_field_count(self) -> None:
        # 10 read-only + 3 mutable = 13 total
        assert len(Chime.model_fields) == 13

    def test_from_controller_full_payload(self) -> None:
        chime = from_controller(SAMPLE)
        assert chime.id == "chime001"
        assert chime.mac == "AA:BB:CC:DD:EE:02"
        assert chime.name == "Front Chime"
        assert chime.model == "UFP-Chime"
        assert chime.type == "chime"
        assert chime.state == "CONNECTED"
        assert chime.is_connected is True
        assert chime.firmware_version == "1.2.3"
        assert chime.volume == 75
        assert chime.paired_cameras == ["cam001", "cam002"]
        assert chime.ring_settings == {"cam001": {"track_no": 1, "volume": 50}}
        assert chime.available_tracks == [{"name": "Default", "track_no": 0}]
        assert chime.repeat_times == 2

    def test_from_controller_handles_missing_fields(self) -> None:
        chime = from_controller({"id": "chime002"})
        assert chime.id == "chime002"
        assert chime.name is None
        assert chime.volume is None
        assert chime.repeat_times is None
        assert chime.paired_cameras == []
        assert chime.ring_settings is None
        assert chime.available_tracks is None

    def test_from_controller_accepts_camera_ids_key(self) -> None:
        """Manager returns camera_ids; model normalises to paired_cameras."""
        raw = {"id": "chime003", "camera_ids": ["cam-a", "cam-b"]}
        chime = from_controller(raw)
        assert chime.paired_cameras == ["cam-a", "cam-b"]

    def test_from_controller_prefers_paired_cameras_over_camera_ids(self) -> None:
        raw = {"paired_cameras": ["cam-x"], "camera_ids": ["cam-y"]}
        chime = from_controller(raw)
        assert chime.paired_cameras == ["cam-x"]

    def test_to_controller_update_filters_read_only(self) -> None:
        out = to_controller_update({"id": "chime001", "name": "New Name", "volume": 60})
        assert "id" not in out
        assert out == {"name": "New Name", "volume": 60}

    def test_to_controller_update_drops_none_values(self) -> None:
        out = to_controller_update({"name": "New", "volume": None})
        assert out == {"name": "New"}

    def test_to_controller_update_empty_input(self) -> None:
        assert to_controller_update({}) == {}

    def test_to_controller_update_filters_read_only_fields(self) -> None:
        out = to_controller_update({
            "mac": "AA:BB:CC",
            "state": "CONNECTED",
            "paired_cameras": ["cam001"],
            "name": "Porch",
        })
        assert "mac" not in out
        assert "state" not in out
        assert "paired_cameras" not in out
        assert out == {"name": "Porch"}

    def test_to_controller_update_all_mutable(self) -> None:
        out = to_controller_update({"name": "Side", "volume": 50, "repeat_times": 3})
        assert out == {"name": "Side", "volume": 50, "repeat_times": 3}

    def test_volume_constraint_rejects_out_of_range(self) -> None:
        with pytest.raises(Exception):
            Chime(volume=101)
        with pytest.raises(Exception):
            Chime(volume=-1)

    def test_repeat_times_constraint_rejects_out_of_range(self) -> None:
        with pytest.raises(Exception):
            Chime(repeat_times=7)
        with pytest.raises(Exception):
            Chime(repeat_times=0)
