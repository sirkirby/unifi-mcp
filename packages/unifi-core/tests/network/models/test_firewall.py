"""Unit tests for the Network FirewallRule, FirewallGroup, FirewallZone domain models."""

from __future__ import annotations

from unifi_core.network.models.firewall import (
    FIREWALLGROUP_MUTABLE_FIELDS,
    FIREWALLGROUP_READ_ONLY_FIELDS,
    FIREWALLZONE_MUTABLE_FIELDS,
    FIREWALLZONE_READ_ONLY_FIELDS,
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    FirewallGroup,
    FirewallRule,
    FirewallZone,
    firewall_group_from_controller,
    firewall_zone_from_controller,
    from_controller,
    to_controller_update,
    to_group_create,
)


class TestFirewallRuleFieldSets:
    def test_mutable_fields_contains_expected(self) -> None:
        expected = {
            "name",
            "action",
            "enabled",
            "index",
            "protocol",
            "ip_version",
            "connection_state_type",
            "connection_states",
            "create_allow_respond",
            "match_ip_sec",
            "match_opposite_protocol",
            "icmp_typename",
            "icmp_v6_typename",
            "schedule",
            "source",
            "destination",
            "logging",
        }
        for field in expected:
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mutable_fields_excludes_read_only(self) -> None:
        for field in ("id", "predefined"):
            assert field not in MUTABLE_FIELDS, f"{field!r} should NOT be in MUTABLE_FIELDS"

    def test_read_only_contains_id_and_predefined(self) -> None:
        assert "id" in READ_ONLY_FIELDS
        assert "predefined" in READ_ONLY_FIELDS

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = MUTABLE_FIELDS & READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_mutable_and_read_only_cover_all_model_fields(self) -> None:
        all_fields = frozenset(FirewallRule.model_fields.keys())
        assert MUTABLE_FIELDS | READ_ONLY_FIELDS == all_fields


class TestFirewallRuleFromController:
    def test_full_dict(self) -> None:
        raw = {
            "_id": "fw-1",
            "name": "Block Outbound",
            "action": "BLOCK",
            "enabled": True,
            "predefined": False,
            "index": 100,
            "protocol": "tcp",
            "source": {"zone_id": "z1", "matching_target": "ANY"},
            "destination": {"zone_id": "z2", "matching_target": "ANY"},
        }
        r = from_controller(raw)
        assert r.id == "fw-1"
        assert r.name == "Block Outbound"
        assert r.action == "BLOCK"
        assert r.enabled is True
        assert r.predefined is False
        assert r.index == 100
        assert r.protocol == "tcp"
        assert r.source == {"zone_id": "z1", "matching_target": "ANY"}

    def test_id_coalesces_underscore_id(self) -> None:
        raw = {"_id": "abc", "name": "Test"}
        r = from_controller(raw)
        assert r.id == "abc"

    def test_index_coalesces_rule_index(self) -> None:
        raw = {"_id": "fw-2", "rule_index": 200}
        r = from_controller(raw)
        assert r.index == 200

    def test_connection_states_defaults_to_empty(self) -> None:
        raw = {"_id": "fw-3"}
        r = from_controller(raw)
        assert r.connection_states == []

    def test_handles_obj_with_raw_attr(self) -> None:
        class MockPolicy:
            raw = {"_id": "fw-4", "name": "Mock", "action": "ALLOW"}

        r = from_controller(MockPolicy())
        assert r.id == "fw-4"
        assert r.name == "Mock"

    def test_handles_empty_dict(self) -> None:
        r = from_controller({})
        assert r.id is None
        assert r.name is None
        assert r.connection_states == []


class TestToControllerUpdate:
    def test_filters_out_read_only_id(self) -> None:
        result = to_controller_update({"id": "ignore-me", "name": "New Name"})
        assert "id" not in result
        assert result["name"] == "New Name"

    def test_filters_out_predefined(self) -> None:
        result = to_controller_update({"predefined": True, "name": "Test"})
        assert "predefined" not in result

    def test_drops_none_values(self) -> None:
        result = to_controller_update({"name": None, "action": "ALLOW"})
        assert "name" not in result
        assert result["action"] == "ALLOW"

    def test_passes_all_mutable_fields(self) -> None:
        fields = {
            "name": "Allow All",
            "action": "ALLOW",
            "enabled": True,
            "index": 50,
            "protocol": "all",
            "source": {"zone_id": "z1", "matching_target": "ANY"},
            "destination": {"zone_id": "z2", "matching_target": "ANY"},
        }
        result = to_controller_update(fields)
        assert result == fields

    def test_empty_list_preserved_for_connection_states(self) -> None:
        result = to_controller_update({"connection_states": []})
        assert result["connection_states"] == []

    def test_drops_unrecognised_keys(self) -> None:
        result = to_controller_update({"ruleset": "WAN_IN", "name": "Valid"})
        assert "ruleset" not in result
        assert result["name"] == "Valid"

    def test_returns_empty_dict_when_no_mutable_fields(self) -> None:
        result = to_controller_update({"id": "read-only"})
        assert result == {}


