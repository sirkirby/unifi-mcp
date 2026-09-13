"""Unit tests for the Network FirewallRule, FirewallGroup, FirewallZone domain models."""

from __future__ import annotations

import pytest
from unifi_core.network.models.firewall import (
    FIREWALLGROUP_MUTABLE_FIELDS,
    FIREWALLGROUP_READ_ONLY_FIELDS,
    FIREWALLGROUP_UPDATE_FIELDS,
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
    activator_is_known,
    firewall_group_from_controller,
    firewall_zone_from_controller,
    from_controller,
    legacy_firewall_rule_from_controller,
    normalize_policy_enums,
    normalize_policy_update,
    policy_update_targeting_error,
    prepare_policy_update,
    retire_stale_selectors,
    to_controller_update,
    to_group_create,
    to_zone_create,
    to_zone_update,
    validate_group_create,
    validate_group_update,
    validate_policy_port_targeting,
    validate_policy_selectors,
    validate_zone_targeting,
)


@pytest.mark.parametrize("direction", ["source", "destination"])
@pytest.mark.parametrize("port", [None, "", " ", 445, ["445"], True, {}])
def test_policy_specific_port_rejects_malformed_values(direction, port):
    with pytest.raises(ValueError, match=rf"{direction}\.port.*non-empty string"):
        validate_policy_port_targeting({direction: {"port_matching_type": "SPECIFIC", "port": port}})


@pytest.mark.parametrize("direction", ["source", "destination"])
@pytest.mark.parametrize("mode", ["ANY", "SPECIFIC", "OBJECT"])
def test_policy_plural_ports_rejected_even_with_valid_singular_port(direction, mode):
    with pytest.raises(ValueError, match=rf"{direction}\.ports is not a valid field"):
        validate_policy_port_targeting({direction: {"port_matching_type": mode, "ports": [], "port": "445"}})


