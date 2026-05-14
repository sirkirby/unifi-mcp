"""Unit tests for the Network ClientGroup + UserGroup domain models."""

from __future__ import annotations

from unifi_core.network.models.client_group import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    USERGROUP_MUTABLE_FIELDS,
    USERGROUP_READ_ONLY_FIELDS,
    ClientGroup,
    UserGroup,
    from_controller,
    to_controller_update,
    usergroup_from_controller,
)


class TestClientGroupFieldSets:
    def test_mutable_fields_contains_expected(self) -> None:
        for field in ("name", "members"):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mutable_fields_excludes_read_only(self) -> None:
        for field in ("id", "group_type"):
            assert field not in MUTABLE_FIELDS, f"{field!r} should NOT be in MUTABLE_FIELDS"

    def test_read_only_fields_contains_id_and_type(self) -> None:
        assert "id" in READ_ONLY_FIELDS
        assert "group_type" in READ_ONLY_FIELDS

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = MUTABLE_FIELDS & READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_mutable_and_read_only_cover_all_model_fields(self) -> None:
        all_fields = frozenset(ClientGroup.model_fields.keys())
        assert MUTABLE_FIELDS | READ_ONLY_FIELDS == all_fields


class TestClientGroupFromController:
    def test_full_dict(self) -> None:
        raw = {
            "_id": "cg-1",
            "name": "Kids Devices",
            "type": "CLIENTS",
            "members": ["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"],
        }
        g = from_controller(raw)
        assert g.id == "cg-1"
        assert g.name == "Kids Devices"
        assert g.group_type == "CLIENTS"
        assert g.members == ["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"]

    def test_id_coalesces_underscore_id(self) -> None:
        raw = {"_id": "abc", "name": "Test"}
        g = from_controller(raw)
        assert g.id == "abc"

    def test_id_coalesces_plain_id(self) -> None:
        raw = {"id": "xyz", "name": "Test"}
        g = from_controller(raw)
        assert g.id == "xyz"

    def test_missing_members_defaults_to_empty(self) -> None:
        g = from_controller({"_id": "g1", "name": "Empty"})
        assert g.members == []

    def test_non_list_members_becomes_empty(self) -> None:
        g = from_controller({"_id": "g1", "members": None})
        assert g.members == []

    def test_handles_empty_dict(self) -> None:
        g = from_controller({})
        assert g.id is None
        assert g.name is None
        assert g.group_type is None
        assert g.members == []


class TestToControllerUpdate:
    def test_filters_out_read_only_id(self) -> None:
        result = to_controller_update({"id": "ignore-me", "name": "New Name"})
        assert "id" not in result
        assert result["name"] == "New Name"

    def test_filters_out_group_type(self) -> None:
        result = to_controller_update({"group_type": "CLIENTS", "name": "Test"})
        assert "group_type" not in result

    def test_drops_none_values(self) -> None:
        result = to_controller_update({"name": None, "members": ["aa:bb:cc:dd:ee:ff"]})
        assert "name" not in result
        assert result["members"] == ["aa:bb:cc:dd:ee:ff"]

    def test_passes_mutable_fields(self) -> None:
        result = to_controller_update({"name": "Updated", "members": ["aa:bb:cc:dd:ee:ff"]})
        assert result == {"name": "Updated", "members": ["aa:bb:cc:dd:ee:ff"]}

    def test_empty_list_is_preserved(self) -> None:
        result = to_controller_update({"members": []})
        assert result["members"] == []

    def test_drops_unrecognised_keys(self) -> None:
        result = to_controller_update({"unknown": "value", "name": "Valid"})
        assert "unknown" not in result
        assert result["name"] == "Valid"

    def test_returns_empty_dict_when_no_mutable_fields(self) -> None:
        result = to_controller_update({"id": "read-only"})
        assert result == {}


class TestUserGroupFieldSets:
    def test_all_fields_read_only(self) -> None:
        assert not USERGROUP_MUTABLE_FIELDS, "UserGroup should have no mutable fields"

    def test_read_only_contains_all_fields(self) -> None:
        all_fields = frozenset(UserGroup.model_fields.keys())
        assert USERGROUP_READ_ONLY_FIELDS == all_fields

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = USERGROUP_MUTABLE_FIELDS & USERGROUP_READ_ONLY_FIELDS
        assert not overlap


class TestUserGroupFromController:
    def test_full_dict(self) -> None:
        raw = {
            "_id": "ug-1",
            "name": "Default",
            "qos_rate_max_down": 10000,
            "qos_rate_max_up": 5000,
        }
        g = usergroup_from_controller(raw)
        assert g.id == "ug-1"
        assert g.name == "Default"
        assert g.qos_rate_max_down == 10000
        assert g.qos_rate_max_up == 5000

    def test_id_coalesces_underscore_id(self) -> None:
        raw = {"_id": "abc"}
        g = usergroup_from_controller(raw)
        assert g.id == "abc"

    def test_unlimited_rates_represented_as_negative_one(self) -> None:
        raw = {"_id": "ug-2", "qos_rate_max_down": -1, "qos_rate_max_up": -1}
        g = usergroup_from_controller(raw)
        assert g.qos_rate_max_down == -1
        assert g.qos_rate_max_up == -1

    def test_handles_empty_dict(self) -> None:
        g = usergroup_from_controller({})
        assert g.id is None
        assert g.name is None
        assert g.qos_rate_max_down is None
        assert g.qos_rate_max_up is None