class TestFirewallGroupFieldSets:
    def test_mutable_fields_contains_expected(self) -> None:
        for field in ("name", "group_type", "members"):
            assert field in FIREWALLGROUP_MUTABLE_FIELDS

    def test_read_only_contains_id(self) -> None:
        assert "id" in FIREWALLGROUP_READ_ONLY_FIELDS

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = FIREWALLGROUP_MUTABLE_FIELDS & FIREWALLGROUP_READ_ONLY_FIELDS
        assert not overlap

    def test_cover_all_model_fields(self) -> None:
        all_fields = frozenset(FirewallGroup.model_fields.keys())
        assert FIREWALLGROUP_MUTABLE_FIELDS | FIREWALLGROUP_READ_ONLY_FIELDS == all_fields


class TestFirewallGroupFromController:
    def test_full_dict(self) -> None:
        raw = {
            "_id": "fg-1",
            "name": "Office IPs",
            "group_type": "address-group",
            "group_members": ["10.0.0.1", "10.0.0.0/24"],
        }
        g = firewall_group_from_controller(raw)
        assert g.id == "fg-1"
        assert g.name == "Office IPs"
        assert g.group_type == "address-group"
        assert g.members == ["10.0.0.1", "10.0.0.0/24"]

    def test_members_coalesces_group_members(self) -> None:
        raw = {"_id": "fg-2", "group_members": ["80", "443"]}
        g = firewall_group_from_controller(raw)
        assert g.members == ["80", "443"]

    def test_members_coalesces_plain_members(self) -> None:
        raw = {"_id": "fg-3", "members": ["80"]}
        g = firewall_group_from_controller(raw)
        assert g.members == ["80"]

    def test_handles_empty_dict(self) -> None:
        g = firewall_group_from_controller({})
        assert g.id is None
        assert g.members == []


class TestToGroupCreate:
    def test_full_model(self) -> None:
        model = FirewallGroup(name="Test", group_type="address-group", members=["10.0.0.1"])
        payload = to_group_create(model)
        assert payload["name"] == "Test"
        assert payload["group_type"] == "address-group"
        assert payload["group_members"] == ["10.0.0.1"]

    def test_maps_members_to_group_members(self) -> None:
        model = FirewallGroup(members=["80", "443"])
        payload = to_group_create(model)
        assert payload["group_members"] == ["80", "443"]
        assert "members" not in payload


class TestFirewallZoneFieldSets:
    def test_all_fields_read_only(self) -> None:
        assert not FIREWALLZONE_MUTABLE_FIELDS

    def test_read_only_contains_all_fields(self) -> None:
        all_fields = frozenset(FirewallZone.model_fields.keys())
        assert FIREWALLZONE_READ_ONLY_FIELDS == all_fields


class TestFirewallZoneFromController:
    def test_full_dict(self) -> None:
        raw = {
            "_id": "zone-1",
            "name": "LAN",
            "networks": ["net-1", "net-2"],
            "default_policy": "ALLOW",
        }
        z = firewall_zone_from_controller(raw)
        assert z.id == "zone-1"
        assert z.name == "LAN"
        assert z.networks == ["net-1", "net-2"]
        assert z.default_policy == "ALLOW"

    def test_networks_coalesces_network_ids(self) -> None:
        raw = {"_id": "zone-2", "network_ids": ["net-x"]}
        z = firewall_zone_from_controller(raw)
        assert z.networks == ["net-x"]

    def test_default_policy_coalesces_default_action(self) -> None:
        raw = {"_id": "zone-3", "default_action": "BLOCK"}
        z = firewall_zone_from_controller(raw)
        assert z.default_policy == "BLOCK"

    def test_handles_empty_dict(self) -> None:
        z = firewall_zone_from_controller({})
        assert z.id is None
        assert z.networks == []