@pytest.mark.parametrize(
    "endpoint",
    [
        {},
        {"port_matching_type": "ANY"},
        {"port_matching_type": "OBJECT", "port_group_id": "group"},
        {"port_matching_type": "SPECIFIC", "port": "445"},
        {"port_matching_type": "SPECIFIC", "port": "1000-2000"},
    ],
)
def test_policy_valid_port_targeting_preserves_input(endpoint):
    import copy

    data = {"source": endpoint, "destination": endpoint}
    before = copy.deepcopy(data)
    validate_policy_port_targeting(data)
    assert data == before


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
            ({"action": "SENTINEL-caller-value"}, "must be one of ALLOW, BLOCK, REJECT"),
            ({"id": "read-only"}, "effectively empty"),
            ({"index": 2000, "enabled": True}, "unifi_reorder_firewall_policies"),
            ({"index": 2000}, "unifi_reorder_firewall_policies"),
            ({"destination": {"port_matching_type": "ANY", "port": "53"}}, "port_matching_type"),
            ({"source": {"matching_target": "ANY", "client_macs": ["aa:bb:cc:dd:ee:ff"]}}, "matching_target"),
        ],
    )
    def test_rejects_legacy_invalid_or_empty_updates(self, fields: dict, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            normalize_policy_update(fields)

    def test_the_action_rejection_does_not_echo_the_submitted_value(self) -> None:
        """It reaches the API audit row, which scrubs secret-keyed values only."""
        with pytest.raises(ValueError) as excinfo:
            normalize_policy_update({"action": "SENTINEL-caller-value"})

        assert "SENTINEL-caller-value" not in str(excinfo.value)


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

    def test_an_activation_only_update_passes_the_stateless_boundary(self) -> None:
        """Switching to OBJECT without naming port_group_id may be perfectly valid against
        a policy that already stores one; only prepare_policy_update can tell."""
        assert normalize_policy_update({"destination": {"port_matching_type": "OBJECT"}}) == {
            "destination": {"port_matching_type": "OBJECT"}
        }
        assert normalize_policy_update({"source": {"matching_target": "CLIENT"}}) == {
            "source": {"matching_target": "CLIENT"}
        }

    def test_normalize_policy_update_inherits_endpoint_enums(self) -> None:
        result = normalize_policy_update({"destination": {"port_matching_type": "object", "port_group_id": "g1"}})

        assert result == {"destination": {"port_matching_type": "OBJECT", "port_group_id": "g1"}}


class TestValidatePolicySelectors:
    """The selector half of V2 targeting: CLIENT, port OBJECT, and the rule that a
    selector is only accepted under the enum value that activates it. Port *shape*
    under SPECIFIC stays with validate_policy_port_targeting; zone/IP/NETWORK
    requirements stay with the Network tool's _validate_zone_targeting."""

    @staticmethod
    def _policy(**destination):
        return {
            "source": {"zone_id": "z1", "matching_target": "ANY"},
            "destination": {"zone_id": "z2", "matching_target": "ANY", **destination},
        }

    def _error(self, **destination) -> str:
        with pytest.raises(ValueError) as excinfo:
            validate_policy_selectors(self._policy(**destination))
        return str(excinfo.value)

    def test_client_target_requires_client_macs(self) -> None:
        assert "client_macs" in self._error(matching_target="CLIENT")
        assert "client_macs" in self._error(matching_target="CLIENT", client_macs=[])
        validate_policy_selectors(self._policy(matching_target="CLIENT", client_macs=["aa:bb:cc:dd:ee:ff"]))

    def test_object_port_matching_requires_port_group_id(self) -> None:
        assert "port_group_id" in self._error(port_matching_type="OBJECT")
        validate_policy_selectors(self._policy(port_matching_type="OBJECT", port_group_id="g1"))

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
        """A selector the controller would accept and silently ignore must not pass validation."""
        assert expected in self._error(**extra)

    @pytest.mark.parametrize("macs", ["aa:bb:cc:dd:ee:ff", ["zz"], [" "], [None]])
    def test_client_macs_must_be_a_list_of_valid_macs(self, macs) -> None:
        assert "client_macs" in self._error(matching_target="CLIENT", client_macs=macs)

    def test_client_macs_accepts_mixed_case_and_dashes(self) -> None:
        validate_policy_selectors(self._policy(matching_target="CLIENT", client_macs=["AA-BB-CC-DD-EE-FF"]))

    def test_unknown_targets_and_port_types_pass_through(self) -> None:
        validate_policy_selectors(self._policy(matching_target="APP", app_ids=["x"]))
        validate_policy_selectors(self._policy(port_matching_type="SOMETHING_NEW"))

    def test_any_and_absent_endpoints_need_nothing(self) -> None:
        validate_policy_selectors(self._policy(port_matching_type="ANY"))
        validate_policy_selectors({"source": None, "destination": None})

    def test_port_shape_and_zone_requirements_are_not_this_function(self) -> None:
        """Boundary pin: the SPECIFIC port string is validate_policy_port_targeting's and
        the IP/NETWORK requirements are validate_zone_targeting's."""
        validate_policy_selectors(self._policy(port_matching_type="SPECIFIC", port="not-a-port"))
        validate_policy_selectors(self._policy(matching_target="IP"))

    def test_non_dict_endpoint_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="source"):
            validate_policy_selectors({"source": "ANY", "destination": None})

    @pytest.mark.parametrize(
        ("macs", "forbidden"),
        [
            (["aa:bb:cc:dd:ee:ff", "nope"], "aa:bb:cc:dd:ee:ff"),
            (["nope"], "nope"),
            ("aa:bb:cc:dd:ee:ff", "aa:bb:cc:dd:ee:ff"),
            ([], "["),
            # A real address in a spelling looks_like_mac rejects: the element that fails
            # IS the MAC, so only a message that quotes nothing keeps it out.
            (["aabb.ccdd.eeff"], "aabb.ccdd.eeff"),
            (["11:22:33:44:55:66:77"], "11:22:33:44:55:66"),
        ],
    )
    def test_the_message_never_quotes_a_mac_address(self, macs, forbidden: str) -> None:
        """It reaches tool logs and the API audit row, where a MAC must never land."""
        error = self._error(matching_target="CLIENT", client_macs=macs)
        assert forbidden not in error
        assert "client_macs" in error

    def test_the_chosen_enums_own_gap_is_reported_before_a_leftover_selector(self) -> None:
        """Reporting the leftover first tells a caller to undo the mode they just asked for."""
        error = self._error(port_matching_type="OBJECT", port="53")
        assert "port_group_id" in error

    def test_a_leftover_selector_is_named_as_the_thing_to_remove(self) -> None:
        """The chosen mode is valid and complete; it is the stale selector that must go."""
        error = self._error(port_matching_type="SPECIFIC", port="53", port_group_id="g1")
        assert error.startswith("destination.port_group_id is ignored while")
        assert "Remove it, or set destination.port_matching_type to 'OBJECT'." in error

    def test_an_unrecognised_enum_value_is_not_echoed_into_the_message(self) -> None:
        error = self._error(port_matching_type="SENTINEL-caller-value", port="53")
        assert "SENTINEL-caller-value" not in error
        assert "an unrecognised value" in error

    def test_an_absent_activator_is_named_as_unset(self) -> None:
        assert "is unset" in self._error(port="53")

    def test_a_read_modify_write_that_echoes_a_stale_selector_is_rejected(self) -> None:
        """Deliberate, and asymmetric with the partial form: the echoed document itself
        contains the contradiction, and the stateless boundary is the only check the API
        preview gets. Sending the same intent as a partial dict is accepted."""
        stale = {"zone_id": "z", "matching_target": "ANY", "port_matching_type": "ANY", "port": "53"}
        with pytest.raises(ValueError, match="port_matching_type"):
            normalize_policy_update({"source": stale})
        assert normalize_policy_update({"source": {"zone_id": "z9"}}) == {"source": {"zone_id": "z9"}}

    @pytest.mark.parametrize("value", ["object", " Object ", "OBJECT"])
    def test_activation_is_case_insensitive(self, value: str) -> None:
        """Callers reach this through several normalization histories; a case-sensitive
        check gave two surfaces opposite verdicts on the same policy."""
        assert "port_group_id" in self._error(port_matching_type=value)

    def test_a_lower_case_client_target_is_not_read_as_a_leftover_selector(self) -> None:
        validate_policy_selectors(self._policy(matching_target="client", client_macs=["aa:bb:cc:dd:ee:ff"]))

    @pytest.mark.parametrize(
        ("key", "value", "known"),
        [
            ("matching_target", "CLIENT", True),
            ("matching_target", "client", True),
            ("matching_target", "APP", False),
            ("port_matching_type", "OBJECT", True),
            ("port_matching_type", "PORT_GROUP", False),
            ("port_matching_type", None, False),
            ("something_else", "ANY", False),
        ],
    )
    def test_activator_is_known_marks_the_values_this_project_has_seen(self, key, value, known) -> None:
        assert activator_is_known(key, value) is known


