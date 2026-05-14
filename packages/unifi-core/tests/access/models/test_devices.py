"""Unit tests for the Access Device read-only domain model."""

from __future__ import annotations

from unifi_core.access.models.devices import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    AccessDevice,
    from_controller,
)


class TestFieldSets:
    def test_mutable_fields_is_empty(self) -> None:
        assert MUTABLE_FIELDS == frozenset(), "AccessDevice is read-only; MUTABLE_FIELDS must be empty"

    def test_all_fields_in_read_only(self) -> None:
        all_fields = frozenset(AccessDevice.model_fields.keys())
        assert READ_ONLY_FIELDS == all_fields

    def test_read_only_contains_expected(self) -> None:
        for field in ("id", "name", "type", "is_online", "firmware_version", "location"):
            assert field in READ_ONLY_FIELDS, f"Expected {field!r} in READ_ONLY_FIELDS"

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = MUTABLE_FIELDS & READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_mutable_and_read_only_cover_all_model_fields(self) -> None:
        all_fields = frozenset(AccessDevice.model_fields.keys())
        assert MUTABLE_FIELDS | READ_ONLY_FIELDS == all_fields


class TestFromController:
    def test_full_dict(self) -> None:
        raw = {
            "id": "dev-1",
            "name": "Front Door Reader",
            "type": "UA-Reader-Pro",
            "is_online": True,
            "firmware_version": "3.2.7",
            "location": "Main Entrance",
        }
        d = from_controller(raw)
        assert d.id == "dev-1"
        assert d.name == "Front Door Reader"
        assert d.type == "UA-Reader-Pro"
        assert d.is_online is True
        assert d.firmware_version == "3.2.7"
        assert d.location == "Main Entrance"

    def test_missing_fields_are_none(self) -> None:
        d = from_controller({})
        assert d.id is None
        assert d.name is None
        assert d.type is None
        assert d.is_online is None
        assert d.firmware_version is None
        assert d.location is None

    def test_is_online_false_preserved(self) -> None:
        d = from_controller({"id": "dev-2", "is_online": False})
        assert d.is_online is False

    def test_handles_partial_dict(self) -> None:
        d = from_controller({"id": "dev-3", "name": "Garage Hub", "type": "UA-Hub"})
        assert d.id == "dev-3"
        assert d.name == "Garage Hub"
        assert d.type == "UA-Hub"
        assert d.is_online is None
        assert d.firmware_version is None
        assert d.location is None

    def test_from_object(self) -> None:
        """from_controller works with an attribute-bearing object."""

        class Obj:
            id = "dev-4"
            name = "Side Entrance"
            type = "UA-Lock"
            is_online = True
            firmware_version = "2.1.0"
            location = "Side Door"

        d = from_controller(Obj())
        assert d.id == "dev-4"
        assert d.name == "Side Entrance"
        assert d.type == "UA-Lock"
        assert d.is_online is True
        assert d.firmware_version == "2.1.0"
        assert d.location == "Side Door"

    def test_model_dump_exclude_none_omits_missing(self) -> None:
        d = from_controller({"id": "dev-5", "name": "Hub A"})
        dumped = d.model_dump(exclude_none=True)
        assert "id" in dumped
        assert "name" in dumped
        assert "type" not in dumped
        assert "is_online" not in dumped
        assert "firmware_version" not in dumped
        assert "location" not in dumped
