"""Unit tests for the Network ApGroup CRUD domain model."""

from __future__ import annotations

import pytest
from unifi_core.network.models.ap_group import (
    ApGroup,
    from_controller,
    to_controller_create,
    to_controller_update,
)

from .model_assertions import assert_fields


class TestFromController:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (
                {
                    "_id": "group-1",
                    "name": "Main APs",
                    "device_macs": ["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"],
                    "wlan_group_ids": ["wlan-group-1"],
                },
                {
                    "id": "group-1",
                    "name": "Main APs",
                    "device_macs": ["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"],
                    "wlan_group_ids": ["wlan-group-1"],
                    "ap_count": 2,
                },
            ),
            ({"_id": "abc", "name": "Test"}, {"id": "abc"}),
            ({"id": "xyz", "name": "Test"}, {"id": "xyz"}),
            ({"_id": "g1", "device_macs": ["aa:bb:cc:dd:ee:ff"]}, {"ap_count": 1}),
            ({"_id": "g1", "name": "Empty"}, {"device_macs": [], "ap_count": 0}),
            ({"_id": "g1"}, {"wlan_group_ids": []}),
            ({"_id": "g1", "device_macs": None}, {"device_macs": []}),
            ({}, {"id": None, "name": None, "device_macs": [], "wlan_group_ids": [], "ap_count": 0}),
        ],
        ids=[
            "full_dict",
            "id_coalesces_underscore_id",
            "id_coalesces_plain_id",
            "ap_count_derived_from_device_macs",
            "missing_device_macs_defaults_to_empty",
            "missing_wlan_group_ids_defaults_to_empty",
            "non_list_device_macs_becomes_empty",
            "handles_empty_dict",
        ],
    )
    def test_from_controller_fields(self, raw, expected) -> None:
        result = from_controller(raw)
        assert_fields(result, expected)


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


class TestToControllerUpdate:
    def test_passes_mutable_fields(self) -> None:
        result = to_controller_update({"name": "Updated", "device_macs": [], "wlan_group_ids": ["wg-2"]})
        assert result == {"name": "Updated", "device_macs": [], "wlan_group_ids": ["wg-2"]}

    def test_empty_list_is_preserved(self) -> None:
        result = to_controller_update({"device_macs": []})
        assert result["device_macs"] == []
