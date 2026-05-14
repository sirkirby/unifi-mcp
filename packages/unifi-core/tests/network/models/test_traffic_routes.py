"""Unit tests for the Network TrafficRoute CRUD domain model."""

from __future__ import annotations

from unifi_core.network.models.traffic_routes import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    TrafficRoute,
    from_controller,
    to_controller_create,
    to_controller_update,
)


class TestFieldSets:
    def test_mutable_fields_contains_expected_scalars(self) -> None:
        for field in ("name", "matching_target", "network_id", "enabled", "kill_switch_enabled", "next_hop"):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mutable_fields_excludes_read_only(self) -> None:
        assert "id" not in MUTABLE_FIELDS, "'id' should NOT be in MUTABLE_FIELDS"

    def test_read_only_fields_contains_id(self) -> None:
        assert "id" in READ_ONLY_FIELDS

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = MUTABLE_FIELDS & READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"


class TestFromController:
    def test_full_route(self) -> None:
        raw = {
            "_id": "rt-1",
            "description": "VPN Route",
            "matching_target": "DOMAIN",
            "network_id": "net-1",
            "enabled": True,
            "kill_switch_enabled": False,
            "next_hop": "10.0.0.1",
            "domains": [{"domain": "example.com", "ports": []}],
            "target_devices": [{"type": "NETWORK", "network_id": "net-1"}],
        }
        route = from_controller(raw)
        assert route.id == "rt-1"
        assert route.name == "VPN Route"
        assert route.matching_target == "DOMAIN"
        assert route.network_id == "net-1"
        assert route.enabled is True
        assert route.kill_switch_enabled is False
        assert route.next_hop == "10.0.0.1"
        assert route.domains == [{"domain": "example.com", "ports": []}]

    def test_name_falls_back_to_name_field(self) -> None:
        raw = {"_id": "rt-2", "name": "Fallback"}
        route = from_controller(raw)
        assert route.name == "Fallback"

    def test_description_takes_priority_over_name(self) -> None:
        raw = {"_id": "rt-3", "description": "Primary", "name": "Secondary"}
        route = from_controller(raw)
        assert route.name == "Primary"

    def test_id_coalesces_underscore_id(self) -> None:
        raw = {"_id": "abc"}
        route = from_controller(raw)
        assert route.id == "abc"

    def test_handles_empty_dict(self) -> None:
        route = from_controller({})
        assert route.id is None
        assert route.name is None
        assert route.enabled is None


class TestToControllerCreate:
    def test_maps_name_to_description(self) -> None:
        model = TrafficRoute(name="My Route", matching_target="INTERNET", network_id="net-1")
        payload = to_controller_create(model)
        assert payload["description"] == "My Route"
        assert "name" not in payload

    def test_excludes_id(self) -> None:
        model = TrafficRoute(id="should-not-appear", name="Test")
        payload = to_controller_create(model)
        assert "id" not in payload

    def test_includes_list_fields(self) -> None:
        model = TrafficRoute(
            name="Domain Route",
            matching_target="DOMAIN",
            network_id="net-1",
            domains=[{"domain": "example.com", "ports": []}],
            target_devices=[{"type": "NETWORK", "network_id": "net-1"}],
        )
        payload = to_controller_create(model)
        assert "domains" in payload
        assert "target_devices" in payload

    def test_omits_none_fields(self) -> None:
        model = TrafficRoute(name="Minimal", matching_target="INTERNET", network_id="net-1")
        payload = to_controller_create(model)
        assert "next_hop" not in payload
        assert "kill_switch_enabled" not in payload


class TestToControllerUpdate:
    def test_filters_out_id(self) -> None:
        result = to_controller_update({"id": "ignore-me", "enabled": True})
        assert "id" not in result
        assert result["enabled"] is True

    def test_maps_name_to_description(self) -> None:
        result = to_controller_update({"name": "Updated Route"})
        assert "description" in result
        assert result["description"] == "Updated Route"
        assert "name" not in result

    def test_drops_none_values(self) -> None:
        result = to_controller_update({"enabled": None, "kill_switch_enabled": False})
        assert "enabled" not in result
        assert result["kill_switch_enabled"] is False

    def test_toggle_payload(self) -> None:
        result = to_controller_update({"enabled": False})
        assert result == {"enabled": False}

    def test_drops_unrecognised_keys(self) -> None:
        result = to_controller_update({"unknown_key": "value", "enabled": True})
        assert "unknown_key" not in result
        assert result["enabled"] is True

    def test_accepts_list_fields(self) -> None:
        domains = [{"domain": "example.com", "ports": []}]
        result = to_controller_update({"domains": domains})
        assert result["domains"] == domains
