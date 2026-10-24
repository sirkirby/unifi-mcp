"""Unit tests for the Network Route + ActiveRoute read-only models."""

from __future__ import annotations

import pytest
from unifi_core.network.models.route import (
    ACTIVEROUTE_MUTABLE_FIELDS,
    MUTABLE_FIELDS,
    ROUTE_MUTABLE_FIELDS,
    ActiveRoute,
    Route,
    active_route_from_controller,
    route_from_controller,
    validate_static_route_fields,
)

from .model_assertions import assert_fields

# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------


class TestRouteFieldSets:
    def test_route_has_no_mutable_fields(self) -> None:
        assert ROUTE_MUTABLE_FIELDS == frozenset()

    def test_module_alias_matches_route_mutable(self) -> None:
        assert MUTABLE_FIELDS == ROUTE_MUTABLE_FIELDS


class TestActiveRouteFieldSets:
    def test_activeroute_has_no_mutable_fields(self) -> None:
        assert ACTIVEROUTE_MUTABLE_FIELDS == frozenset()


# ---------------------------------------------------------------------------
# Route factory
# ---------------------------------------------------------------------------


class TestRouteFromController:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (
                {
                    "_id": "route-1",
                    "name": "Office VPN",
                    "static-route_network": "10.0.0.0/24",
                    "static-route_nexthop": "192.168.1.1",
                    "static-route_distance": 5,
                    "enabled": True,
                },
                {
                    "id": "route-1",
                    "name": "Office VPN",
                    "target_subnet": "10.0.0.0/24",
                    "gateway": "192.168.1.1",
                    "distance": 5,
                    "enabled": True,
                },
            ),
            ({"id": "route-2", "name": "Route 2"}, {"id": "route-2"}),
            ({"_id": "route-3", "id": "ignored"}, {"id": "route-3"}),
            ({"target_subnet": "172.16.0.0/16"}, {"target_subnet": "172.16.0.0/16"}),
            ({"nexthop": "10.0.0.1"}, {"gateway": "10.0.0.1"}),
            ({}, {"enabled": True}),
            ({}, {"id": None, "name": None, "target_subnet": None, "gateway": None, "distance": None, "enabled": True}),
        ],
        ids=[
            "full_static_route_v1_fields",
            "id_coalesces_plain_id",
            "underscore_id_takes_priority",
            "target_subnet_fallback_keys",
            "gateway_fallback_keys",
            "enabled_defaults_true_when_absent",
            "empty_dict_returns_defaults",
        ],
    )
    def test_route_from_controller_fields(self, raw, expected) -> None:
        result = route_from_controller(raw)
        assert_fields(result, expected)

    def test_all_fields_are_read_only(self) -> None:
        # Every field should be tagged mutable: False
        for name, field in Route.model_fields.items():
            extra = field.json_schema_extra or {}
            assert extra.get("mutable") is False, f"Field {name!r} is not tagged mutable=False"


class TestStaticRouteValidation:
    def test_create_normalizes_name_and_defaults(self) -> None:
        assert validate_static_route_fields(
            {"name": " Office ", "network": "10.0.0.0/24", "nexthop": "192.168.1.1"},
            require_complete=True,
        ) == {
            "name": "Office",
            "network": "10.0.0.0/24",
            "nexthop": "192.168.1.1",
            "distance": 1,
            "enabled": True,
        }

    @pytest.mark.parametrize(
        ("fields", "message"),
        [
            ({"name": " ", "network": "10.0.0.0/24", "nexthop": "192.168.1.1"}, "Name is required"),
            ({"name": "x", "network": "not-cidr", "nexthop": "192.168.1.1"}, "Invalid network"),
            ({"name": "x", "network": "10.0.0.0/24", "nexthop": "not-ip"}, "Invalid nexthop"),
            ({"name": "x", "network": "10.0.0.0/24", "nexthop": "192.168.1.1", "distance": 0}, "Distance"),
        ],
    )
    def test_create_rejects_invalid_fields(self, fields: dict, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            validate_static_route_fields(fields, require_complete=True)

    def test_update_requires_a_field(self) -> None:
        with pytest.raises(ValueError, match="At least one field"):
            validate_static_route_fields({}, require_complete=False)


# ---------------------------------------------------------------------------
# ActiveRoute factory
# ---------------------------------------------------------------------------


class TestActiveRouteFromController:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (
                {"pfx": "0.0.0.0/0", "nh": [{"via": "10.0.0.1", "intf": "eth0"}], "metric": 10},
                {"target_subnet": "0.0.0.0/0", "gateway": "10.0.0.1", "interface": "eth0", "distance": 10},
            ),
            (
                {"pfx": "192.168.1.0/24", "nh": [], "gateway": "10.1.0.1", "interface": "eth1", "metric": 1},
                {"target_subnet": "192.168.1.0/24", "gateway": "10.1.0.1", "interface": "eth1", "distance": 1},
            ),
            (
                {
                    "pfx": "10.0.0.0/8",
                    "nh": [{"via": "nh-gateway", "intf": "nh-intf"}],
                    "gateway": "flat-gateway",
                    "interface": "flat-intf",
                },
                {"gateway": "nh-gateway", "interface": "nh-intf"},
            ),
            ({"distance": 20}, {"distance": 20}),
            ({}, {"target_subnet": None, "gateway": None, "interface": None, "distance": None}),
        ],
        ids=[
            "full_stat_routing_row",
            "empty_nh_list_falls_back_to_flat_fields",
            "nh_via_takes_priority_over_flat_gateway",
            "distance_fallback_to_distance_key",
            "empty_dict_returns_all_none",
        ],
    )
    def test_active_route_from_controller_fields(self, raw, expected) -> None:
        result = active_route_from_controller(raw)
        assert_fields(result, expected)

    def test_target_subnet_fallbacks(self) -> None:
        ar = active_route_from_controller({"target_subnet": "10.0.0.0/8"})
        assert ar.target_subnet == "10.0.0.0/8"

        ar2 = active_route_from_controller({"network": "172.16.0.0/12"})
        assert ar2.target_subnet == "172.16.0.0/12"

    def test_all_fields_are_read_only(self) -> None:
        for name, field in ActiveRoute.model_fields.items():
            extra = field.json_schema_extra or {}
            assert extra.get("mutable") is False, f"Field {name!r} is not tagged mutable=False"
