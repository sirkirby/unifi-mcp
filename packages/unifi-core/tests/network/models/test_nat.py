"""Unit tests for the Network NatRule domain model."""

from __future__ import annotations

import pytest
from unifi_core.network.models.nat import (
    FILTER_SELECTORS,
    MUTABLE_FIELDS,
    OBSERVED_FILTER_TYPES,
    OBSERVED_RULE_TYPES,
    READ_ONLY_FIELDS,
    RULE_SELECTORS,
    NatRule,
    from_controller,
    merge_nat_update,
    nat_rule_error,
    nat_update_error,
    normalize_nat_create,
    normalize_nat_enums,
    normalize_nat_update,
    reject_unknown_fields,
    to_controller_create,
    to_controller_update,
)

from tests.network.nat_fixtures import DNS_REDIRECT, NONE_FILTER, dnat


class TestFieldSets:
    def test_mutable_fields_contains_every_writable_key(self) -> None:
        for field in (
            "type",
            "description",
            "enabled",
            "rule_index",
            "protocol",
            "ip_version",
            "in_interface",
            "out_interface",
            "ip_address",
            "port",
            "logging",
            "exclude",
            "pppoe_use_base_interface",
            "source_filter",
            "destination_filter",
        ):
            assert field in MUTABLE_FIELDS, field

    def test_read_only_fields(self) -> None:
        assert READ_ONLY_FIELDS == {"id", "is_predefined", "setting_preference"}

    def test_sets_are_disjoint_and_cover_the_model(self) -> None:
        assert not MUTABLE_FIELDS & READ_ONLY_FIELDS
        assert MUTABLE_FIELDS | READ_ONLY_FIELDS == frozenset(NatRule.model_fields)

    def test_observed_enums_match_the_controller(self) -> None:
        assert OBSERVED_RULE_TYPES == {"DNAT", "SNAT", "MASQUERADE"}
        assert OBSERVED_FILTER_TYPES == {"NONE", "ADDRESS_AND_PORT", "FIREWALL_GROUPS", "NETWORK_CONF"}

    def test_selector_tables(self) -> None:
        assert {s: a for s, a, _ in FILTER_SELECTORS} == {
            "address": {"ADDRESS_AND_PORT"},
            "port": {"ADDRESS_AND_PORT"},
            "network_conf_id": {"NETWORK_CONF"},
            "firewall_group_ids": {"FIREWALL_GROUPS"},
        }
        assert {s: a for s, a, _ in RULE_SELECTORS} == {
            "ip_address": {"DNAT", "SNAT"},
            "port": {"DNAT", "SNAT"},
        }


class TestFromController:
    def test_live_dnat_round_trip(self) -> None:
        rule = from_controller(DNS_REDIRECT)
        assert rule.id == "6f0000000000000000000001"
        assert rule.type == "DNAT"
        assert rule.rule_index == 3
        assert rule.ip_address == "192.0.2.53"
        assert rule.port == "53"
        assert rule.is_predefined is False
        assert rule.setting_preference == "manual"
        assert rule.destination_filter["invert_address"] is True
        assert rule.destination_filter["address"] == "192.0.2.53"

    def test_masquerade_has_no_translation_or_in_interface(self) -> None:
        raw = {
            "_id": "6f0000000000000000000002",
            "type": "MASQUERADE",
            "out_interface": "6f0000000000000000000020",
            "protocol": "all",
            "ip_version": "IPV4",
            "enabled": False,
            "source_filter": dict(NONE_FILTER),
            "destination_filter": dict(NONE_FILTER),
        }
        rule = from_controller(raw)
        assert rule.type == "MASQUERADE"
        assert rule.out_interface == "6f0000000000000000000020"
        assert rule.in_interface is None
        assert rule.ip_address is None
        assert rule.port is None
        assert rule.rule_index is None

    def test_hides_selector_stored_under_a_non_activating_filter_type(self) -> None:
        raw = dict(DNS_REDIRECT, source_filter={**NONE_FILTER, "address": "198.51.100.0/24", "port": "53"})
        rule = from_controller(raw)
        assert "address" not in rule.source_filter
        assert "port" not in rule.source_filter
        assert rule.source_filter["firewall_group_ids"] == []

    def test_hides_a_non_empty_group_list_under_a_non_activating_filter_type(self) -> None:
        raw = dict(DNS_REDIRECT, source_filter={**NONE_FILTER, "firewall_group_ids": ["g1"]})
        assert "firewall_group_ids" not in from_controller(raw).source_filter

    def test_hides_translation_stored_on_a_masquerade(self) -> None:
        raw = dict(DNS_REDIRECT, type="MASQUERADE", out_interface="wan")
        rule = from_controller(raw)
        assert rule.ip_address is None
        assert rule.port is None

    def test_keeps_selectors_under_an_unobserved_filter_type(self) -> None:
        raw = dict(DNS_REDIRECT, source_filter={**NONE_FILTER, "filter_type": "IID_AND_PORT", "port": "53"})
        assert from_controller(raw).source_filter["port"] == "53"

    def test_handles_empty_dict(self) -> None:
        rule = from_controller({})
        assert rule.id is None
        assert rule.type is None
        assert rule.source_filter is None


