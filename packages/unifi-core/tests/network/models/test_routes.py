"""Unit tests for the Network Route + ActiveRoute read-only models."""

from __future__ import annotations

from unifi_core.network.models.route import (
    ACTIVEROUTE_MUTABLE_FIELDS,
    ACTIVEROUTE_READ_ONLY_FIELDS,
    MUTABLE_FIELDS,
    ROUTE_MUTABLE_FIELDS,
    ROUTE_READ_ONLY_FIELDS,
    ActiveRoute,
    Route,
    active_route_from_controller,
    route_from_controller,
)

# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------


class TestRouteFieldSets:
    def test_route_has_no_mutable_fields(self) -> None:
        assert ROUTE_MUTABLE_FIELDS == frozenset()

    def test_route_read_only_covers_all_fields(self) -> None:
        all_fields = frozenset(Route.model_fields.keys())
        assert ROUTE_READ_ONLY_FIELDS == all_fields

    def test_mutable_and_read_only_disjoint(self) -> None:
        overlap = ROUTE_MUTABLE_FIELDS & ROUTE_READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_module_alias_matches_route_mutable(self) -> None:
        assert MUTABLE_FIELDS == ROUTE_MUTABLE_FIELDS


class TestActiveRouteFieldSets:
    def test_activeroute_has_no_mutable_fields(self) -> None:
        assert ACTIVEROUTE_MUTABLE_FIELDS == frozenset()

    def test_activeroute_read_only_covers_all_fields(self) -> None:
        all_fields = frozenset(ActiveRoute.model_fields.keys())
        assert ACTIVEROUTE_READ_ONLY_FIELDS == all_fields

    def test_mutable_and_read_only_disjoint(self) -> None:
        overlap = ACTIVEROUTE_MUTABLE_FIELDS & ACTIVEROUTE_READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"


# ---------------------------------------------------------------------------
# Route factory
# ---------------------------------------------------------------------------


class TestRouteFromController:
    def test_full_static_route_v1_fields(self) -> None:
        raw = {
            "_id": "route-1",
            "name": "Office VPN",
            "static-route_network": "10.0.0.0/24",
            "static-route_nexthop": "192.168.1.1",
            "static-route_distance": 5,
            "enabled": True,
        }
        route = route_from_controller(raw)
        assert route.id == "route-1"
        assert route.name == "Office VPN"
        assert route.target_subnet == "10.0.0.0/24"
        assert route.gateway == "192.168.1.1"
        assert route.distance == 5
        assert route.enabled is True

    def test_id_coalesces_plain_id(self) -> None:
        raw = {"id": "route-2", "name": "Route 2"}
        route = route_from_controller(raw)
        assert route.id == "route-2"

    def test_underscore_id_takes_priority(self) -> None:
        raw = {"_id": "route-3", "id": "ignored"}
        route = route_from_controller(raw)
        assert route.id == "route-3"

    def test_target_subnet_fallback_keys(self) -> None:
        raw = {"target_subnet": "172.16.0.0/16"}
        route = route_from_controller(raw)
        assert route.target_subnet == "172.16.0.0/16"

    def test_gateway_fallback_keys(self) -> None:
        raw = {"nexthop": "10.0.0.1"}
        route = route_from_controller(raw)
        assert route.gateway == "10.0.0.1"

    def test_enabled_defaults_true_when_absent(self) -> None:
        route = route_from_controller({})
        assert route.enabled is True

    def test_empty_dict_returns_defaults(self) -> None:
        route = route_from_controller({})
        assert route.id is None
        assert route.name is None
        assert route.target_subnet is None
        assert route.gateway is None
        assert route.distance is None
        assert route.enabled is True

    def test_all_fields_are_read_only(self) -> None:
        # Every field should be tagged mutable: False
        for name, field in Route.model_fields.items():
            extra = field.json_schema_extra or {}
            assert extra.get("mutable") is False, f"Field {name!r} is not tagged mutable=False"


# ---------------------------------------------------------------------------
# ActiveRoute factory
# ---------------------------------------------------------------------------


class TestActiveRouteFromController:
    def test_full_stat_routing_row(self) -> None:
        raw = {
            "pfx": "0.0.0.0/0",
            "nh": [{"via": "10.0.0.1", "intf": "eth0"}],
            "metric": 10,
        }
        ar = active_route_from_controller(raw)
        assert ar.target_subnet == "0.0.0.0/0"
        assert ar.gateway == "10.0.0.1"
        assert ar.interface == "eth0"
        assert ar.distance == 10

    def test_empty_nh_list_falls_back_to_flat_fields(self) -> None:
        raw = {
            "pfx": "192.168.1.0/24",
            "nh": [],
            "gateway": "10.1.0.1",
            "interface": "eth1",
            "metric": 1,
        }
        ar = active_route_from_controller(raw)
        assert ar.target_subnet == "192.168.1.0/24"
        assert ar.gateway == "10.1.0.1"
        assert ar.interface == "eth1"
        assert ar.distance == 1

    def test_target_subnet_fallbacks(self) -> None:
        ar = active_route_from_controller({"target_subnet": "10.0.0.0/8"})
        assert ar.target_subnet == "10.0.0.0/8"

        ar2 = active_route_from_controller({"network": "172.16.0.0/12"})
        assert ar2.target_subnet == "172.16.0.0/12"

    def test_nh_via_takes_priority_over_flat_gateway(self) -> None:
        raw = {
            "pfx": "10.0.0.0/8",
            "nh": [{"via": "nh-gateway", "intf": "nh-intf"}],
            "gateway": "flat-gateway",
            "interface": "flat-intf",
        }
        ar = active_route_from_controller(raw)
        assert ar.gateway == "nh-gateway"
        assert ar.interface == "nh-intf"

    def test_distance_fallback_to_distance_key(self) -> None:
        ar = active_route_from_controller({"distance": 20})
        assert ar.distance == 20

    def test_empty_dict_returns_all_none(self) -> None:
        ar = active_route_from_controller({})
        assert ar.target_subnet is None
        assert ar.gateway is None
        assert ar.interface is None
        assert ar.distance is None

    def test_all_fields_are_read_only(self) -> None:
        for name, field in ActiveRoute.model_fields.items():
            extra = field.json_schema_extra or {}
            assert extra.get("mutable") is False, f"Field {name!r} is not tagged mutable=False"