class TestValidateZoneTargeting:
    """The matching_target completeness rules, moved from the Network tool so the
    update path and the API create path get them too. Same messages, same order."""

    @staticmethod
    def _policy(**source):
        return {
            "source": {"zone_id": "z1", **source},
            "destination": {"zone_id": "z2", "matching_target": "ANY"},
        }

    @pytest.mark.parametrize(
        ("endpoint", "expected"),
        [
            ({"matching_target": "IP"}, "source.matching_target_type is required"),
            ({"matching_target": "NETWORK"}, "source.matching_target_type is required"),
            ({"matching_target": "IP", "matching_target_type": "OBJECT"}, "source.ip_group_id is required"),
            ({"matching_target": "IP", "matching_target_type": "SPECIFIC"}, "source.ips array is required"),
            ({"matching_target": "NETWORK", "matching_target_type": "OBJECT"}, "source.network_ids array is required"),
        ],
    )
    def test_an_incomplete_target_is_rejected(self, endpoint: dict, expected: str) -> None:
        assert expected in validate_zone_targeting(self._policy(**endpoint))

    @pytest.mark.parametrize(
        "endpoint",
        [
            {"matching_target": "ANY"},
            {"matching_target": "IP", "matching_target_type": "SPECIFIC", "ips": ["10.0.0.1"]},
            {"matching_target": "IP", "matching_target_type": "OBJECT", "ip_group_id": "g1"},
            {"matching_target": "NETWORK", "matching_target_type": "OBJECT", "network_ids": ["n1"]},
            {"matching_target": "CLIENT", "client_macs": ["aa:bb:cc:dd:ee:ff"]},
            {"matching_target": "APP", "app_ids": ["x"]},
        ],
    )
    def test_a_complete_or_unknown_target_passes(self, endpoint: dict) -> None:
        assert validate_zone_targeting(self._policy(**endpoint)) is None

    def test_a_non_dict_endpoint_is_left_to_the_selector_check(self) -> None:
        assert validate_zone_targeting({"source": "ANY", "destination": None}) is None


