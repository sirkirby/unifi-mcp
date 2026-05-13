"""Unit tests for the Access Credential read/create domain model."""

from __future__ import annotations

import pytest

from unifi_core.access.models.credentials import (
    Credential,
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    from_controller,
    to_controller_create,
)


class TestFieldSets:
    def test_mutable_fields_contains_expected(self) -> None:
        for field in ("type", "user_id", "token", "pin_code"):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mutable_fields_excludes_read_only(self) -> None:
        for field in ("id", "status", "expiry", "last_used"):
            assert field not in MUTABLE_FIELDS, f"{field!r} should NOT be in MUTABLE_FIELDS"

    def test_read_only_fields_contains_expected(self) -> None:
        for field in ("id", "status", "expiry", "last_used"):
            assert field in READ_ONLY_FIELDS, f"Expected {field!r} in READ_ONLY_FIELDS"

    def test_read_only_fields_excludes_mutable(self) -> None:
        for field in ("type", "user_id", "token", "pin_code"):
            assert field not in READ_ONLY_FIELDS, f"{field!r} should NOT be in READ_ONLY_FIELDS"

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = MUTABLE_FIELDS & READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_mutable_and_read_only_cover_all_model_fields(self) -> None:
        all_fields = frozenset(Credential.model_fields.keys())
        assert MUTABLE_FIELDS | READ_ONLY_FIELDS == all_fields


class TestFromController:
    def test_full_dict(self) -> None:
        raw = {
            "id": "cred-1",
            "type": "nfc",
            "status": "active",
            "expiry": "2027-01-01T00:00:00Z",
            "last_used": "2026-05-01T12:00:00Z",
            "user_id": "user-1",
            "token": "AABBCCDD",
            "pin_code": None,
        }
        c = from_controller(raw)
        assert c.id == "cred-1"
        assert c.type == "nfc"
        assert c.status == "active"
        assert c.expiry == "2027-01-01T00:00:00Z"
        assert c.last_used == "2026-05-01T12:00:00Z"
        assert c.user_id == "user-1"
        assert c.token == "AABBCCDD"
        assert c.pin_code is None

    def test_coalesces_last_used_at(self) -> None:
        raw = {"id": "c1", "last_used_at": "2026-04-01T08:00:00Z"}
        c = from_controller(raw)
        assert c.last_used == "2026-04-01T08:00:00Z"

    def test_last_used_takes_priority_over_last_used_at(self) -> None:
        raw = {
            "id": "c1",
            "last_used": "2026-05-01T10:00:00Z",
            "last_used_at": "2026-04-01T08:00:00Z",
        }
        c = from_controller(raw)
        assert c.last_used == "2026-05-01T10:00:00Z"

    def test_coalesces_expires_at(self) -> None:
        raw = {"id": "c1", "expires_at": "2028-12-31T00:00:00Z"}
        c = from_controller(raw)
        assert c.expiry == "2028-12-31T00:00:00Z"

    def test_expiry_takes_priority_over_expires_at(self) -> None:
        raw = {
            "id": "c1",
            "expiry": "2027-06-01T00:00:00Z",
            "expires_at": "2028-12-31T00:00:00Z",
        }
        c = from_controller(raw)
        assert c.expiry == "2027-06-01T00:00:00Z"

    def test_handles_empty_dict(self) -> None:
        c = from_controller({})
        assert c.id is None
        assert c.type is None
        assert c.status is None
        assert c.expiry is None
        assert c.last_used is None
        assert c.user_id is None
        assert c.token is None
        assert c.pin_code is None

    def test_handles_partial_dict(self) -> None:
        c = from_controller({"id": "c2", "type": "pin", "status": "active"})
        assert c.id == "c2"
        assert c.type == "pin"
        assert c.status == "active"
        assert c.token is None
        assert c.pin_code is None

    def test_accepts_object_with_attributes(self) -> None:
        class Obj:
            id = "c3"
            type = "mobile"
            status = "active"
            expiry = None
            last_used = None
            last_used_at = None
            expires_at = None
            user_id = "user-99"
            token = None
            pin_code = None

        c = from_controller(Obj())
        assert c.id == "c3"
        assert c.type == "mobile"
        assert c.user_id == "user-99"


class TestToControllerCreate:
    def test_nfc_emits_type_user_id_token(self) -> None:
        model = Credential(type="nfc", user_id="u1", token="DEADBEEF")
        payload = to_controller_create(model)
        assert payload["credential_type"] == "nfc"
        assert payload["data"] == {"user_id": "u1", "token": "DEADBEEF"}

    def test_pin_emits_type_user_id_pin_code(self) -> None:
        model = Credential(type="pin", user_id="u2", pin_code="1234")
        payload = to_controller_create(model)
        assert payload["credential_type"] == "pin"
        assert payload["data"] == {"user_id": "u2", "pin_code": "1234"}

    def test_mobile_emits_type_user_id_only(self) -> None:
        model = Credential(type="mobile", user_id="u3")
        payload = to_controller_create(model)
        assert payload["credential_type"] == "mobile"
        assert payload["data"] == {"user_id": "u3"}
        assert "token" not in payload["data"]
        assert "pin_code" not in payload["data"]

    def test_excludes_none_token(self) -> None:
        model = Credential(type="pin", user_id="u4", pin_code="9999", token=None)
        payload = to_controller_create(model)
        assert "token" not in payload["data"]

    def test_excludes_none_pin_code(self) -> None:
        model = Credential(type="nfc", user_id="u5", token="CAFE", pin_code=None)
        payload = to_controller_create(model)
        assert "pin_code" not in payload["data"]

    def test_excludes_none_user_id(self) -> None:
        model = Credential(type="mobile", user_id=None)
        payload = to_controller_create(model)
        assert "user_id" not in payload["data"]