class TestNormalizeEnums:
    def test_upper_cases_type_ip_version_and_filter_types(self) -> None:
        out = normalize_nat_enums(
            {
                "type": " dnat ",
                "ip_version": "ipv4",
                "protocol": "TCP_UDP",
                "source_filter": {"filter_type": "none"},
                "destination_filter": {"filter_type": " address_and_port"},
            }
        )
        assert out["type"] == "DNAT"
        assert out["ip_version"] == "IPV4"
        assert out["protocol"] == "tcp_udp"
        assert out["source_filter"]["filter_type"] == "NONE"
        assert out["destination_filter"]["filter_type"] == "ADDRESS_AND_PORT"

    def test_leaves_non_strings_and_other_keys_alone(self) -> None:
        fields = {"type": 7, "source_filter": "bad", "description": "Keep Case"}
        assert normalize_nat_enums(fields) == fields

    def test_does_not_mutate_input(self) -> None:
        fields = {"type": "dnat", "source_filter": {"filter_type": "none"}}
        normalize_nat_enums(fields)
        assert fields == {"type": "dnat", "source_filter": {"filter_type": "none"}}


class TestRejectUnknownFields:
    def test_accepts_mutable_keys(self) -> None:
        reject_unknown_fields({"description": "x", "source_filter": {}})

    def test_rejects_unknown_and_read_only_keys(self) -> None:
        with pytest.raises(ValueError) as exc:
            reject_unknown_fields({"bogus": 1, "is_predefined": True})
        assert "bogus" in str(exc.value)
        assert "is_predefined" in str(exc.value)
        assert "description" in str(exc.value)


class TestToController:
    def test_create_drops_none_and_read_only(self) -> None:
        model = NatRule(id="x", is_predefined=True, type="DNAT", description=None, enabled=False)
        assert to_controller_create(model) == {"type": "DNAT", "enabled": False}

    def test_update_filters_read_only_unknown_and_none(self) -> None:
        assert to_controller_update(
            {"id": "x", "setting_preference": "auto", "nope": 1, "port": None, "enabled": True}
        ) == {"enabled": True}


