"""Unit tests for the Network ApGroup CRUD domain model."""

from __future__ import annotations

from unifi_core.network.models.ap_group import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    ApGroup,
    from_controller,
    to_controller_create,
    to_controller_update,
)


class TestFieldSets:
    def test_mutable_fields_contains_expected(self) -> None:
        for field in ("name", "device_macs", "wlan_group_ids"):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mutable_fields_excludes_read_only(self) -> None:
        for field in ("id", "ap_count"):
            assert field not in MUTABLE_FIELDS, f"{field!r} should NOT be in MUTABLE_FIELDS"

    def test_read_only_fields_contains_id_and_ap_count(self) -> None:
        assert "id" in READ_ONLY_FIELDS
        assert "ap_count" in READ_ONLY_FIELDS

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = MUTABLE_FIELDS & READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_mutable_and_read_only_cover_all_model_fields(self) -> None:
        all_fields = frozenset(ApGroup.model_fields.keys())
        assert MUTABLE_FIELDS | READ_ONLY_FIELDS == all_fields


class TestFromController:
    def test_full_dict(self) -> None:
        raw = {
            "_id": "group-1",
            "name": "Main APs",
            "device_macs": ["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"],
            "wlan_group_ids": ["wlan-group-1"],
        }
        g = from_controller(raw)
        assert g.id == "group-1"
        assert g.name == "Main APs"
        assert g.device_macs == ["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"]
        assert g.wlan_group_ids == ["wlan-group-1"]
        assert g.ap_count == 2

    def test_id_coalesces_underscore_id(self) -> None:
        raw = {"_id": "abc", "name": "Test"}
        g = from_controller(raw)
        assert g.id == "abc"

    def test_id_coalesces_plain_id(self) -> None:
        raw = {"id": "xyz", "name": "Test"}
        g = from_controller(raw)
        assert g.id == "xyz"

    def test_ap_count_derived_from_device_macs(self) -> None:
        raw = {"_id": "g1", "device_macs": ["aa:bb:cc:dd:ee:ff"]}
        g = from_controller(raw)
        assert g.ap_count == 1

    def test_missing_device_macs_defaults_to_empty(self) -> None:
        g = from_controller({"_id": "g1", "name": "Empty"})
        assert g.device_macs == []
        assert g.ap_count == 0

    def test_missing_wlan_group_ids_defaults_to_empty(self) -> None:
        g = from_controller({"_id": "g1"})
        assert g.wlan_group_ids == []

    def test_non_list_device_macs_becomes_empty(self) -> None:
        g = from_controller({"_id": "g1", "device_macs": None})
        assert g.device_macs == []

    def test_handles_empty_dict(self) -> None:
        g = from_controller({})
        assert g.id is None
        assert g.name is None
        assert g.device_macs == []
        assert g.wlan_group_ids == []
        assert g.ap_count == 0


class TestToControllerCreate:
    def test_full_model(self) -> None:
        model = ApGroup(name="My Group", device_macs=["aa:bb:cc:dd:ee:ff"], wlan_group_ids=["wg-1"])
        payload = to_controller_create(model)
        assert payload["name"] == "My Group"
        assert payload["device_macs"] == ["aa:bb:cc:dd:ee:ff"]
        assert payload["wlan_group_ids"] == ["wg-1"]

    def test_name_none_excluded(self) -> None:
        model = ApGroup(device_macs=[], wlan_group_ids=[])
        payload = to_controller_create(model)
        assert "name" not in payload

    def test_empty_lists_included(self) -> None:
        model = ApGroup(name="Test", device_macs=[], wlan_group_ids=[])
        payload = to_controller_create(model)
        assert payload["device_macs"] == []
        assert payload["wlan_group_ids"] == []

    def test_read_only_fields_excluded(self) -> None:
        model = ApGroup(id="should-not-appear", name="Test", ap_count=5)
        payload = to_controller_create(model)
        assert "id" not in payload
        assert "ap_count" not in payload


class TestToControllerUpdate:
    def test_filters_out_read_only_id(self) -> None:
        result = to_controller_update({"id": "ignore-me", "name": "New Name"})
        assert "id" not in result
        assert result["name"] == "New Name"

    def test_filters_out_ap_count(self) -> None:
        result = to_controller_update({"ap_count": 5, "name": "Test"})
        assert "ap_count" not in result

    def test_drops_none_values(self) -> None:
        result = to_controller_update({"name": None, "device_macs": ["aa:bb:cc:dd:ee:ff"]})
        assert "name" not in result
        assert result["device_macs"] == ["aa:bb:cc:dd:ee:ff"]

    def test_passes_mutable_fields(self) -> None:
        result = to_controller_update({"name": "Updated", "device_macs": [], "wlan_group_ids": ["wg-2"]})
        assert result == {"name": "Updated", "device_macs": [], "wlan_group_ids": ["wg-2"]}

    def test_empty_list_is_preserved(self) -> None:
        result = to_controller_update({"device_macs": []})
        assert result["device_macs"] == []

    def test_drops_unrecognised_keys(self) -> None:
        result = to_controller_update({"unknown": "value", "name": "Valid"})
        assert "unknown" not in result
        assert result["name"] == "Valid"

    def test_returns_empty_dict_when_no_mutable_fields(self) -> None:
        result = to_controller_update({"id": "read-only"})
        assert result == {}
