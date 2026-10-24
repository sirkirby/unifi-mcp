"""Unit tests for the Network ClientGroup + UserGroup domain models."""

from __future__ import annotations

import pytest
from unifi_core.network.models.client_group import (
    USERGROUP_MUTABLE_FIELDS,
    from_controller,
    to_controller_update,
    usergroup_from_controller,
)

from .model_assertions import assert_fields


class TestClientGroupFromController:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (
                {
                    "_id": "cg-1",
                    "name": "Kids Devices",
                    "type": "CLIENTS",
                    "members": ["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"],
                },
                {
                    "id": "cg-1",
                    "name": "Kids Devices",
                    "group_type": "CLIENTS",
                    "members": ["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"],
                },
            ),
            ({"_id": "abc", "name": "Test"}, {"id": "abc"}),
            ({"id": "xyz", "name": "Test"}, {"id": "xyz"}),
            ({"_id": "g1", "name": "Empty"}, {"members": []}),
            ({"_id": "g1", "members": None}, {"members": []}),
            ({}, {"id": None, "name": None, "group_type": None, "members": []}),
        ],
        ids=[
            "full_dict",
            "id_coalesces_underscore_id",
            "id_coalesces_plain_id",
            "missing_members_defaults_to_empty",
            "non_list_members_becomes_empty",
            "handles_empty_dict",
        ],
    )
    def test_from_controller_fields(self, raw, expected) -> None:
        result = from_controller(raw)
        assert_fields(result, expected)


class TestToControllerUpdate:
    def test_passes_mutable_fields(self) -> None:
        result = to_controller_update({"name": "Updated", "members": ["aa:bb:cc:dd:ee:ff"]})
        assert result == {"name": "Updated", "members": ["aa:bb:cc:dd:ee:ff"]}

    def test_empty_list_is_preserved(self) -> None:
        result = to_controller_update({"members": []})
        assert result["members"] == []


class TestUserGroupFieldSets:
    def test_all_fields_read_only(self) -> None:
        assert not USERGROUP_MUTABLE_FIELDS, "UserGroup should have no mutable fields"


class TestUserGroupFromController:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (
                {"_id": "ug-1", "name": "Default", "qos_rate_max_down": 10000, "qos_rate_max_up": 5000},
                {"id": "ug-1", "name": "Default", "qos_rate_max_down": 10000, "qos_rate_max_up": 5000},
            ),
            ({"_id": "abc"}, {"id": "abc"}),
            (
                {"_id": "ug-2", "qos_rate_max_down": -1, "qos_rate_max_up": -1},
                {"qos_rate_max_down": -1, "qos_rate_max_up": -1},
            ),
            ({}, {"id": None, "name": None, "qos_rate_max_down": None, "qos_rate_max_up": None}),
        ],
        ids=[
            "full_dict",
            "id_coalesces_underscore_id",
            "unlimited_rates_represented_as_negative_one",
            "handles_empty_dict",
        ],
    )
    def test_usergroup_from_controller_fields(self, raw, expected) -> None:
        result = usergroup_from_controller(raw)
        assert_fields(result, expected)
