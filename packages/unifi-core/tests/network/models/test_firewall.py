"""Unit tests for the Network FirewallRule, FirewallGroup, FirewallZone domain models."""

from __future__ import annotations

import pytest
from unifi_core.network.models.firewall import (
    FIREWALLGROUP_MUTABLE_FIELDS,
    FIREWALLGROUP_READ_ONLY_FIELDS,
    FIREWALLZONE_MUTABLE_FIELDS,
    FIREWALLZONE_READ_ONLY_FIELDS,
    LEGACY_ACTIONS,
    LEGACY_RULESETS,
    LEGACYFIREWALLRULE_MUTABLE_FIELDS,
    LEGACYFIREWALLRULE_READ_ONLY_FIELDS,
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    FirewallGroup,
    FirewallRule,
    FirewallZone,
    LegacyFirewallRule,
    firewall_group_from_controller,
    firewall_zone_from_controller,
    from_controller,
    legacy_firewall_rule_from_controller,
    normalize_policy_enums,
    normalize_policy_update,
    policy_update_targeting_error,
    retire_stale_selectors,
    to_controller_update,
    to_group_create,
    to_zone_create,
    to_zone_update,
    validate_policy_targeting,
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


class TestNormalizePolicyUpdate:
    def test_normalizes_public_enum_values_and_filters_unknown_fields(self) -> None:
        result = normalize_policy_update(
            {
                "action": "allow",
                "ip_version": "ipv4",
                "connection_states": ["established", "related"],
                "unknown": "drop-me",
            }
        )

        assert result == {
            "action": "ALLOW",
            "ip_version": "IPV4",
            "connection_states": ["ESTABLISHED", "RELATED"],
        }

    @pytest.mark.parametrize(
        ("fields", "message"),
        [
            ({"ruleset": "WAN_IN"}, "Legacy V1 firewall fields"),
            ({"action": "accept"}, "Legacy V1 firewall fields"),
            ({"action": "invalid"}, "Invalid action"),
            ({"id": "read-only"}, "effectively empty"),
        ],
    )
    def test_rejects_legacy_invalid_or_empty_updates(self, fields: dict, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            normalize_policy_update(fields)


class TestNormalizePolicyEnumsEndpoints:
    def test_upper_cases_endpoint_enums_on_both_sides(self) -> None:
        result = normalize_policy_enums(
            {
                "source": {"zone_id": "z1", "matching_target": "client", "client_macs": ["aa:bb"]},
                "destination": {
                    "zone_id": "z2",
                    "matching_target": "ip",
                    "matching_target_type": "specific",
                    "ips": ["10.0.0.1"],
                    "port_matching_type": "specific",
                    "port": "53",
                },
            }
        )

        assert result["source"]["matching_target"] == "CLIENT"
        assert result["destination"]["matching_target"] == "IP"
        assert result["destination"]["matching_target_type"] == "SPECIFIC"
        assert result["destination"]["port_matching_type"] == "SPECIFIC"
        assert result["destination"]["port"] == "53"

    def test_strips_and_upper_cases_padded_enum_values(self) -> None:
        result = normalize_policy_enums(
            {"destination": {"port_matching_type": " specific ", "matching_target": "any "}}
        )

        assert result["destination"] == {"port_matching_type": "SPECIFIC", "matching_target": "ANY"}

    def test_leaves_non_string_and_non_dict_endpoints_alone(self) -> None:
        result = normalize_policy_enums(
            {"source": {"zone_id": "z1", "matching_target": None}, "destination": "not-a-dict"}
        )

        assert result["source"] == {"zone_id": "z1", "matching_target": None}
        assert result["destination"] == "not-a-dict"

    def test_normalize_policy_update_inherits_endpoint_enums(self) -> None:
        result = normalize_policy_update({"destination": {"port_matching_type": "object", "port_group_id": "g1"}})

        assert result == {"destination": {"port_matching_type": "OBJECT", "port_group_id": "g1"}}


class TestValidatePolicyTargeting:
    def _policy(self, **destination):
        return {
            "source": {"zone_id": "z1", "matching_target": "ANY"},
            "destination": {"zone_id": "z2", "matching_target": "ANY", **destination},
        }

    def test_existing_ip_and_network_rules_still_apply(self) -> None:
        assert "matching_target_type" in validate_policy_targeting(self._policy(matching_target="IP"))
        assert "network_ids" in validate_policy_targeting(
            self._policy(matching_target="NETWORK", matching_target_type="OBJECT")
        )

    def test_client_target_requires_client_macs(self) -> None:
        assert "client_macs" in validate_policy_targeting(self._policy(matching_target="CLIENT"))
        assert "client_macs" in validate_policy_targeting(self._policy(matching_target="CLIENT", client_macs=[]))
        assert (
            validate_policy_targeting(self._policy(matching_target="CLIENT", client_macs=["aa:bb:cc:dd:ee:ff"])) is None
        )

    def test_specific_port_matching_requires_port(self) -> None:
        error = validate_policy_targeting(self._policy(port_matching_type="SPECIFIC"))
        assert error is not None and "destination.port" in error

    def test_object_port_matching_requires_port_group_id(self) -> None:
        error = validate_policy_targeting(self._policy(port_matching_type="OBJECT"))
        assert error is not None and "port_group_id" in error
        assert validate_policy_targeting(self._policy(port_matching_type="OBJECT", port_group_id="g1")) is None

    @pytest.mark.parametrize(
        "port", ["53", "53,853", "1000-2000", "22,1000-2000,443", "53-53", "1", "65535", "1-65535"]
    )
    def test_accepts_well_formed_port_strings(self, port: str) -> None:
        assert validate_policy_targeting(self._policy(port_matching_type="SPECIFIC", port=port)) is None

    @pytest.mark.parametrize("port", ["", "0", "65536", "70000", "53, 853", "900-800", "abc", "53-", 53])
    def test_rejects_malformed_port_strings(self, port) -> None:
        error = validate_policy_targeting(self._policy(port_matching_type="SPECIFIC", port=port))
        assert error is not None and "port" in error

    def test_unknown_targets_and_port_types_pass_through(self) -> None:
        assert validate_policy_targeting(self._policy(matching_target="APP", app_ids=["x"])) is None
        assert validate_policy_targeting(self._policy(port_matching_type="SOMETHING_NEW")) is None

    def test_any_port_matching_needs_nothing(self) -> None:
        assert validate_policy_targeting(self._policy(port_matching_type="ANY")) is None
        assert validate_policy_targeting({"source": None, "destination": None}) is None

    def test_non_dict_endpoint_is_rejected(self) -> None:
        error = validate_policy_targeting({"source": "ANY", "destination": None})
        assert error is not None and "source" in error and "object" in error

    @pytest.mark.parametrize(
        ("extra", "expected"),
        [
            ({"port": "53"}, "port_matching_type"),
            ({"port_matching_type": "ANY", "port": "53"}, "port_matching_type"),
            ({"port_group_id": "g1"}, "port_matching_type"),
            ({"port_matching_type": "SPECIFIC", "port": "53", "port_group_id": "g1"}, "port_matching_type"),
            ({"client_macs": ["aa:bb:cc:dd:ee:ff"]}, "matching_target"),
        ],
    )
    def test_selector_without_its_activating_enum_is_rejected(self, extra: dict, expected: str) -> None:
        """A selector the controller would ignore must not pass validation silently."""
        error = validate_policy_targeting(self._policy(**extra))
        assert error is not None and expected in error

    @pytest.mark.parametrize("port", ["53\n", " 53"])
    def test_rejects_port_strings_with_stray_whitespace(self, port: str) -> None:
        error = validate_policy_targeting(self._policy(port_matching_type="SPECIFIC", port=port))
        assert error is not None and "\n" not in error

    @pytest.mark.parametrize("macs", ["aa:bb:cc:dd:ee:ff", ["zz"], [" "], [None]])
    def test_client_macs_must_be_a_list_of_valid_macs(self, macs) -> None:
        error = validate_policy_targeting(self._policy(matching_target="CLIENT", client_macs=macs))
        assert error is not None and "client_macs" in error

    def test_client_macs_accepts_mixed_case_and_dashes(self) -> None:
        assert (
            validate_policy_targeting(self._policy(matching_target="CLIENT", client_macs=["AA-BB-CC-DD-EE-FF"])) is None
        )


class TestPolicyUpdateTargetingError:
    _stored = {"zone_id": "z2", "matching_target": "ANY", "port_matching_type": "ANY"}

    def test_partial_update_is_validated_as_merged(self) -> None:
        current = {"destination": dict(self._stored)}
        assert policy_update_targeting_error(current, {"destination": {"port_matching_type": "OBJECT"}}) is not None
        assert (
            policy_update_targeting_error(current, {"destination": {"port_matching_type": "SPECIFIC", "port": "53"}})
            is None
        )

    def test_untouched_side_is_not_revalidated(self) -> None:
        current = {"source": {"zone_id": "x", "matching_target": "IP"}, "destination": dict(self._stored)}
        assert (
            policy_update_targeting_error(current, {"destination": {"port_matching_type": "SPECIFIC", "port": "53"}})
            is None
        )

    def test_preexisting_error_on_the_updated_side_is_not_held_against_the_update(self) -> None:
        current = {"destination": {"zone_id": "z2", "matching_target": "NETWORK", "network_ids": ["n1"]}}
        assert (
            policy_update_targeting_error(current, {"destination": {"port_matching_type": "SPECIFIC", "port": "53"}})
            is None
        )

    def test_new_error_is_reported_even_when_a_different_one_preexists(self) -> None:
        current = {"destination": {"zone_id": "z2", "matching_target": "NETWORK", "network_ids": ["n1"]}}
        error = policy_update_targeting_error(current, {"destination": {"port": "53"}})
        assert error is not None and "port_matching_type" in error

    def test_missing_or_non_dict_stored_side_validates_the_update_alone(self) -> None:
        assert (
            policy_update_targeting_error(
                {"destination": None}, {"destination": {"zone_id": "z", "matching_target": "ANY"}}
            )
            is None
        )
        assert "object" in policy_update_targeting_error({"source": "junk"}, {"source": "ANY"})


class TestRetireStaleSelectors:
    def test_switching_port_matching_to_any_retires_the_stored_port(self) -> None:
        stored = {"zone_id": "z", "matching_target": "ANY", "port_matching_type": "SPECIFIC", "port": "53"}
        assert retire_stale_selectors(stored, {"port_matching_type": "ANY"}) == {
            "port_matching_type": "ANY",
            "port": None,
        }

    def test_switching_between_specific_and_object_retires_the_other_selector(self) -> None:
        specific = {"port_matching_type": "SPECIFIC", "port": "53"}
        as_object = retire_stale_selectors(specific, {"port_matching_type": "OBJECT", "port_group_id": "g1"})
        assert as_object == {"port_matching_type": "OBJECT", "port_group_id": "g1", "port": None}

        obj = {"port_matching_type": "OBJECT", "port_group_id": "g1"}
        as_specific = retire_stale_selectors(obj, {"port_matching_type": "SPECIFIC", "port": "53"})
        assert as_specific == {"port_matching_type": "SPECIFIC", "port": "53", "port_group_id": None}

    def test_switching_client_target_away_retires_client_macs(self) -> None:
        stored = {"matching_target": "CLIENT", "client_macs": ["aa:bb:cc:dd:ee:ff"]}
        assert retire_stale_selectors(stored, {"matching_target": "ANY"}) == {
            "matching_target": "ANY",
            "client_macs": None,
        }

    def test_update_that_does_not_touch_the_activator_is_unchanged(self) -> None:
        stored = {"port_matching_type": "SPECIFIC", "port": "53"}
        assert retire_stale_selectors(stored, {"port": "53,853"}) == {"port": "53,853"}
        assert retire_stale_selectors(stored, {"zone_id": "z2"}) == {"zone_id": "z2"}

    def test_update_that_sets_the_selector_itself_is_unchanged(self) -> None:
        stored = {"port_matching_type": "SPECIFIC", "port": "53"}
        update = {"port_matching_type": "ANY", "port": ""}
        assert retire_stale_selectors(stored, update) == update

    def test_non_dict_inputs_pass_through(self) -> None:
        assert retire_stale_selectors(None, {"port_matching_type": "ANY"}) == {"port_matching_type": "ANY"}
        assert retire_stale_selectors({"port": "53"}, "ANY") == "ANY"

    def test_retired_update_validates_clean(self) -> None:
        current = {
            "destination": {"zone_id": "z", "matching_target": "ANY", "port_matching_type": "SPECIFIC", "port": "53"}
        }
        update = {"destination": retire_stale_selectors(current["destination"], {"port_matching_type": "ANY"})}
        assert policy_update_targeting_error(current, update) is None


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
    def test_name_is_mutable(self) -> None:
        assert FIREWALLZONE_MUTABLE_FIELDS == frozenset({"name"})

    def test_read_only_excludes_name(self) -> None:
        all_fields = frozenset(FirewallZone.model_fields.keys())
        assert FIREWALLZONE_READ_ONLY_FIELDS == all_fields - FIREWALLZONE_MUTABLE_FIELDS
        assert "name" not in FIREWALLZONE_READ_ONLY_FIELDS
        assert "id" in FIREWALLZONE_READ_ONLY_FIELDS
        assert "networks" in FIREWALLZONE_READ_ONLY_FIELDS


class TestFirewallZoneCreateUpdate:
    def test_to_zone_create_includes_empty_network_ids(self) -> None:
        payload = to_zone_create(FirewallZone(name="IoT"))
        assert payload == {"name": "IoT", "networkIds": []}

    def test_to_zone_create_never_writes_read_only_networks(self) -> None:
        payload = to_zone_create(FirewallZone(name="IoT", networks=["n1", "n2"]))
        assert payload == {"name": "IoT", "networkIds": []}

    def test_to_zone_update_filters_to_name(self) -> None:
        result = to_zone_update({"name": "IoT", "id": "x", "networks": []})
        assert result == {"name": "IoT"}

    def test_to_zone_update_drops_none(self) -> None:
        assert to_zone_update({"name": None}) == {}


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


# ---------------------------------------------------------------------------
# LegacyFirewallRule — pre-zone-based engine (V1 /rest/firewallrule)
# ---------------------------------------------------------------------------

#: A representative rule as the controller returns it. Field names and value
#: shapes follow the controller-generated schema used by the Terraform/Pulumi
#: providers, since the V2 zone-based engine uses entirely different names.
RAW_LEGACY_RULE = {
    "_id": "60f1a2b3c4d5e6f7a8b9c0d1",
    "site_id": "5f0000000000000000000001",
    "name": "Block IoT to LAN",
    "ruleset": "LAN_IN",
    "rule_index": 2001,
    "action": "drop",
    "enabled": True,
    "protocol": "all",
    "protocol_v6": "",
    "protocol_match_excepted": False,
    "src_address": "192.168.30.0/24",
    "src_address_ipv6": "",
    "src_port": "",
    "src_mac_address": "",
    "src_firewallgroup_ids": ["grp-src-1"],
    "src_networkconf_id": "net-iot",
    "src_networkconf_type": "NETv4",
    "dst_address": "192.168.10.0/24",
    "dst_address_ipv6": "",
    "dst_port": "443",
    "dst_firewallgroup_ids": ["grp-dst-1", "grp-dst-2"],
    "dst_networkconf_id": "net-lan",
    "dst_networkconf_type": "NETv4",
    "state_new": True,
    "state_established": False,
    "state_related": False,
    "state_invalid": False,
    "icmp_typename": "",
    "icmpv6_typename": "",
    "ipsec": "match-none",
    "logging": True,
    "setting_preference": "manual",
    "attr_no_edit": False,
    "attr_no_delete": False,
}


class TestLegacyFirewallRuleModel:
    def test_is_read_only(self) -> None:
        assert LEGACYFIREWALLRULE_MUTABLE_FIELDS == frozenset()
        assert LEGACYFIREWALLRULE_READ_ONLY_FIELDS == frozenset(LegacyFirewallRule.model_fields.keys())

    def test_ruleset_enum_includes_ipv6_variants(self) -> None:
        assert len(LEGACY_RULESETS) == 18
        for name in ("WAN_IN", "LAN_OUT", "GUEST_LOCAL", "LANv6_IN", "GUESTv6_OUT", "WANv6_LOCAL"):
            assert name in LEGACY_RULESETS

    def test_legacy_actions_are_lowercase(self) -> None:
        """The V2 engine uses ALLOW/BLOCK/REJECT; the legacy engine does not."""
        assert LEGACY_ACTIONS == {"accept", "drop", "reject"}


class TestLegacyFirewallRuleFromController:
    def test_maps_every_documented_field(self) -> None:
        r = legacy_firewall_rule_from_controller(RAW_LEGACY_RULE)
        assert r.id == "60f1a2b3c4d5e6f7a8b9c0d1"
        assert r.name == "Block IoT to LAN"
        assert r.ruleset == "LAN_IN"
        assert r.rule_index == 2001
        assert r.action == "drop"
        assert r.enabled is True
        assert r.src_address == "192.168.30.0/24"
        assert r.src_firewallgroup_ids == ["grp-src-1"]
        assert r.src_networkconf_id == "net-iot"
        assert r.src_networkconf_type == "NETv4"
        assert r.dst_port == "443"
        assert r.dst_firewallgroup_ids == ["grp-dst-1", "grp-dst-2"]
        assert r.ipsec == "match-none"
        assert r.logging is True
        assert r.setting_preference == "manual"

    def test_state_flags_preserve_false(self) -> None:
        """False is a meaningful value here and must not collapse to None."""
        r = legacy_firewall_rule_from_controller(RAW_LEGACY_RULE)
        assert r.state_new is True
        assert r.state_established is False
        assert r.state_related is False
        assert r.state_invalid is False

    def test_maps_attr_flags_to_friendly_names(self) -> None:
        r = legacy_firewall_rule_from_controller({**RAW_LEGACY_RULE, "attr_no_edit": True, "attr_no_delete": True})
        assert r.no_edit is True
        assert r.no_delete is True

    def test_drops_site_id_and_unknown_keys(self) -> None:
        r = legacy_firewall_rule_from_controller({**RAW_LEGACY_RULE, "totally_unknown": "x"})
        dumped = r.model_dump()
        assert "site_id" not in dumped
        assert "totally_unknown" not in dumped

    def test_coerces_string_rule_index(self) -> None:
        r = legacy_firewall_rule_from_controller({"_id": "r", "rule_index": "2005"})
        assert r.rule_index == 2005

    def test_non_numeric_rule_index_becomes_none(self) -> None:
        r = legacy_firewall_rule_from_controller({"_id": "r", "rule_index": "not-a-number"})
        assert r.rule_index is None

    def test_non_list_firewallgroup_ids_become_empty(self) -> None:
        r = legacy_firewall_rule_from_controller({"_id": "r", "src_firewallgroup_ids": "grp-1"})
        assert r.src_firewallgroup_ids == []

    def test_non_string_group_members_are_dropped(self) -> None:
        r = legacy_firewall_rule_from_controller({"_id": "r", "dst_firewallgroup_ids": ["ok", 7, None]})
        assert r.dst_firewallgroup_ids == ["ok"]

    def test_non_bool_enabled_becomes_none(self) -> None:
        r = legacy_firewall_rule_from_controller({"_id": "r", "enabled": "yes"})
        assert r.enabled is None

    def test_handles_empty_dict(self) -> None:
        r = legacy_firewall_rule_from_controller({})
        assert r.id is None
        assert r.ruleset is None
        assert r.src_firewallgroup_ids == []
        assert r.dst_firewallgroup_ids == []

    def test_falls_back_to_id_key(self) -> None:
        r = legacy_firewall_rule_from_controller({"id": "alt-id"})
        assert r.id == "alt-id"
