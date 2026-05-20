"""Unit tests for the Access Device read-only domain model."""

from __future__ import annotations

from unifi_core.access.models.devices import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    AccessDevice,
    AccessLocation,
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
    def test_full_dict_with_structured_location(self) -> None:
        """Real UNVR shape: location is a structured dict."""
        raw = {
            "id": "dev-1",
            "name": "Front Door Reader",
            "type": "UA-Reader-Pro",
            "is_online": True,
            "firmware_version": "3.2.7",
            "location": {
                "unique_id": "loc-uuid-1",
                "name": "Front Door",
                "up_id": "parent-uuid",
                "location_type": "door",
                "full_name": "Site - 1F - Front Door",
                "level": 0,
            },
        }
        d = from_controller(raw)
        assert d.id == "dev-1"
        assert d.name == "Front Door Reader"
        assert d.type == "UA-Reader-Pro"
        assert d.is_online is True
        assert d.firmware_version == "3.2.7"
        assert isinstance(d.location, AccessLocation)
        assert d.location.unique_id == "loc-uuid-1"
        assert d.location.name == "Front Door"
        assert d.location.up_id == "parent-uuid"
        assert d.location.location_type == "door"
        assert d.location.full_name == "Site - 1F - Front Door"
        assert d.location.level == 0

    def test_bare_string_location_wrapped_into_name(self) -> None:
        """Legacy/string location is mapped to AccessLocation(name=...)."""
        d = from_controller({"id": "dev-1", "location": "Main Entrance"})
        assert isinstance(d.location, AccessLocation)
        assert d.location.name == "Main Entrance"
        assert d.location.unique_id is None
        assert d.location.location_type is None

    def test_empty_string_location_is_none(self) -> None:
        d = from_controller({"id": "dev-1", "location": "   "})
        assert d.location is None

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

    def test_from_object_with_string_location(self) -> None:
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
        assert d.location is not None
        assert d.location.name == "Side Door"

    def test_partial_location_dict_only_some_fields(self) -> None:
        """Location dict with only some fields populates available subset, leaves rest None."""
        d = from_controller({"id": "dev-5", "location": {"name": "Lobby", "location_type": "floor"}})
        assert d.location is not None
        assert d.location.name == "Lobby"
        assert d.location.location_type == "floor"
        assert d.location.unique_id is None
        assert d.location.full_name is None
        assert d.location.level is None

    def test_unknown_location_value_type_yields_none(self) -> None:
        """Defensive: an unexpected location shape (e.g. a list) yields None rather than crashing."""
        d = from_controller({"id": "dev-6", "location": ["not", "a", "valid", "shape"]})
        assert d.location is None

    def test_model_dump_exclude_none_omits_missing(self) -> None:
        d = from_controller({"id": "dev-5", "name": "Hub A"})
        dumped = d.model_dump(exclude_none=True)
        assert "id" in dumped
        assert "name" in dumped
        assert "type" not in dumped
        assert "is_online" not in dumped
        assert "firmware_version" not in dumped
        assert "location" not in dumped

    def test_model_dump_serializes_nested_location(self) -> None:
        """model_dump produces a nested dict for the location field, not a string."""
        d = from_controller(
            {
                "id": "dev-7",
                "location": {"unique_id": "loc-7", "name": "Roof", "location_type": "floor"},
            }
        )
        dumped = d.model_dump(exclude_none=True)
        assert dumped["location"] == {
            "unique_id": "loc-7",
            "name": "Roof",
            "location_type": "floor",
        }
