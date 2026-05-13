"""Unit tests for the Access Door / DoorGroup / DoorStatus read-only models."""

from __future__ import annotations

from unifi_core.access.models.doors import (
    Door,
    DoorGroup,
    DoorStatus,
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    door_from_controller,
    door_group_from_controller,
    door_status_from_controller,
)


class TestFieldSets:
    def test_mutable_fields_is_empty(self) -> None:
        assert MUTABLE_FIELDS == frozenset()

    def test_read_only_contains_door_fields(self) -> None:
        for field in ("id", "name", "location", "is_online", "is_locked", "lock_state", "last_event"):
            assert field in READ_ONLY_FIELDS, f"Expected {field!r} in READ_ONLY_FIELDS"

    def test_read_only_contains_door_group_fields(self) -> None:
        for field in ("door_ids",):
            assert field in READ_ONLY_FIELDS, f"Expected {field!r} in READ_ONLY_FIELDS"

    def test_read_only_contains_door_status_fields(self) -> None:
        for field in (
            "door_id",
            "door_position_status",
            "last_event_at",
            "last_event_type",
        ):
            assert field in READ_ONLY_FIELDS, f"Expected {field!r} in READ_ONLY_FIELDS"

    def test_read_only_covers_all_model_fields(self) -> None:
        all_fields = (
            set(Door.model_fields)
            | set(DoorGroup.model_fields)
            | set(DoorStatus.model_fields)
        )
        assert READ_ONLY_FIELDS == frozenset(all_fields)


class TestDoorFromController:
    def test_basic_dict(self) -> None:
        d = door_from_controller({
            "id": "d1",
            "name": "Front Door",
            "location": "Lobby",
            "is_online": True,
            "lock_state": "locked",
            "is_locked": True,
        })
        assert d.id == "d1"
        assert d.name == "Front Door"
        assert d.location == "Lobby"
        assert d.is_online is True
        assert d.lock_state == "locked"
        assert d.is_locked is True

    def test_is_locked_from_explicit_field(self) -> None:
        d = door_from_controller({"id": "d1", "is_locked": False})
        assert d.is_locked is False

    def test_is_locked_from_relay_status_lock(self) -> None:
        d = door_from_controller({"id": "d1", "lock_relay_status": "lock"})
        assert d.is_locked is True

    def test_is_locked_from_relay_status_unlock(self) -> None:
        d = door_from_controller({"id": "d1", "lock_relay_status": "unlock"})
        assert d.is_locked is False

    def test_is_locked_none_when_absent(self) -> None:
        d = door_from_controller({"id": "d1"})
        assert d.is_locked is None

    def test_explicit_is_locked_takes_priority_over_relay(self) -> None:
        # Explicit False wins even when relay says "lock"
        d = door_from_controller({"id": "d1", "is_locked": False, "lock_relay_status": "lock"})
        assert d.is_locked is False

    def test_location_falls_back_to_location_type(self) -> None:
        d = door_from_controller({"id": "d1", "location_type": "Main Entrance"})
        assert d.location == "Main Entrance"

    def test_lock_state_falls_back_to_relay_status(self) -> None:
        d = door_from_controller({"id": "d1", "lock_relay_status": "lock"})
        assert d.lock_state == "lock"

    def test_last_event_normalised_from_dict(self) -> None:
        d = door_from_controller({
            "id": "d1",
            "last_event": {"name": "door_open", "timestamp": "2026-05-12T10:00:00Z"},
        })
        assert isinstance(d.last_event, dict)
        assert d.last_event["name"] == "door_open"
        assert d.last_event["timestamp"] == "2026-05-12T10:00:00Z"

    def test_last_event_timestamp_falls_back_to_created_at(self) -> None:
        d = door_from_controller({
            "id": "d1",
            "last_event": {"name": "door_close", "created_at": "2026-05-12T11:00:00Z"},
        })
        assert d.last_event["timestamp"] == "2026-05-12T11:00:00Z"

    def test_last_event_none_when_absent(self) -> None:
        d = door_from_controller({"id": "d1"})
        assert d.last_event is None

    def test_handles_empty_dict(self) -> None:
        d = door_from_controller({})
        assert d.id is None
        assert d.name is None
        assert d.is_locked is None