class TestPolicyUpdateTargetingError:
    _stored = {"zone_id": "z2", "matching_target": "ANY", "port_matching_type": "ANY"}

    def test_partial_update_is_validated_as_merged(self) -> None:
        current = {"destination": dict(self._stored)}
        assert policy_update_targeting_error(current, {"destination": {"port_matching_type": "OBJECT"}}) is not None
        assert (
            policy_update_targeting_error(current, {"destination": {"port_matching_type": "SPECIFIC", "port": "53"}})
            is None
        )

    def test_merged_port_shape_is_validated(self) -> None:
        """Blanking the port of a stored SPECIFIC match is only invalid after the merge:
        the update dict alone carries no port_matching_type to judge it against."""
        current = {
            "destination": {
                "zone_id": "z2",
                "matching_target": "ANY",
                "port_matching_type": "SPECIFIC",
                "port": "53",
            }
        }
        error = policy_update_targeting_error(current, {"destination": {"port": "   "}})
        assert error is not None and "destination.port" in error

    def test_untouched_side_is_not_revalidated(self) -> None:
        current = {"source": {"zone_id": "x", "matching_target": "CLIENT"}, "destination": dict(self._stored)}
        assert (
            policy_update_targeting_error(current, {"destination": {"port_matching_type": "SPECIFIC", "port": "53"}})
            is None
        )

    def test_preexisting_error_on_the_updated_side_is_not_held_against_the_update(self) -> None:
        current = {"destination": {"zone_id": "z2", "matching_target": "CLIENT", "client_macs": []}}
        assert (
            policy_update_targeting_error(current, {"destination": {"port_matching_type": "SPECIFIC", "port": "53"}})
            is None
        )

    def test_new_error_is_reported_even_when_a_different_one_preexists(self) -> None:
        current = {"destination": {"zone_id": "z2", "matching_target": "CLIENT", "client_macs": []}}
        error = policy_update_targeting_error(current, {"destination": {"port": "53"}})
        assert error is not None and "port_matching_type" in error

    @pytest.mark.parametrize(
        ("stored", "update", "expected"),
        [
            (
                {"matching_target": "CLIENT", "client_macs": []},
                {"client_macs": ["zz"]},
                "client_macs[0]",
            ),
            # Two writes to the same bad selector produce the same words, so suppressing
            # by message text would let the second one through.
            (
                {"matching_target": "ANY", "port_matching_type": "ANY", "port": "445"},
                {"port": "80"},
                "port_matching_type",
            ),
            (
                {"matching_target": "ANY", "port_matching_type": "SPECIFIC", "port_group_id": "g_old"},
                {"port_group_id": "g_new"},
                "port_matching_type",
            ),
            (
                {"matching_target": "ANY", "port_matching_type": "ANY", "port": "445"},
                {"port_matching_type": "OBJECT"},
                "port_group_id",
            ),
            # The matching_target family, which used to be checked on create only.
            ({"matching_target": "ANY"}, {"matching_target": "IP"}, "matching_target_type is required"),
            (
                {"matching_target": "ANY"},
                {"matching_target": "NETWORK", "matching_target_type": "OBJECT"},
                "network_ids array is required",
            ),
            (
                {"matching_target": "IP", "matching_target_type": "SPECIFIC", "ips": ["10.0.0.1"]},
                {"matching_target_type": "OBJECT"},
                "ip_group_id is required",
            ),
            # Stored side ALREADY broken, and the update touches a member of the same
            # family without fixing it: the caller now owns the result. Excusing this
            # because the error was there before lets an update leave a policy matching
            # nothing while reporting success.
            (
                {"matching_target": "IP", "matching_target_type": "SPECIFIC"},
                {"matching_target_type": "OBJECT"},
                "ip_group_id is required",
            ),
            (
                {"matching_target": "IP", "matching_target_type": "SPECIFIC"},
                {"ips": []},
                "ips array is required",
            ),
            (
                {"matching_target": "NETWORK", "matching_target_type": "OBJECT"},
                {"network_ids": []},
                "network_ids array is required",
            ),
        ],
    )
    def test_writing_to_an_already_invalid_selector_is_reported(self, stored, update, expected) -> None:
        """A pre-existing error excuses an update that leaves the selector alone, not one
        that writes to it."""
        current = {"source": {"zone_id": "z", **stored}}
        error = policy_update_targeting_error(current, {"source": update})
        assert error is not None and expected in error

    @pytest.mark.parametrize(
        ("stored", "update", "expected"),
        [
            # Activating an already-junk stored selector: the update names no selector key,
            # only the enum that switches it on, and the caller now owns the result.
            ({"matching_target": "ANY", "client_macs": ["nope"]}, {"matching_target": "CLIENT"}, "client_macs[0]"),
            (
                {"matching_target": "ANY", "port_matching_type": "ANY", "port": "  "},
                {"port_matching_type": "SPECIFIC"},
                "source.port",
            ),
            (
                {"matching_target": "ANY", "port_matching_type": "ANY", "port_group_id": ""},
                {"port_matching_type": "OBJECT"},
                "port_group_id",
            ),
            # The plural alias is the same field to validate_policy_port_targeting.
            (
                {"matching_target": "ANY", "port_matching_type": "ANY"},
                {"ports": ["445"]},
                "ports is not a valid field",
            ),
        ],
    )
    def test_activating_an_already_invalid_selector_is_reported(self, stored, update, expected) -> None:
        current = {"source": {"zone_id": "z", **stored}}
        error = policy_update_targeting_error(current, {"source": update})
        assert error is not None and expected in error

    def test_a_selector_the_update_never_touches_stays_excused(self) -> None:
        current = {"source": {"zone_id": "z", "matching_target": "ANY", "port_matching_type": "ANY", "port": "445"}}
        assert policy_update_targeting_error(current, {"source": {"zone_id": "z2"}}) is None

    def test_a_zone_gap_the_controller_already_had_is_not_held_against_an_unrelated_update(self) -> None:
        """State this project did not author: an IP side with no ips, already stored,
        must not block a rename or a port change."""
        current = {"source": {"zone_id": "z", "matching_target": "IP", "matching_target_type": "SPECIFIC"}}
        assert policy_update_targeting_error(current, {"source": {"zone_id": "z2"}}) is None

    def test_a_completed_target_clears_the_error_it_had(self) -> None:
        current = {"source": {"zone_id": "z", "matching_target": "IP", "matching_target_type": "SPECIFIC"}}
        assert policy_update_targeting_error(current, {"source": {"ips": ["10.0.0.1"]}}) is None

    def test_missing_or_non_dict_stored_side_validates_the_update_alone(self) -> None:
        assert (
            policy_update_targeting_error(
                {"destination": None}, {"destination": {"zone_id": "z", "matching_target": "ANY"}}
            )
            is None
        )
        assert "object" in policy_update_targeting_error({"source": "junk"}, {"source": "ANY"})


