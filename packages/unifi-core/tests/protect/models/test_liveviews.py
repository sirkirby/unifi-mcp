"""Unit tests for the Protect Liveview shared field model."""

from __future__ import annotations

import pytest
from unifi_core.protect.models.liveviews import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    Liveview,
    from_controller,
    to_controller_create,
)

SAMPLE = {
    "id": "lv001",
    "name": "Front Yard",
    "layout": 4,
    "is_default": True,
    "is_global": False,
    "owner_id": "user001",
    "cameras": ["cam001", "cam002"],
    "slots": [{"index": 0, "camera": "cam001"}],
    "slot_count": 4,
    "camera_count": 2,
}


class TestLiveviewMutableFields:
    @pytest.mark.parametrize("field", ["name", "cameras"])
    def test_mutable_fields_contains(self, field: str) -> None:
        assert field in MUTABLE_FIELDS

    def test_mutable_fields_excludes_read_only(self) -> None:
        assert "id" not in MUTABLE_FIELDS
        assert "layout" not in MUTABLE_FIELDS
        assert "is_default" not in MUTABLE_FIELDS
        assert "is_global" not in MUTABLE_FIELDS
        assert "owner_id" not in MUTABLE_FIELDS
        assert "slots" not in MUTABLE_FIELDS
        assert "slot_count" not in MUTABLE_FIELDS
        assert "camera_count" not in MUTABLE_FIELDS

    def test_read_only_fields_contains_expected(self) -> None:
        assert "id" in READ_ONLY_FIELDS
        assert "layout" in READ_ONLY_FIELDS
        assert "is_default" in READ_ONLY_FIELDS
        assert "is_global" in READ_ONLY_FIELDS
        assert "owner_id" in READ_ONLY_FIELDS
        assert "slots" in READ_ONLY_FIELDS
        assert "slot_count" in READ_ONLY_FIELDS
        assert "camera_count" in READ_ONLY_FIELDS

    def test_read_only_excludes_mutable(self) -> None:
        assert "name" not in READ_ONLY_FIELDS
        assert "cameras" not in READ_ONLY_FIELDS

    def test_sets_are_disjoint(self) -> None:
        assert not (MUTABLE_FIELDS & READ_ONLY_FIELDS)


class TestFromController:
    def test_full_payload_with_cameras_key(self) -> None:
        lv = from_controller(SAMPLE)
        assert lv.id == "lv001"
        assert lv.name == "Front Yard"
        assert lv.layout == 4
        assert lv.is_default is True
        assert lv.is_global is False
        assert lv.owner_id == "user001"
        assert lv.cameras == ["cam001", "cam002"]
        assert lv.slots == [{"index": 0, "camera": "cam001"}]
        assert lv.slot_count == 4
        assert lv.camera_count == 2

    def test_coalesces_camera_ids_key(self) -> None:
        raw = {
            "id": "lv002",
            "name": "Back Yard",
            "camera_ids": ["cam003", "cam004"],
        }
        lv = from_controller(raw)
        assert lv.cameras == ["cam003", "cam004"]

    def test_cameras_key_takes_precedence_over_camera_ids(self) -> None:
        raw = {
            "id": "lv003",
            "cameras": ["cam001"],
            "camera_ids": ["cam002"],
        }
        lv = from_controller(raw)
        assert lv.cameras == ["cam001"]

    @pytest.mark.parametrize(
        ("field", "expected"),
        [
            ("cameras", []),
            ("slots", None),
        ],
    )
    def test_missing_optional_collection_defaults(self, field: str, expected: object) -> None:
        lv = from_controller({"id": "lv004"})
        assert getattr(lv, field) == expected

    @pytest.mark.parametrize("slots", ["garbage", {"key": "val"}])
    def test_non_list_slots_becomes_none(self, slots: object) -> None:
        lv = from_controller({"id": "lv005", "slots": slots})
        assert lv.slots is None

    def test_handles_missing_optional_fields(self) -> None:
        lv = from_controller({"id": "lv007"})
        assert lv.id == "lv007"
        assert lv.name is None
        assert lv.layout is None
        assert lv.is_default is None
        assert lv.is_global is None
        assert lv.owner_id is None
        assert lv.slot_count is None
        assert lv.camera_count is None


class TestToControllerCreate:
    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            (
                Liveview(name="My View", cameras=["cam001", "cam002"]),
                {"name": "My View", "camera_ids": ["cam001", "cam002"]},
            ),
            (Liveview(name="Test", cameras=["cam-x"]), {"name": "Test", "camera_ids": ["cam-x"]}),
            (Liveview(name=None, cameras=["cam001"]), {"name": "", "camera_ids": ["cam001"]}),
            (Liveview(name="Empty", cameras=[]), {"name": "Empty", "camera_ids": []}),
        ],
    )
    def test_to_controller_create(self, model: Liveview, expected: dict) -> None:
        assert to_controller_create(model) == expected

    def test_roundtrip_from_controller_to_create(self) -> None:
        lv = from_controller(SAMPLE)
        payload = to_controller_create(lv)
        assert payload["name"] == "Front Yard"
        assert payload["camera_ids"] == ["cam001", "cam002"]
