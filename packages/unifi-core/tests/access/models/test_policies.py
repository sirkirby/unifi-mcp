"""Unit tests for the Access Policy read/update domain model."""

from __future__ import annotations

import pytest

from unifi_core.access.models.policies import (
    Policy,
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    from_controller,
    to_controller_update,
)


class TestFieldSets:
    def test_mutable_fields_contains_expected(self) -> None:
        for field in ("name", "schedule_id", "door_ids", "user_group_ids", "enabled"):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mutable_fields_excludes_id(self) -> None:
        assert "id" not in MUTABLE_FIELDS, "'id' should NOT be in MUTABLE_FIELDS"

    def test_read_only_fields_contains_id(self) -> None:
        assert "id" in READ_ONLY_FIELDS, "Expected 'id' in READ_ONLY_FIELDS"

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = MUTABLE_FIELDS & READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_mutable_and_read_only_cover_all_model_fields(self) -> None:
        all_fields = frozenset(Policy.model_fields.keys())
        assert MUTABLE_FIELDS | READ_ONLY_FIELDS == all_fields


class TestFromController:
    def test_full_dict(self) -> None:
        raw = {
            "id": "policy-1",
            "name": "Office Access",
            "schedule_id": "sched-1",
            "door_ids": ["door-1", "door-2"],
            "user_group_ids": ["group-1"],
            "enabled": True,
        }
        p = from_controller(raw)
        assert p.id == "policy-1"
        assert p.name == "Office Access"
        assert p.schedule_id == "sched-1"
        assert p.door_ids == ["door-1", "door-2"]
        assert p.user_group_ids == ["group-1"]
        assert p.enabled is True

    def test_coalesces_doors_into_door_ids(self) -> None:
        """Raw ``doors`` list should be normalised into ``door_ids``."""
        raw = {"id": "p1", "doors": ["door-a", "door-b"]}
        p = from_controller(raw)
        assert p.door_ids == ["door-a", "door-b"]

    def test_coalesces_doors_dict_list(self) -> None:
        """Raw ``doors`` as list-of-dicts should extract ``id`` values."""
        raw = {"id": "p1", "doors": [{"id": "door-x"}, {"id": "door-y"}]}
        p = from_controller(raw)
        assert p.door_ids == ["door-x", "door-y"]

    def test_door_ids_takes_priority_over_doors(self) -> None:
        """When both ``door_ids`` and ``doors`` are present, ``door_ids`` wins."""
        raw = {
            "id": "p1",
            "door_ids": ["door-canonical"],
            "doors": ["door-legacy"],
        }
        p = from_controller(raw)
        assert p.door_ids == ["door-canonical"]

    def test_coalesces_user_groups_into_user_group_ids(self) -> None:
        """Raw ``user_groups`` list should be normalised into ``user_group_ids``."""
        raw = {"id": "p1", "user_groups": ["group-a", "group-b"]}
        p = from_controller(raw)
        assert p.user_group_ids == ["group-a", "group-b"]

    def test_coalesces_user_groups_dict_list(self) -> None:
        """Raw ``user_groups`` as list-of-dicts should extract ``id`` values."""
        raw = {"id": "p1", "user_groups": [{"id": "grp-x"}, {"id": "grp-y"}]}
        p = from_controller(raw)
        assert p.user_group_ids == ["grp-x", "grp-y"]

    def test_user_group_ids_takes_priority_over_user_groups(self) -> None:
        raw = {
            "id": "p1",
            "user_group_ids": ["group-canonical"],
            "user_groups": ["group-legacy"],
        }
        p = from_controller(raw)
        assert p.user_group_ids == ["group-canonical"]

    def test_missing_door_ids_defaults_to_empty_list(self) -> None:
        p = from_controller({"id": "p2"})
        assert p.door_ids == []

    def test_missing_user_group_ids_defaults_to_empty_list(self) -> None:
        p = from_controller({"id": "p2"})
        assert p.user_group_ids == []

    def test_missing_enabled_defaults_to_true(self) -> None:
        p = from_controller({"id": "p3", "name": "Lobby"})
        assert p.enabled is True

    def test_enabled_false_is_preserved(self) -> None:
        p = from_controller({"id": "p4", "enabled": False})
        assert p.enabled is False

    def test_handles_empty_dict(self) -> None:
        p = from_controller({})
        assert p.id is None
        assert p.name is None
        assert p.schedule_id is None
        assert p.door_ids == []
        assert p.user_group_ids == []
        assert p.enabled is True


class TestToControllerUpdate:
    def test_filters_out_read_only_id(self) -> None:
        changes = {"id": "should-be-stripped", "name": "New Name"}
        result = to_controller_update(changes)
        assert "id" not in result
        assert result["name"] == "New Name"

    def test_drops_none_values(self) -> None:
        changes = {"name": None, "schedule_id": "sched-1"}
        result = to_controller_update(changes)
        assert "name" not in result
        assert result["schedule_id"] == "sched-1"

    def test_preserves_boolean_false(self) -> None:
        """``False`` must not be treated as None and silently dropped."""
        changes = {"enabled": False, "name": "Still Active"}
        result = to_controller_update(changes)
        assert result["enabled"] is False
        assert result["name"] == "Still Active"

    def test_preserves_boolean_true(self) -> None:
        changes = {"enabled": True}
        result = to_controller_update(changes)
        assert result["enabled"] is True

    def test_drops_unrecognised_keys(self) -> None:
        changes = {"unknown_field": "value", "name": "Valid"}
        result = to_controller_update(changes)
        assert "unknown_field" not in result
        assert result["name"] == "Valid"

    def test_full_mutable_dict_passes_through(self) -> None:
        changes = {
            "name": "Full Update",
            "schedule_id": "sched-99",
            "door_ids": ["d1", "d2"],
            "user_group_ids": ["g1"],
            "enabled": True,
        }
        result = to_controller_update(changes)
        assert result == changes

    def test_empty_list_is_preserved(self) -> None:
        """An explicit empty list is a valid payload (clears all doors)."""
        changes = {"door_ids": []}
        result = to_controller_update(changes)
        assert result["door_ids"] == []

    def test_returns_empty_dict_when_no_mutable_fields(self) -> None:
        changes = {"id": "read-only-only"}
        result = to_controller_update(changes)
        assert result == {}