class TestPreparePolicyUpdate:
    """The one update path both MCP and API run composes retirement with merged-state
    validation; each half is covered by its own class."""

    _stored = {"zone_id": "z2", "matching_target": "ANY", "port_matching_type": "SPECIFIC", "port": "53"}

    def test_selector_only_update_on_inactive_stored_enum_is_rejected(self) -> None:
        current = {"destination": {"zone_id": "z2", "matching_target": "ANY", "port_matching_type": "ANY"}}
        with pytest.raises(ValueError, match="port_matching_type"):
            prepare_policy_update(current, {"destination": {"port": "53"}})

    def test_activation_change_retires_the_stored_selector(self) -> None:
        current = {"destination": dict(self._stored)}
        assert prepare_policy_update(current, {"destination": {"port_matching_type": "ANY"}}) == {
            "destination": {"port_matching_type": "ANY", "port": None}
        }

    @pytest.mark.parametrize("value", ["SPECIFIC", "specific", " Specific "])
    def test_a_lower_case_activation_does_not_slip_past_the_port_shape_check(self, value: str) -> None:
        """Activation is compared case-insensitively and the port shape check is not, so
        an un-normalized update could look active to one and inert to the other."""
        current = {"destination": {"zone_id": "z2", "matching_target": "ANY", "port_matching_type": "ANY"}}
        with pytest.raises(ValueError, match="destination.port"):
            prepare_policy_update(current, {"destination": {"port_matching_type": value}})

    def test_endpoint_enums_are_upper_cased_in_the_prepared_update(self) -> None:
        current = {"destination": {"zone_id": "z2", "matching_target": "ANY", "port_matching_type": "ANY"}}
        prepared = prepare_policy_update(current, {"destination": {"port_matching_type": "specific", "port": "53"}})
        assert prepared["destination"]["port_matching_type"] == "SPECIFIC"

    def test_non_endpoint_updates_pass_through_untouched(self) -> None:
        current = {"destination": dict(self._stored)}
        assert prepare_policy_update(current, {"enabled": False}) == {"enabled": False}

    def test_the_caller_dict_is_not_mutated(self) -> None:
        current = {"destination": dict(self._stored)}
        updates = {"destination": {"port_matching_type": "ANY"}}
        prepare_policy_update(current, updates)
        assert updates == {"destination": {"port_matching_type": "ANY"}}


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

    def test_a_stored_empty_selector_is_still_retired(self) -> None:
        """Truthiness is not the question: an empty stored port under SPECIFIC must be
        removed from the PUT, not sent back as ''."""
        stored = {"port_matching_type": "SPECIFIC", "port": ""}
        assert retire_stale_selectors(stored, {"port_matching_type": "ANY"}) == {
            "port_matching_type": "ANY",
            "port": None,
        }

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