class TestRuleError:
    def test_live_dnat_is_valid(self) -> None:
        assert nat_rule_error(dnat()) is None

    def test_snat_needs_out_interface_and_ip_address(self) -> None:
        assert nat_rule_error(dnat(type="SNAT", out_interface="6f0000000000000000000020", port=None)) is None
        error = nat_rule_error(dnat(type="SNAT", port=None))
        assert error is not None and "out_interface" in error and "'SNAT'" in error

    def test_masquerade_needs_out_interface_and_no_translation(self) -> None:
        good = {
            "type": "MASQUERADE",
            "out_interface": "6f0000000000000000000020",
            "protocol": "all",
            "source_filter": dict(NONE_FILTER),
            "destination_filter": dict(NONE_FILTER),
        }
        assert nat_rule_error(good) is None
        error = nat_rule_error({**good, "ip_address": "192.0.2.1"})
        assert error is not None and "ip_address" in error and "'MASQUERADE'" in error
        error = nat_rule_error({**good, "port": "53"})
        assert error is not None and "port" in error
        error = nat_rule_error({**good, "out_interface": None})
        assert error is not None and "out_interface" in error and "'MASQUERADE'" in error

    @pytest.mark.parametrize("missing", ["in_interface", "ip_address"])
    def test_dnat_requires_interface_and_target(self, missing: str) -> None:
        error = nat_rule_error(dnat(**{missing: None}))
        assert error is not None and missing in error and "'DNAT'" in error

    def test_dnat_requires_a_destination_filter(self) -> None:
        error = nat_rule_error(dnat(destination_filter=dict(NONE_FILTER)))
        assert error is not None and "destination_filter" in error and "'NONE'" in error

    def test_unknown_rule_type_passes_through(self) -> None:
        assert nat_rule_error({"type": "FUTURE", "port": "53"}) is None

    def test_type_is_required(self) -> None:
        error = nat_rule_error({"description": "no type"})
        assert error is not None and "type" in error

    @pytest.mark.parametrize("port", ["53", "1000-2000", "53,853", "65535"])
    def test_valid_translation_ports(self, port: str) -> None:
        assert nat_rule_error(dnat(port=port)) is None

    @pytest.mark.parametrize("port", ["", "0", "65536", "53 ", " 53", "53\n", "2000-1000", "a", "53,", "53;853", 53])
    def test_invalid_translation_port_names_the_value(self, port) -> None:
        error = nat_rule_error(dnat(port=port))
        assert error is not None and repr(port) in error

    def test_rule_index_must_be_an_int(self) -> None:
        error = nat_rule_error(dnat(rule_index="3"))
        assert error is not None and "rule_index" in error and "'3'" in error

    def test_address_and_port_filter_needs_address_or_port(self) -> None:
        bare = {"filter_type": "ADDRESS_AND_PORT", "firewall_group_ids": []}
        error = nat_rule_error(dnat(source_filter=bare))
        assert error is not None and "source_filter" in error and "address" in error and "port" in error
        assert nat_rule_error(dnat(source_filter={**bare, "address": "198.51.100.0/24"})) is None
        assert nat_rule_error(dnat(source_filter={**bare, "port": "5353"})) is None

    def test_filter_port_is_validated(self) -> None:
        error = nat_rule_error(dnat(source_filter={"filter_type": "ADDRESS_AND_PORT", "port": "53 "}))
        assert error is not None and "source_filter.port" in error and repr("53 ") in error

    def test_firewall_groups_filter_needs_ids(self) -> None:
        error = nat_rule_error(dnat(source_filter={"filter_type": "FIREWALL_GROUPS", "firewall_group_ids": []}))
        assert error is not None and "firewall_group_ids" in error and "'FIREWALL_GROUPS'" in error
        ok = {"filter_type": "FIREWALL_GROUPS", "firewall_group_ids": ["6f0000000000000000000030"]}
        assert nat_rule_error(dnat(source_filter=ok)) is None

    def test_network_conf_filter_needs_network_conf_id(self) -> None:
        error = nat_rule_error(dnat(source_filter={"filter_type": "NETWORK_CONF"}))
        assert error is not None and "network_conf_id" in error and "'NETWORK_CONF'" in error
        ok = {"filter_type": "NETWORK_CONF", "network_conf_id": "6f0000000000000000000011"}
        assert nat_rule_error(dnat(source_filter=ok)) is None

    @pytest.mark.parametrize(
        "selector,value,activator",
        [
            ("address", "198.51.100.0/24", "ADDRESS_AND_PORT"),
            ("port", "53", "ADDRESS_AND_PORT"),
            ("network_conf_id", "6f0000000000000000000011", "NETWORK_CONF"),
            ("firewall_group_ids", ["6f0000000000000000000030"], "FIREWALL_GROUPS"),
        ],
    )
    def test_selector_under_a_non_activating_filter_type_is_rejected(self, selector, value, activator) -> None:
        error = nat_rule_error(dnat(source_filter={**NONE_FILTER, selector: value}))
        assert error is not None and f"source_filter.{selector}" in error and f"'{activator}'" in error

    def test_empty_firewall_group_ids_is_fine_under_any_filter_type(self) -> None:
        assert nat_rule_error(dnat(source_filter=dict(NONE_FILTER))) is None

    def test_unobserved_filter_type_passes_through(self) -> None:
        assert nat_rule_error(dnat(source_filter={"filter_type": "IID_AND_PORT", "port": "53"})) is None

    def test_filter_must_be_an_object(self) -> None:
        error = nat_rule_error(dnat(source_filter="NONE"))
        assert error is not None and "source_filter" in error

    def test_filter_type_is_required_on_a_filter(self) -> None:
        error = nat_rule_error(dnat(source_filter={"address": "198.51.100.1"}))
        assert error is not None and "source_filter.filter_type" in error


class TestNormalizeCreateAndUpdate:
    def test_create_normalizes_filters_and_validates(self) -> None:
        payload = normalize_nat_create(dnat(type="dnat", rule_index=None))
        assert payload["type"] == "DNAT"
        assert "rule_index" not in payload
        with pytest.raises(ValueError) as exc:
            normalize_nat_create(dnat(port="0"))
        assert "'0'" in str(exc.value)
        with pytest.raises(ValueError) as exc:
            normalize_nat_create(dnat(bogus=1))
        assert "bogus" in str(exc.value)

    def test_update_normalizes_and_filters_without_validating(self) -> None:
        assert normalize_nat_update({"type": "snat", "port": None, "enabled": False}) == {
            "type": "SNAT",
            "enabled": False,
        }
        with pytest.raises(ValueError):
            normalize_nat_update({"is_predefined": True})


