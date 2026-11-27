"""Unit tests for the Access User read-only domain model."""

from __future__ import annotations

import datetime

from unifi_core.access.models.users import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    User,
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


def _row(**overrides):
    """A user row as the UniFi OS Users application returns it."""
    row = {
        "unique_id": "5b1c2d3e-0000-4000-8000-000000000001",
        "full_name": "Alice Smith",
        "first_name": "Alice",
        "last_name": "Smith",
        "employee_number": "EMP-101",
        "status": "ACTIVE",
        "user_status": "ACTIVE",
        "roles": [{"unique_id": "role-1", "name": "Super Admin", "system_key": "super_administrator", "level": 2}],
        "create_time": 1768473000,
        "email": "alice@example.com",
    }
    row.update(overrides)
    return row


class TestFromController:
    def test_reads_the_users_application_field_names(self) -> None:
        u = from_controller(_row())
        assert u.id == "5b1c2d3e-0000-4000-8000-000000000001"
        assert u.name == "Alice Smith"
        assert u.employee_id == "EMP-101"
        assert u.status == "ACTIVE"
        assert u.role == "Super Admin"
        assert u.created_at == "2026-01-15T10:30:00Z"

    def test_missing_fields_are_none(self) -> None:
        u = from_controller({})
        assert u.model_dump() == {f: None for f in User.model_fields}

    def test_empty_employee_number_is_absent(self) -> None:
        assert from_controller(_row(employee_number="")).employee_id is None

    def test_user_without_roles_has_no_role(self) -> None:
        assert from_controller(_row(roles=[])).role is None

    def test_role_is_the_first_named_role(self) -> None:
        roles = [{"unique_id": "r0"}, {"name": "Viewer"}, {"name": "Owner"}]
        assert from_controller(_row(roles=roles)).role == "Viewer"

    def test_private_role_is_labelled_by_its_system_key(self) -> None:
        role = {
            "name": "role_private_1794462254133",
            "is_private": True,
            "system_key": "custom_administrator_c8086f51-0ddf-4c3e-81cb-0bb21f395650",
        }
        assert from_controller(_row(roles=[role])).role == "custom_administrator"

    def test_private_role_without_system_key_falls_back_to_name(self) -> None:
        role = {"name": "role_private_1", "is_private": True}
        assert from_controller(_row(roles=[role])).role == "role_private_1"

    def test_malformed_roles_are_skipped(self) -> None:
        assert from_controller(_row(roles="Owner")).role is None
        assert from_controller(_row(roles=["Owner", {"name": ""}])).role is None

    def test_created_at_from_datetime_object(self) -> None:
        dt = datetime.datetime(2026, 4, 10, 12, 0, 0)
        assert from_controller(_row(create_time=dt)).created_at == dt.isoformat()

    def test_created_at_none(self) -> None:
        assert from_controller(_row(create_time=None)).created_at is None

    def test_model_names_are_not_read(self) -> None:
        """Only the Users application's names map; the model's own names are not a controller shape."""
        u = from_controller({"id": "user-1", "name": "Alice", "employee_id": "E1", "role": "admin", "created_at": "x"})
        assert u.model_dump(exclude_none=True) == {}

    def test_model_dump_exclude_none_omits_missing(self) -> None:
        dumped = from_controller({"unique_id": "u-7", "full_name": "Dave"}).model_dump(exclude_none=True)
        assert dumped == {"id": "u-7", "name": "Dave"}
