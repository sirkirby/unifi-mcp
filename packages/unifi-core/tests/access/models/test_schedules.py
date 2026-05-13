"""Unit tests for the Access Schedule read-only domain model."""

from __future__ import annotations

import pytest

from unifi_core.access.models.schedules import (
    Schedule,
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    from_controller,
)


class TestFieldSets:
    def test_mutable_fields_is_empty(self) -> None:
        assert MUTABLE_FIELDS == frozenset(), "Schedule is read-only; MUTABLE_FIELDS must be empty"

    def test_all_fields_in_read_only(self) -> None:
        all_fields = frozenset(Schedule.model_fields.keys())
        assert READ_ONLY_FIELDS == all_fields

    def test_read_only_contains_expected(self) -> None:
        for field in ("id", "name", "weekly_pattern", "enabled"):
            assert field in READ_ONLY_FIELDS, f"Expected {field!r} in READ_ONLY_FIELDS"

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = MUTABLE_FIELDS & READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_mutable_and_read_only_cover_all_model_fields(self) -> None:
        all_fields = frozenset(Schedule.model_fields.keys())
        assert MUTABLE_FIELDS | READ_ONLY_FIELDS == all_fields


class TestFromController:
    def test_full_dict(self) -> None:
        raw = {
            "id": "sched-1",
            "name": "Business Hours",
            "weekly_pattern": {"mon": [{"start": "08:00", "end": "18:00"}]},
            "enabled": True,
        }
        s = from_controller(raw)
        assert s.id == "sched-1"
        assert s.name == "Business Hours"
        assert s.weekly_pattern == {"mon": [{"start": "08:00", "end": "18:00"}]}
        assert s.enabled is True

    def test_weekly_pattern_as_list(self) -> None:
        """weekly_pattern accepts a list (pass-through for any JSON shape)."""
        raw = {
            "id": "sched-2",
            "weekly_pattern": [{"day": "mon", "blocks": []}],
        }
        s = from_controller(raw)
        assert isinstance(s.weekly_pattern, list)
        assert s.weekly_pattern[0]["day"] == "mon"

    def test_weekly_pattern_none(self) -> None:
        s = from_controller({"id": "sched-3"})
        assert s.weekly_pattern is None

    def test_missing_fields_are_none(self) -> None:
        s = from_controller({})
        assert s.id is None
        assert s.name is None
        assert s.weekly_pattern is None
        assert s.enabled is None

    def test_enabled_false_preserved(self) -> None:
        s = from_controller({"id": "sched-4", "enabled": False})
        assert s.enabled is False

    def test_handles_partial_dict(self) -> None:
        s = from_controller({"id": "sched-5", "name": "Night Hours", "enabled": True})
        assert s.id == "sched-5"
        assert s.name == "Night Hours"
        assert s.enabled is True
        assert s.weekly_pattern is None

    def test_from_object(self) -> None:
        """from_controller works with an attribute-bearing object."""
        class Obj:
            id = "sched-6"
            name = "Weekend"
            weekly_pattern = {"sat": [], "sun": []}
            enabled = True

        s = from_controller(Obj())
        assert s.id == "sched-6"
        assert s.weekly_pattern == {"sat": [], "sun": []}

    def test_weekly_pattern_nested_dict(self) -> None:
        """Nested JSON structure passes through unchanged."""
        pattern = {
            "mon": [{"start": "09:00", "end": "17:00"}],
            "fri": [{"start": "09:00", "end": "13:00"}],
        }
        s = from_controller({"id": "sched-7", "weekly_pattern": pattern})
        assert s.weekly_pattern == pattern