class TestMergeUpdate:
    def test_partial_filter_update_keeps_sibling_keys(self) -> None:
        merged = merge_nat_update(dnat(), {"destination_filter": {"port": "853"}})
        assert merged["destination_filter"] == {**DNS_REDIRECT["destination_filter"], "port": "853"}
        assert merged["description"] == DNS_REDIRECT["description"]

    def test_switching_filter_type_drops_the_stored_selectors(self) -> None:
        merged = merge_nat_update(dnat(), {"destination_filter": {"filter_type": "NONE"}})
        assert merged["destination_filter"] == {**NONE_FILTER, "invert_address": True}

    def test_switching_away_from_firewall_groups_empties_the_list(self) -> None:
        stored = dnat(source_filter={**NONE_FILTER, "filter_type": "FIREWALL_GROUPS", "firewall_group_ids": ["g1"]})
        merged = merge_nat_update(stored, {"source_filter": {"filter_type": "ADDRESS_AND_PORT", "port": "53"}})
        assert merged["source_filter"]["firewall_group_ids"] == []
        assert merged["source_filter"]["port"] == "53"

    def test_selector_set_by_the_update_is_kept(self) -> None:
        update = {"destination_filter": {"filter_type": "FIREWALL_GROUPS", "firewall_group_ids": ["g1"], "port": "53"}}
        merged = merge_nat_update(dnat(), update)
        assert merged["destination_filter"]["port"] == "53"
        assert "address" not in merged["destination_filter"]

    def test_same_filter_type_retires_nothing(self) -> None:
        merged = merge_nat_update(dnat(), {"destination_filter": {"filter_type": "ADDRESS_AND_PORT", "port": "853"}})
        assert merged["destination_filter"]["address"] == "192.0.2.53"

    def test_switching_to_masquerade_drops_the_translation(self) -> None:
        merged = merge_nat_update(dnat(), {"type": "MASQUERADE", "out_interface": "wan"})
        assert "ip_address" not in merged
        assert "port" not in merged
        assert merged["in_interface"] == DNS_REDIRECT["in_interface"]

    def test_none_inside_a_filter_is_dropped(self) -> None:
        merged = merge_nat_update(dnat(), {"source_filter": {"address": None}})
        assert "address" not in merged["source_filter"]

    def test_non_dict_filter_in_the_update_replaces_the_stored_one(self) -> None:
        assert merge_nat_update(dnat(), {"source_filter": "x"})["source_filter"] == "x"


class TestUpdateError:
    def _error(self, stored, update):
        return nat_update_error(stored, merge_nat_update(stored, update))

    def test_reports_an_error_the_update_introduces(self) -> None:
        error = self._error(dnat(), {"port": "0"})
        assert error is not None and "'0'" in error

    def test_ignores_an_error_the_stored_rule_already_has(self) -> None:
        assert self._error(dnat(port="bogus"), {"enabled": False}) is None

    def test_reports_a_swapped_bad_value(self) -> None:
        error = self._error(dnat(port="bogus"), {"port": "worse"})
        assert error is not None and "'worse'" in error

    def test_validates_the_merged_filter(self) -> None:
        error = self._error(dnat(), {"destination_filter": {"filter_type": "NETWORK_CONF"}})
        assert error is not None and "network_conf_id" in error

    def test_retired_selectors_do_not_count_against_the_update(self) -> None:
        update = {"destination_filter": {"filter_type": "NETWORK_CONF", "network_conf_id": "n1"}}
        assert self._error(dnat(), update) is None

    def test_switching_away_from_a_stored_group_list_is_clean(self) -> None:
        stored = dnat(source_filter={**NONE_FILTER, "filter_type": "FIREWALL_GROUPS", "firewall_group_ids": ["g1"]})
        assert self._error(stored, {"source_filter": {"filter_type": "ADDRESS_AND_PORT", "port": "53"}}) is None

    def test_type_switch_to_masquerade_is_clean_after_retirement(self) -> None:
        assert self._error(dnat(), {"type": "MASQUERADE", "out_interface": "wan"}) is None


