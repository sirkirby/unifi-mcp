"""Unit tests for the Access Visitor read/create domain model."""

from __future__ import annotations

from unifi_core.access.models.visitors import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    Visitor,
    from_controller,
    to_controller_create,
)


class TestFieldSets:
    def test_mutable_fields_contains_expected(self) -> None:
        for field in (
            "name",
            "first_name",
            "last_name",
            "valid_from",
            "valid_until",
            "email",
            "phone",
            "company",
            "visit_reason",
            "remarks",
        ):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mutable_fields_excludes_read_only(self) -> None:
        for field in ("id", "host_user_id", "status", "credential_count", "access_policy_ids"):
            assert field not in MUTABLE_FIELDS, f"{field!r} should NOT be in MUTABLE_FIELDS"

    def test_read_only_fields_contains_expected(self) -> None:
        for field in ("id", "host_user_id", "status", "credential_count", "access_policy_ids"):
            assert field in READ_ONLY_FIELDS, f"Expected {field!r} in READ_ONLY_FIELDS"

    def test_read_only_fields_excludes_mutable(self) -> None:
        for field in ("name", "valid_from", "valid_until", "email", "phone"):
            assert field not in READ_ONLY_FIELDS, f"{field!r} should NOT be in READ_ONLY_FIELDS"

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = MUTABLE_FIELDS & READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_mutable_and_read_only_cover_all_model_fields(self) -> None:
        all_fields = frozenset(Visitor.model_fields.keys())
        assert MUTABLE_FIELDS | READ_ONLY_FIELDS == all_fields


class TestFromController:
    def test_full_dict(self) -> None:
        raw = {
            "id": "vis-1",
            "name": "Jane Doe",
            "host_user_id": "user-42",
            "valid_from": "2026-03-17T09:00:00Z",
            "valid_until": "2026-03-17T17:00:00Z",
            "status": "active",
            "credential_count": 2,
            "email": "jane@example.com",
            "phone": "+15551234567",
        }
        v = from_controller(raw)
        assert v.id == "vis-1"
        assert v.name == "Jane Doe"
        assert v.host_user_id == "user-42"
        assert v.valid_from == "2026-03-17T09:00:00Z"
        assert v.valid_until == "2026-03-17T17:00:00Z"
        assert v.status == "active"
        assert v.credential_count == 2
        assert v.email == "jane@example.com"
        assert v.phone == "+15551234567"

    def test_normalizes_developer_api_shape(self) -> None:
        raw = {
            "id": "dev-vis-1",
            "first_name": "Jane",
            "last_name": "Doe",
            "start_time": 1773738000,
            "end_time": 1773766800,
            "status": 6,
            "mobile_phone": "+15551234567",
            "company": "Example Co",
            "visit_reason": "Business",
            "remarks": "Front desk",
            "access_policy_ids": ["policy-uuid"],
            "nfc_cards": [{"id": "nfc-1"}],
            "pin_code": {"token": "secret"},
            "qr_code": None,
            "license_plates": [],
        }

        visitor = from_controller(raw)

        assert visitor.name == "Jane Doe"
        assert visitor.first_name == "Jane"
        assert visitor.last_name == "Doe"
        assert visitor.valid_from == "2026-03-17T09:00:00Z"
        assert visitor.valid_until == "2026-03-17T17:00:00Z"
        assert visitor.status == "active"
        assert visitor.phone == "+15551234567"
        assert visitor.company == "Example Co"
        assert visitor.visit_reason == "Business"
        assert visitor.remarks == "Front desk"
        assert visitor.access_policy_ids == ["policy-uuid"]
        assert visitor.credential_count == 2

    def test_coalesces_access_start_to_valid_from(self) -> None:
        raw = {"id": "vis-2", "access_start": "2026-04-01T08:00:00Z"}
        v = from_controller(raw)
        assert v.valid_from == "2026-04-01T08:00:00Z"

    def test_valid_from_takes_priority_over_access_start(self) -> None:
        raw = {
            "id": "vis-3",
            "valid_from": "2026-05-01T10:00:00Z",
            "access_start": "2026-04-01T08:00:00Z",
        }
        v = from_controller(raw)
        assert v.valid_from == "2026-05-01T10:00:00Z"

    def test_coalesces_access_end_to_valid_until(self) -> None:
        raw = {"id": "vis-4", "access_end": "2026-04-01T18:00:00Z"}
        v = from_controller(raw)
        assert v.valid_until == "2026-04-01T18:00:00Z"

    def test_valid_until_takes_priority_over_access_end(self) -> None:
        raw = {
            "id": "vis-5",
            "valid_until": "2026-06-01T17:00:00Z",
            "access_end": "2026-04-01T18:00:00Z",
        }
        v = from_controller(raw)
        assert v.valid_until == "2026-06-01T17:00:00Z"

    def test_handles_empty_dict(self) -> None:
        v = from_controller({})
        assert v.id is None
        assert v.name is None
        assert v.host_user_id is None
        assert v.valid_from is None
        assert v.valid_until is None
        assert v.status is None
        assert v.credential_count is None
        assert v.email is None
        assert v.phone is None

    def test_handles_partial_dict(self) -> None:
        v = from_controller({"id": "vis-6", "name": "Bob", "status": "expired"})
        assert v.id == "vis-6"
        assert v.name == "Bob"
        assert v.status == "expired"
        assert v.valid_from is None
        assert v.valid_until is None
        assert v.email is None


