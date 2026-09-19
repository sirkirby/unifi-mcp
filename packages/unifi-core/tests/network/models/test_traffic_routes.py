"""Unit tests for the Network TrafficRoute CRUD domain model."""

from __future__ import annotations

from typing import Any

import pytest
from unifi_core.network.models.traffic_routes import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    TrafficRoute,
    build_traffic_route_create_payload,
    from_controller,
    to_controller_create,
    to_controller_update,
    validate_update,
)


class TestFieldSets:
    def test_mutable_fields_contains_expected_updates(self) -> None:
        for field in ("name", "enabled", "kill_switch_enabled", "next_hop"):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_create_only_fields_are_read_only_for_updates(self) -> None:
        fields = {"matching_target", "network_id"}

        assert not fields & MUTABLE_FIELDS
        assert fields <= READ_ONLY_FIELDS

    def test_update_capable_target_lists_are_mutable_not_read_only(self) -> None:
        fields = {"domains", "ip_addresses", "ip_ranges", "regions", "target_devices"}

        assert fields <= MUTABLE_FIELDS
        assert not fields & READ_ONLY_FIELDS

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
        model = TrafficRoute(
            name="My Route",
            matching_target="DOMAIN",
            network_id="net-1",
            domains=[{"domain": "example.com"}],
        )
        payload = to_controller_create(model)
        assert payload["description"] == "My Route"
        assert "name" not in payload

    def test_uses_canonical_safe_create_serializer(self) -> None:
        model = TrafficRoute(
            name="My Route",
            matching_target="DOMAIN",
            network_id="net-1",
            domains=[{"domain": "example.com"}],
        )

        assert to_controller_create(model) == build_traffic_route_create_payload(
            description="My Route",
            matching_target="DOMAIN",
            network_id="net-1",
            domains=[{"domain": "example.com"}],
        )

    def test_rejects_internet_target(self) -> None:
        model = TrafficRoute(name="Catch all", matching_target="INTERNET", network_id="net-1")

        with pytest.raises(ValueError, match="blocked"):
            to_controller_create(model)

    def test_excludes_id(self) -> None:
        model = TrafficRoute(
            id="should-not-appear",
            name="Test",
            matching_target="DOMAIN",
            network_id="net-1",
            domains=[{"domain": "example.com"}],
        )
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
        model = TrafficRoute(
            name="Minimal",
            matching_target="DOMAIN",
            network_id="net-1",
            domains=[{"domain": "example.com"}],
        )
        payload = to_controller_create(model)
        assert payload["next_hop"] == ""
        assert payload["kill_switch_enabled"] is False

    def test_preserves_supplied_next_hop(self) -> None:
        model = TrafficRoute(
            name="Next-hop route",
            matching_target="DOMAIN",
            network_id="net-1",
            domains=[{"domain": "example.com"}],
            next_hop="10.0.0.1",
        )

        assert to_controller_create(model)["next_hop"] == "10.0.0.1"