class TestReviewFindings:
    """Cases the review pass added; each names the production change that breaks it."""

    def test_unobserved_type_in_update_retires_nothing(self) -> None:
        merged = merge_nat_update(dnat(), {"type": "FUTURE"})
        assert merged["ip_address"] == "192.0.2.53" and merged["port"] == "53"

    def test_unobserved_filter_type_in_update_retires_nothing(self) -> None:
        stored = dnat(source_filter={**NONE_FILTER, "filter_type": "IID_AND_PORT", "port": "53"})
        merged = merge_nat_update(stored, {"source_filter": {"filter_type": "IID_AND_PORT", "invert_port": True}})
        assert merged["source_filter"]["port"] == "53"
        merged = merge_nat_update(dnat(), {"destination_filter": {"filter_type": "IID_AND_PORT"}})
        assert merged["destination_filter"]["address"] == "192.0.2.53"

    def test_none_inside_a_filter_is_dropped_without_a_stored_filter(self) -> None:
        stored = dnat()
        del stored["source_filter"]
        merged = merge_nat_update(stored, {"source_filter": {"filter_type": "NONE", "address": None}})
        assert merged["source_filter"] == {"filter_type": "NONE"}

    @pytest.mark.parametrize("port", ["٥٣", "５３"])
    def test_port_digits_must_be_ascii(self, port: str) -> None:
        assert nat_rule_error(dnat(port=port)) is not None
        assert nat_rule_error(dnat(source_filter={"filter_type": "ADDRESS_AND_PORT", "port": port})) is not None

    def test_dnat_requires_a_destination_filter_at_all(self) -> None:
        error = nat_rule_error(dnat(destination_filter=None))
        assert error is not None and "destination_filter" in error

    def test_rule_index_rejects_bool(self) -> None:
        error = nat_rule_error(dnat(rule_index=True))
        assert error is not None and "rule_index" in error

    def test_swapping_a_stale_translation_on_a_masquerade_is_reported(self) -> None:
        stored = {
            "type": "MASQUERADE",
            "out_interface": "wan-1",
            "port": "53",
            "source_filter": dict(NONE_FILTER),
            "destination_filter": dict(NONE_FILTER),
        }
        error = nat_update_error(stored, merge_nat_update(stored, {"port": "80"}))
        assert error is not None and "port" in error and "'MASQUERADE'" in error

    def test_swapping_a_stale_selector_under_none_is_reported(self) -> None:
        stored = dnat(source_filter={**NONE_FILTER, "address": "198.51.100.5"})
        merged = merge_nat_update(stored, {"source_filter": {"address": "203.0.113.0/24"}})
        error = nat_update_error(stored, merged)
        assert error is not None and "source_filter.address" in error

    def test_restating_a_stored_error_is_still_ignored(self) -> None:
        stored = dnat(source_filter={**NONE_FILTER, "address": "198.51.100.5"})
        merged = merge_nat_update(stored, {"enabled": False})
        assert nat_update_error(stored, merged) is None

    def test_clearing_a_required_key_is_reported(self) -> None:
        stored = dnat()
        del stored["in_interface"]
        merged = merge_nat_update(stored, {"in_interface": ""})
        error = nat_update_error(stored, merged)
        assert error is not None and "in_interface" in error

    @pytest.mark.parametrize("value", [["DNAT"], {"a": 1}, 7])
    def test_non_string_type_is_a_value_error_not_a_type_error(self, value) -> None:
        error = nat_rule_error(dnat(type=value))
        assert error is not None and "type" in error
        with pytest.raises(ValueError):
            normalize_nat_create(dnat(type=value))
        assert merge_nat_update(dnat(), {"type": value})["type"] == value
        with pytest.raises(ValueError):
            from_controller(dnat(type=value))

    def test_non_string_filter_type_is_a_value_error(self) -> None:
        bad = dnat(destination_filter={"filter_type": ["X"], "address": "192.0.2.1"})
        error = nat_rule_error(bad)
        assert error is not None and "destination_filter.filter_type" in error
        merged = merge_nat_update(dnat(), {"destination_filter": {"filter_type": ["X"]}})
        assert merged["destination_filter"]["filter_type"] == ["X"]

    @pytest.mark.parametrize(
        "fields", [{"enabled": "yes"}, {"rule_index": "3"}, {"description": {"a": 1}}, {"source_filter": "NONE"}]
    )
    def test_wrong_value_types_are_rejected_before_the_controller(self, fields) -> None:
        with pytest.raises(ValueError):
            normalize_nat_update(fields)

    def test_normalize_update_drops_none_inside_filters(self) -> None:
        out = normalize_nat_update({"source_filter": {"filter_type": "none", "address": None, "port": None}})
        assert out == {"source_filter": {"filter_type": "NONE"}}