class TestDoorGroupFromController:
    def test_basic_dict(self) -> None:
        g = door_group_from_controller({
            "id": "g1",
            "name": "All Doors",
            "door_ids": ["d1", "d2"],
            "location": "Building A",
        })
        assert g.id == "g1"
        assert g.name == "All Doors"
        assert g.door_ids == ["d1", "d2"]
        assert g.location == "Building A"

    def test_door_ids_from_door_ids_field(self) -> None:
        g = door_group_from_controller({"id": "g1", "door_ids": ["d1", "d2", "d3"]})
        assert g.door_ids == ["d1", "d2", "d3"]

    def test_door_ids_coalesced_from_resources(self) -> None:
        g = door_group_from_controller({
            "id": "g1",
            "resources": [{"id": "d1"}, {"id": "d2"}],
        })
        assert g.door_ids == ["d1", "d2"]

    def test_door_ids_resources_skips_none_entries(self) -> None:
        g = door_group_from_controller({
            "id": "g1",
            "resources": [{"id": "d1"}, None, {"id": "d3"}],
        })
        assert g.door_ids == ["d1", "d3"]

    def test_door_ids_empty_when_neither_present(self) -> None:
        g = door_group_from_controller({"id": "g1"})
        assert g.door_ids == []

    def test_door_ids_takes_priority_over_resources(self) -> None:
        g = door_group_from_controller({
            "id": "g1",
            "door_ids": ["d1"],
            "resources": [{"id": "d2"}, {"id": "d3"}],
        })
        # door_ids wins
        assert g.door_ids == ["d1"]

    def test_location_falls_back_to_location_type(self) -> None:
        g = door_group_from_controller({"id": "g1", "location_type": "Floor 2"})
        assert g.location == "Floor 2"

    def test_handles_empty_dict(self) -> None:
        g = door_group_from_controller({})
        assert g.id is None
        assert g.door_ids == []


class TestDoorStatusFromController:
    def test_basic_dict(self) -> None:
        s = door_status_from_controller({
            "door_id": "d1",
            "name": "Front Door",
            "lock_state": "locked",
            "is_locked": True,
            "door_position_status": "closed",
        })
        assert s.door_id == "d1"
        assert s.name == "Front Door"
        assert s.lock_state == "locked"
        assert s.is_locked is True
        assert s.door_position_status == "closed"

    def test_door_id_falls_back_to_id(self) -> None:
        s = door_status_from_controller({"id": "d2"})
        assert s.door_id == "d2"

    def test_last_event_flattened_to_at_and_type(self) -> None:
        s = door_status_from_controller({
            "door_id": "d1",
            "last_event": {"name": "door_open", "timestamp": "2026-05-12T10:00:00Z"},
        })
        assert s.last_event_at == "2026-05-12T10:00:00Z"
        assert s.last_event_type == "door_open"

    def test_last_event_timestamp_falls_back_to_created_at(self) -> None:
        s = door_status_from_controller({
            "door_id": "d1",
            "last_event": {"name": "door_close", "created_at": "2026-05-12T11:00:00Z"},
        })
        assert s.last_event_at == "2026-05-12T11:00:00Z"

    def test_last_event_none_when_absent(self) -> None:
        s = door_status_from_controller({"door_id": "d1"})
        assert s.last_event_at is None
        assert s.last_event_type is None

    def test_last_event_none_explicit(self) -> None:
        s = door_status_from_controller({"door_id": "d1", "last_event": None})
        assert s.last_event_at is None
        assert s.last_event_type is None

    def test_is_locked_from_relay_status(self) -> None:
        s = door_status_from_controller({"door_id": "d1", "lock_relay_status": "lock"})
        assert s.is_locked is True

    def test_handles_empty_dict(self) -> None:
        s = door_status_from_controller({})
        assert s.door_id is None
        assert s.is_locked is None
        assert s.last_event_at is None