class TestBuildTrafficRouteCreatePayload:
    def test_normalizes_domain_route_and_controller_defaults(self) -> None:
        payload = build_traffic_route_create_payload(
            description="Example domain route",
            matching_target="domain",
            network_id="network-1",
            domains=[{"domain": "example.com"}],
        )

        assert payload == {
            "description": "Example domain route",
            "matching_target": "DOMAIN",
            "network_id": "network-1",
            "domains": [{"domain": "example.com", "ports": [], "port_ranges": []}],
            "target_devices": [{"type": "ALL_CLIENTS"}],
            "kill_switch_enabled": False,
            "enabled": True,
            "ip_addresses": [],
            "ip_ranges": [],
            "regions": [],
            "next_hop": "",
        }

    def test_preserves_canonical_ip_route_selectors(self) -> None:
        ip_addresses = [{"ip_or_subnet": "203.0.113.10", "ip_version": "IPV4", "ports": [443], "port_ranges": []}]
        ip_ranges = [{"ip_start": "203.0.113.20", "ip_stop": "203.0.113.30", "ip_version": "IPV4"}]

        payload = build_traffic_route_create_payload(
            description="IP route",
            matching_target="IP",
            network_id="network-1",
            ip_addresses=ip_addresses,
            ip_ranges=ip_ranges,
        )

        assert payload["ip_addresses"] == ip_addresses
        assert payload["ip_ranges"] == ip_ranges

    @pytest.mark.parametrize(
        ("matching_target", "selectors"),
        [
            ("DOMAIN", {"domains": [{"domain": "example.com", "unexpected": True}]}),
            ("DOMAIN", {"domains": [{"domain": "example.com", "ports": [True]}]}),
            ("IP", {"ip_addresses": {}}),
            (
                "DOMAIN",
                {"domains": [{"domain": "example.com", "port_ranges": [{"port_start": 2, "port_stop": 1}]}]},
            ),
            ("IP", {"ip_addresses": [{"ip_or_subnet": "not-an-ip", "ip_version": "IPV4"}]}),
            ("IP", {"ip_addresses": [{"ip_or_subnet": "2001:db8::1", "ip_version": "IPV4"}]}),
            (
                "IP",
                {"ip_ranges": [{"ip_start": "203.0.113.9", "ip_stop": "203.0.113.1", "ip_version": "IPV4"}]},
            ),
            ("REGION", {"regions": ["US"], "domains": [{"domain": "example.com"}]}),
            (
                "DOMAIN",
                {
                    "domains": [{"domain": "example.com"}],
                    "ip_addresses": [{"ip_or_subnet": "203.0.113.1", "ip_version": "IPV4"}],
                },
            ),
            ("DOMAIN", {"domains": [{"domain": "example.com"}], "target_devices": []}),
            (
                "DOMAIN",
                {
                    "domains": [{"domain": "example.com"}],
                    "target_devices": [{"type": "ALL_CLIENTS", "client_mac": "aa:bb:cc:dd:ee:ff"}],
                },
            ),
            (
                "DOMAIN",
                {
                    "domains": [{"domain": "example.com"}],
                    "target_devices": [{"type": "CLIENT", "client_mac": "not-a-mac"}],
                },
            ),
            (
                "DOMAIN",
                {"domains": [{"domain": "example.com"}], "target_devices": [{"type": "NETWORK", "network_id": " "}]},
            ),
        ],
    )
    def test_rejects_unsafe_nested_write_values(self, matching_target: str, selectors: dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            build_traffic_route_create_payload(
                description="Validated route",
                matching_target=matching_target,
                network_id="network-1",
                **selectors,
            )

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("description", " "),
            ("description", None),
            ("description", 123),
            ("network_id", " "),
            ("network_id", None),
            ("network_id", 123),
        ],
    )
    def test_rejects_invalid_required_strings(self, field: str, value: Any) -> None:
        kwargs: dict[str, Any] = {
            "description": "Validated route",
            "matching_target": "DOMAIN",
            "network_id": "network-1",
            "domains": [{"domain": "example.com"}],
        }
        kwargs[field] = value

        with pytest.raises(ValueError, match=rf"{field} is required"):
            build_traffic_route_create_payload(**kwargs)

    @pytest.mark.parametrize("matching_target", [None, 1, True])
    def test_rejects_non_string_matching_target(self, matching_target: Any) -> None:
        with pytest.raises(ValueError, match="matching_target must be a string"):
            build_traffic_route_create_payload(
                description="Validated route",
                matching_target=matching_target,
                network_id="network-1",
                domains=[{"domain": "example.com"}],
            )

    @pytest.mark.parametrize(("field", "value"), [("enabled", "false"), ("kill_switch_enabled", 1)])
    def test_rejects_non_boolean_flags(self, field: str, value: Any) -> None:
        kwargs: dict[str, Any] = {
            "description": "Validated route",
            "matching_target": "DOMAIN",
            "network_id": "network-1",
            "domains": [{"domain": "example.com"}],
        }
        kwargs[field] = value

        with pytest.raises(ValueError, match=rf"{field} must be a boolean"):
            build_traffic_route_create_payload(**kwargs)

    def test_rejects_catch_all_internet_route(self) -> None:
        with pytest.raises(ValueError, match="blocked"):
            build_traffic_route_create_payload(
                description="Catch all",
                matching_target="INTERNET",
                network_id="network-1",
            )

    @pytest.mark.parametrize(
        ("client_mac", "expected"),
        [
            ("aa:bb:cc:dd:ee:ff", "aa:bb:cc:dd:ee:ff"),
            ("AA-BB-CC-DD-EE-FF", "aa:bb:cc:dd:ee:ff"),
            ("AABBCCDDEEFF", "aa:bb:cc:dd:ee:ff"),
        ],
    )
    def test_normalizes_compatible_client_mac_forms(self, client_mac: str, expected: str) -> None:
        payload = build_traffic_route_create_payload(
            description="Validated route",
            matching_target="DOMAIN",
            network_id="network-1",
            domains=[{"domain": "example.com"}],
            target_devices=[{"type": "CLIENT", "client_mac": client_mac}],
        )

        assert payload["target_devices"] == [{"type": "CLIENT", "client_mac": expected}]

    @pytest.mark.parametrize(
        ("matching_target", "selectors", "message"),
        [
            ("DOMAIN", {"domains": [{"domain": " "}]}, "Each domains entry must contain a non-empty domain."),
            (
                "IP",
                {"ip_addresses": ["not-an-ip-object"]},
                "Each ip_addresses entry must be an object.",
            ),
            (
                "IP",
                {"ip_ranges": [{"ip_start": "", "ip_stop": "203.0.113.30", "ip_version": "IPV4"}]},
                "Each ip_ranges entry must contain non-empty ip_start and ip_stop.",
            ),
            ("REGION", {"regions": [""]}, "Each regions entry must be a non-empty string."),
            (
                "DOMAIN",
                {"domains": [{"domain": "example.com"}], "target_devices": [{"type": 1}]},
                "target_devices type must be ALL_CLIENTS, CLIENT, or NETWORK.",
            ),
        ],
    )
    def test_rejects_malformed_selector_entries(
        self, matching_target: str, selectors: dict[str, Any], message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            build_traffic_route_create_payload(
                description="Validated route",
                matching_target=matching_target,
                network_id="network-1",
                **selectors,
            )


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


class TestStrictWriteValidation:
    def test_permissive_read_retains_malformed_legacy_region_values(self) -> None:
        legacy_regions = [{"legacy": "value"}]

        route = TrafficRoute(regions=legacy_regions)

        assert route.regions == legacy_regions

    def test_permissive_read_retains_malformed_legacy_selectors(self) -> None:
        malformed = {"domains": [{"domain": 1, "unexpected": object()}], "target_devices": "legacy"}

        route = from_controller(malformed)

        assert route.domains == malformed["domains"]
        assert route.target_devices == "legacy"

    def test_update_rejects_unknown_and_immutable_fields(self) -> None:
        for fields in ({"unknown": True}, {"network_id": "net-2"}, {"matching_target": "IP"}):
            with pytest.raises(ValueError):
                validate_update(fields, matching_target="DOMAIN")

    def test_update_rejects_incompatible_selector_family(self) -> None:
        with pytest.raises(ValueError, match="DOMAIN"):
            validate_update(
                {"ip_addresses": [{"ip_or_subnet": "203.0.113.1", "ip_version": "IPV4"}]},
                matching_target="DOMAIN",
            )

    def test_update_validates_only_submitted_fields(self) -> None:
        assert validate_update({"enabled": False}, matching_target="DOMAIN") == {"enabled": False}

    def test_update_rejects_overlong_name(self) -> None:
        with pytest.raises(ValueError, match="at most 128 characters"):
            validate_update({"name": "x" * 129}, matching_target="DOMAIN")

    def test_update_allows_disabling_or_renaming_an_internet_route(self) -> None:
        assert validate_update({"enabled": False}, matching_target="INTERNET") == {"enabled": False}
        assert validate_update({"name": "Legacy route", "enabled": False}, matching_target="INTERNET") == {
            "description": "Legacy route",
            "enabled": False,
        }

    def test_update_allows_scalar_partial_updates_for_unrecognized_legacy_target(self) -> None:
        assert validate_update({"enabled": True}, matching_target="legacy-malformed") == {"enabled": True}

    @pytest.mark.parametrize(
        "fields",
        [
            {"enabled": True},
            {"next_hop": "10.0.0.1"},
            {"kill_switch_enabled": True},
        ],
    )
    def test_update_rejects_routing_mutations_for_internet_route(self, fields: dict[str, Any]) -> None:
        with pytest.raises(ValueError, match="only be renamed or disabled"):
            validate_update(fields, matching_target="INTERNET")

    @pytest.mark.parametrize("matching_target", ["INTERNET", "legacy-malformed"])
    def test_update_rejects_selector_replacements_for_unsafe_target(self, matching_target: str) -> None:
        with pytest.raises(ValueError, match="not safe"):
            validate_update({"domains": [{"domain": "example.com"}]}, matching_target=matching_target)