class TestToControllerCreate:
    def test_full_payload(self) -> None:
        model = Visitor(
            name="Jane Doe",
            valid_from="2026-03-17T09:00:00Z",
            valid_until="2026-03-17T17:00:00Z",
            email="jane@example.com",
            first_name="Jane",
            last_name="Doe",
            phone="+15551234567",
            company="Example Co",
            visit_reason="Business",
            remarks="Disposable",
        )
        payload = to_controller_create(model)
        assert payload == {
            "name": "Jane Doe",
            "access_start": "2026-03-17T09:00:00Z",
            "access_end": "2026-03-17T17:00:00Z",
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane@example.com",
            "phone": "+15551234567",
            "company": "Example Co",
            "visit_reason": "Business",
            "remarks": "Disposable",
        }

    def test_minimal_payload_excludes_email_and_phone(self) -> None:
        model = Visitor(
            name="John Smith",
            valid_from="2026-06-01T08:00:00Z",
            valid_until="2026-06-01T16:00:00Z",
        )
        payload = to_controller_create(model)
        assert "email" not in payload
        assert "phone" not in payload
        assert payload["name"] == "John Smith"
        assert payload["access_start"] == "2026-06-01T08:00:00Z"
        assert payload["access_end"] == "2026-06-01T16:00:00Z"

    def test_renames_valid_from_to_access_start(self) -> None:
        model = Visitor(
            name="Tester",
            valid_from="2026-07-01T09:00:00Z",
            valid_until="2026-07-01T17:00:00Z",
        )
        payload = to_controller_create(model)
        assert "access_start" in payload
        assert "valid_from" not in payload
        assert payload["access_start"] == "2026-07-01T09:00:00Z"

    def test_renames_valid_until_to_access_end(self) -> None:
        model = Visitor(
            name="Tester",
            valid_from="2026-07-01T09:00:00Z",
            valid_until="2026-07-01T17:00:00Z",
        )
        payload = to_controller_create(model)
        assert "access_end" in payload
        assert "valid_until" not in payload
        assert payload["access_end"] == "2026-07-01T17:00:00Z"

    def test_excludes_none_email(self) -> None:
        model = Visitor(
            name="Tester",
            valid_from="2026-08-01T09:00:00Z",
            valid_until="2026-08-01T17:00:00Z",
            email=None,
        )
        payload = to_controller_create(model)
        assert "email" not in payload

    def test_excludes_none_phone(self) -> None:
        model = Visitor(
            name="Tester",
            valid_from="2026-08-01T09:00:00Z",
            valid_until="2026-08-01T17:00:00Z",
            phone=None,
        )
        payload = to_controller_create(model)
        assert "phone" not in payload
