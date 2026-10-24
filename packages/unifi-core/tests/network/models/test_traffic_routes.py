"""Unit tests for the Network TrafficRoute CRUD domain model."""

from __future__ import annotations

import pytest
from unifi_core.network.models.traffic_routes import (
    TrafficRoute,
    from_controller,
    to_controller_create,
    to_controller_update,
    validate_create_payload,
)

from .model_assertions import assert_fields


class TestFromController:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (
                {
                    "_id": "rt-1",
                    "description": "VPN Route",
                    "matching_target": "DOMAIN",
                    "network_id": "net-1",
                    "enabled": True,
                    "kill_switch_enabled": False,
                    "next_hop": "10.0.0.1",
                    "domains": [{"domain": "example.com", "ports": []}],
                    "target_devices": [{"type": "NETWORK", "network_id": "net-1"}],
                },
                {
                    "id": "rt-1",
                    "name": "VPN Route",
                    "matching_target": "DOMAIN",
                    "network_id": "net-1",
                    "enabled": True,
                    "kill_switch_enabled": False,
                    "next_hop": "10.0.0.1",
                    "domains": [{"domain": "example.com", "ports": []}],
                },
            ),
            ({"_id": "rt-2", "name": "Fallback"}, {"name": "Fallback"}),
            ({"_id": "rt-3", "description": "Primary", "name": "Secondary"}, {"name": "Primary"}),
            ({"_id": "abc"}, {"id": "abc"}),
            ({}, {"id": None, "name": None, "enabled": None}),
        ],
        ids=[
            "full_route",
            "name_falls_back_to_name_field",
            "description_takes_priority_over_name",
            "id_coalesces_underscore_id",
            "handles_empty_dict",
        ],
    )
    def test_from_controller_fields(self, raw, expected) -> None:
        result = from_controller(raw)
        assert_fields(result, expected)


class TestToControllerCreate:
    def test_maps_name_to_description(self) -> None:
        model = TrafficRoute(name="My Route", matching_target="INTERNET", network_id="net-1")
        payload = to_controller_create(model)
        assert payload["description"] == "My Route"
        assert "name" not in payload

    def test_excludes_id(self) -> None:
        model = TrafficRoute(id="should-not-appear", name="Test", matching_target="INTERNET", network_id="wan-1")
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

    def test_accepts_empty_inactive_selectors_without_inventing_client_scope(self) -> None:
        route = TrafficRoute(
            name="Domain route",
            matching_target="DOMAIN",
            network_id="vpn-1",
            domains=[{"domain": "example.com"}],
            ip_addresses=[],
            ip_ranges=[],
            regions=[],
        )
        payload = validate_create_payload(to_controller_create(route))
        assert payload["domains"] == [{"domain": "example.com", "ports": [], "port_ranges": []}]
        assert "target_devices" not in payload
        assert payload["ip_addresses"] == []

    def test_rejects_incompatible_nonempty_selector(self) -> None:
        route = TrafficRoute(
            name="Domain route",
            matching_target="DOMAIN",
            network_id="vpn-1",
            domains=[{"domain": "example.com"}],
            regions=["US"],
        )
        with pytest.raises(ValueError, match="do not accept selector"):
            validate_create_payload(to_controller_create(route))


CONTROLLER_IP_ADDRESS_V4 = {
    "ip_or_subnet": "203.0.113.10",
    "ip_version": "v4",
    "ports": [443],
    "port_ranges": [],
}
CONTROLLER_IP_RANGE_V6 = {
    "ip_start": "2001:db8::1",
    "ip_stop": "2001:db8::9",
    "ip_version": "v6",
}


class TestControllerIpSelectors:
    @pytest.mark.parametrize(
        ("field", "item"),
        [("ip_addresses", CONTROLLER_IP_ADDRESS_V4), ("ip_ranges", CONTROLLER_IP_RANGE_V6)],
    )
    def test_accepts_controller_shaped_ip_selector(self, field: str, item: dict) -> None:
        payload = validate_create_payload(
            {
                "description": "IP route",
                "matching_target": "IP",
                "network_id": "vpn-1",
                field: [item],
            }
        )
        assert payload[field][0]["ip_version"] == item["ip_version"]
        assert "ip_version" not in payload

    @pytest.mark.parametrize(
        ("field", "item", "alias", "expected"),
        [
            ("ip_addresses", CONTROLLER_IP_ADDRESS_V4, "IPV4", "v4"),
            ("ip_ranges", CONTROLLER_IP_RANGE_V6, "IPV6", "v6"),
        ],
    )
    def test_normalizes_existing_public_ip_version_spelling(
        self, field: str, item: dict, alias: str, expected: str
    ) -> None:
        payload = validate_create_payload(
            {
                "description": "IP route",
                "matching_target": "IP",
                "network_id": "vpn-1",
                field: [{**item, "ip_version": alias}],
            }
        )
        assert payload[field][0]["ip_version"] == expected

    @pytest.mark.parametrize(
        "field,item", [("ip_addresses", CONTROLLER_IP_ADDRESS_V4), ("ip_ranges", CONTROLLER_IP_RANGE_V6)]
    )
    def test_rejects_ip_version_family_mismatch(self, field: str, item: dict) -> None:
        wrong = "v6" if item["ip_version"] == "v4" else "v4"
        with pytest.raises(ValueError, match="address family"):
            validate_create_payload(
                {
                    "description": "IP route",
                    "matching_target": "IP",
                    "network_id": "vpn-1",
                    field: [{**item, "ip_version": wrong}],
                }
            )


class TestToControllerUpdate:
    def test_maps_name_to_description(self) -> None:
        result = to_controller_update({"name": "Updated Route"})
        assert "description" in result
        assert result["description"] == "Updated Route"
        assert "name" not in result

    def test_toggle_payload(self) -> None:
        result = to_controller_update({"enabled": False})
        assert result == {"enabled": False}

    def test_accepts_list_fields(self) -> None:
        domains = [{"domain": "example.com", "ports": []}]
        result = to_controller_update({"domains": domains})
        assert result["domains"] == domains
