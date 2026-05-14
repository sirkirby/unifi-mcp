"""Unit tests for the Network OonPolicy CRUD domain model."""

from __future__ import annotations

from unifi_core.network.models.oon import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    OonPolicy,
    from_controller,
    to_controller_create,
    to_controller_update,
)


class TestFieldSets:
    def test_mutable_fields_contains_expected(self) -> None:
        for field in ("name", "enabled", "target_type", "targets", "secure", "qos", "route"):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mutable_fields_contains_qos_enabled_and_route_enabled(self) -> None:
        # These were silent-drop bugs (issue #137)
        assert "qos_enabled" in MUTABLE_FIELDS
        assert "route_enabled" in MUTABLE_FIELDS

    def test_mutable_fields_excludes_read_only(self) -> None:
        for field in ("id", "restriction_level"):
            assert field not in MUTABLE_FIELDS, f"{field!r} should NOT be in MUTABLE_FIELDS"

    def test_read_only_fields_contains_id_and_restriction_level(self) -> None:
        assert "id" in READ_ONLY_FIELDS
        assert "restriction_level" in READ_ONLY_FIELDS

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = MUTABLE_FIELDS & READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_mutable_and_read_only_cover_all_model_fields(self) -> None:
        all_fields = frozenset(OonPolicy.model_fields.keys())
        assert MUTABLE_FIELDS | READ_ONLY_FIELDS == all_fields


class TestFromController:
    def test_full_policy(self) -> None:
        raw = {
            "_id": "oon-1",
            "name": "Bedtime Policy",
            "enabled": True,
            "target_type": "CLIENTS",
            "targets": ["aa:bb:cc:dd:ee:ff"],
            "restriction_level": "high",
            "qos": {"enabled": True, "mode": "LIMIT"},
            "route": {"enabled": False, "mode": "OFF"},
            "secure": {"enabled": True},
        }
        p = from_controller(raw)
        assert p.id == "oon-1"
        assert p.name == "Bedtime Policy"
        assert p.enabled is True
        assert p.target_type == "CLIENTS"
        assert p.targets == ["aa:bb:cc:dd:ee:ff"]
        assert p.restriction_level == "high"
        assert p.qos_enabled is True
        assert p.route_enabled is False

    def test_id_coalesces_underscore_id(self) -> None:
        raw = {"_id": "abc", "name": "Test"}
        p = from_controller(raw)
        assert p.id == "abc"

    def test_id_coalesces_plain_id(self) -> None:
        raw = {"id": "xyz", "name": "Test"}
        p = from_controller(raw)
        assert p.id == "xyz"

    def test_qos_enabled_extracted_from_qos_block(self) -> None:
        raw = {"_id": "p1", "qos": {"enabled": True}}
        p = from_controller(raw)
        assert p.qos_enabled is True

    def test_route_enabled_extracted_from_route_block(self) -> None:
        raw = {"_id": "p1", "route": {"enabled": False}}
        p = from_controller(raw)
        assert p.route_enabled is False

    def test_missing_qos_gives_none(self) -> None:
        raw = {"_id": "p1"}
        p = from_controller(raw)
        assert p.qos is None
        assert p.qos_enabled is None

    def test_targets_defaults_to_empty_list(self) -> None:
        raw = {"_id": "p1", "name": "Empty"}
        p = from_controller(raw)
        assert p.targets == []

    def test_applies_to_mirrors_targets(self) -> None:
        raw = {"_id": "p1", "targets": ["mac-1", "mac-2"]}
        p = from_controller(raw)
        assert p.applies_to == ["mac-1", "mac-2"]

    def test_handles_empty_dict(self) -> None:
        p = from_controller({})
        assert p.id is None
        assert p.name is None
        assert p.targets == []


class TestToControllerCreate:
    def test_full_model(self) -> None:
        model = OonPolicy(
            name="Test Policy",
            enabled=True,
            target_type="CLIENTS",
            targets=["aa:bb:cc:dd:ee:ff"],
            qos={"enabled": False},
        )
        payload = to_controller_create(model)
        assert payload["name"] == "Test Policy"
        assert payload["enabled"] is True
        assert payload["target_type"] == "CLIENTS"
        assert payload["targets"] == ["aa:bb:cc:dd:ee:ff"]
        assert payload["qos"] == {"enabled": False}

    def test_read_only_fields_excluded(self) -> None:
        model = OonPolicy(id="should-not-appear", name="Test")
        payload = to_controller_create(model)
        assert "id" not in payload
        assert "restriction_level" not in payload


class TestToControllerUpdate:
    def test_filters_out_read_only_id(self) -> None:
        result = to_controller_update({"id": "ignore-me", "name": "New Name"})
        assert "id" not in result
        assert result["name"] == "New Name"

    def test_drops_none_values(self) -> None:
        result = to_controller_update({"name": None, "enabled": True})
        assert "name" not in result
        assert result["enabled"] is True

    def test_passes_qos_enabled(self) -> None:
        result = to_controller_update({"qos_enabled": True})
        assert result["qos_enabled"] is True

    def test_passes_route_enabled(self) -> None:
        result = to_controller_update({"route_enabled": False})
        assert result["route_enabled"] is False
        result2 = to_controller_update({"route_enabled": True})
        assert result2["route_enabled"] is True

    def test_drops_unrecognised_keys(self) -> None:
        result = to_controller_update({"unknown": "value", "name": "Valid"})
        assert "unknown" not in result
        assert result["name"] == "Valid"

    def test_returns_empty_dict_when_no_mutable_fields(self) -> None:
        result = to_controller_update({"id": "read-only"})
        assert result == {}

    def test_toggle_payload(self) -> None:
        result = to_controller_update({"enabled": True})
        assert result == {"enabled": True}