class TestFirewallGroupValidation:
    def test_create_translates_public_members(self) -> None:
        payload = validate_group_create({"name": "Web", "group_type": "port-group", "members": ["80", "443"]})

        assert payload == {
            "name": "Web",
            "group_type": "port-group",
            "group_members": ["80", "443"],
        }

    @pytest.mark.parametrize("missing", ["name", "group_type", "members"])
    def test_create_requires_complete_public_shape(self, missing: str) -> None:
        fields = {"name": "Web", "group_type": "port-group", "members": ["443"]}
        fields.pop(missing)

        with pytest.raises(ValueError, match="Missing required"):
            validate_group_create(fields)

    def test_create_rejects_controller_dialect(self) -> None:
        with pytest.raises(ValueError, match="group_members"):
            validate_group_create({"name": "Web", "group_type": "port-group", "group_members": ["443"]})

    def test_create_rejects_unknown_group_type(self) -> None:
        with pytest.raises(ValueError, match="group_type"):
            validate_group_create({"name": "Web", "group_type": "ports", "members": ["443"]})

    def test_update_fields_exclude_immutable_type(self) -> None:
        assert FIREWALLGROUP_UPDATE_FIELDS == frozenset({"name", "members"})

    def test_update_translates_only_submitted_fields(self) -> None:
        assert validate_group_update({"members": []}) == {"group_members": []}
        assert validate_group_update({"name": "Renamed"}) == {"name": "Renamed"}

    def test_update_rejects_group_type(self) -> None:
        with pytest.raises(ValueError, match="cannot be changed"):
            validate_group_update({"group_type": "port-group"})

    def test_update_rejects_empty_payload(self) -> None:
        with pytest.raises(ValueError, match="No firewall group fields"):
            validate_group_update({})


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
