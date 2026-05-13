"""Unit tests for the Access User read-only domain model."""

from __future__ import annotations

import datetime

import pytest

from unifi_core.access.models.users import (
    User,
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    from_controller,
)


class TestFieldSets:
    def test_mutable_fields_is_empty(self) -> None:
        assert MUTABLE_FIELDS == frozenset(), "User is read-only; MUTABLE_FIELDS must be empty"

    def test_all_fields_in_read_only(self) -> None:
        all_fields = frozenset(User.model_fields.keys())
        assert READ_ONLY_FIELDS == all_fields

    def test_read_only_contains_expected(self) -> None:
        for field in ("id", "name", "employee_id", "status", "role", "created_at"):
            assert field in READ_ONLY_FIELDS, f"Expected {field!r} in READ_ONLY_FIELDS"

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = MUTABLE_FIELDS & READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_mutable_and_read_only_cover_all_model_fields(self) -> None:
        all_fields = frozenset(User.model_fields.keys())
        assert MUTABLE_FIELDS | READ_ONLY_FIELDS == all_fields


class TestFromController:
    def test_full_dict(self) -> None:
        raw = {
            "id": "user-1",
            "name": "Alice Smith",
            "employee_id": "EMP-101",
            "status": "active",
            "role": "employee",
            "created_at": "2026-01-15T10:30:00Z",
        }
        u = from_controller(raw)
        assert u.id == "user-1"
        assert u.name == "Alice Smith"
        assert u.employee_id == "EMP-101"
        assert u.status == "active"
        assert u.role == "employee"
        assert u.created_at == "2026-01-15T10:30:00Z"

    def test_missing_fields_are_none(self) -> None:
        u = from_controller({})
        assert u.id is None
        assert u.name is None
        assert u.employee_id is None
        assert u.status is None
        assert u.role is None
        assert u.created_at is None

    def test_handles_partial_dict(self) -> None:
        u = from_controller({"id": "user-2", "name": "Bob Jones", "status": "inactive"})
        assert u.id == "user-2"
        assert u.name == "Bob Jones"
        assert u.status == "inactive"
        assert u.employee_id is None
        assert u.role is None
        assert u.created_at is None

    def test_created_at_from_string(self) -> None:
        u = from_controller({"id": "user-3", "created_at": "2026-03-01T08:00:00Z"})
        assert u.created_at == "2026-03-01T08:00:00Z"

    def test_created_at_from_datetime_object(self) -> None:
        dt = datetime.datetime(2026, 4, 10, 12, 0, 0)
        u = from_controller({"id": "user-4", "created_at": dt})
        assert u.created_at == dt.isoformat()

    def test_created_at_none(self) -> None:
        u = from_controller({"id": "user-5", "created_at": None})
        assert u.created_at is None

    def test_from_object(self) -> None:
        """from_controller works with an attribute-bearing object."""
        class Obj:
            id = "user-6"
            name = "Carol White"
            employee_id = "EMP-202"
            status = "active"
            role = "admin"
            created_at = "2026-02-20T09:00:00Z"

        u = from_controller(Obj())
        assert u.id == "user-6"
        assert u.name == "Carol White"
        assert u.employee_id == "EMP-202"
        assert u.role == "admin"

    def test_model_dump_exclude_none_omits_missing(self) -> None:
        u = from_controller({"id": "user-7", "name": "Dave"})
        dumped = u.model_dump(exclude_none=True)
        assert "id" in dumped
        assert "name" in dumped
        assert "employee_id" not in dumped
        assert "status" not in dumped
        assert "role" not in dumped
        assert "created_at" not in dumped
