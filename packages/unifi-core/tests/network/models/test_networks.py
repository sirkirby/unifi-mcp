"""Unit tests for the Network Network CRUD domain model."""

from __future__ import annotations

import pytest
from unifi_core.network.models.networks import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    Network,
    from_controller,
    is_hotspot_zone,
    to_controller_create,
    to_controller_update,
    to_guest_create_wire,
    validate_create,
    validate_guest_create_fields,
    validate_update,
    validate_wan_dns_state,
)

from .model_assertions import assert_fields


class TestFieldSets:
    def test_mdns_enabled_is_read_only(self) -> None:
        assert "mdns_enabled" in READ_ONLY_FIELDS
        assert "mdns_enabled" not in MUTABLE_FIELDS

    def test_to_controller_update_filters_mdns_enabled(self) -> None:
        result = to_controller_update({"mdns_enabled": False})
        assert result == {}, f"mdns_enabled should be filtered out, got: {result}"


class TestFromController:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (
                {
                    "_id": "net-1",
                    "site_id": "site-a",
                    "name": "LAN",
                    "purpose": "corporate",
                    "enabled": True,
                    "vlan_enabled": True,
                    "vlan": 10,
                    "ip_subnet": "192.168.10.1/24",
                    "dhcpd_enabled": True,
                    "dhcpd_start": "192.168.10.100",
                    "dhcpd_stop": "192.168.10.200",
                },
                {
                    "id": "net-1",
                    "site_id": "site-a",
                    "name": "LAN",
                    "purpose": "corporate",
                    "enabled": True,
                    "vlan_enabled": True,
                    "vlan": "10",
                    "ip_subnet": "192.168.10.1/24",
                    "dhcpd_enabled": True,
                    "dhcpd_start": "192.168.10.100",
                    "dhcpd_stop": "192.168.10.200",
                },
            ),
            ({"_id": "abc", "name": "Test"}, {"id": "abc"}),
            ({"id": "xyz", "name": "Test"}, {"id": "xyz"}),
            ({"_id": "n1", "vlan": 20}, {"vlan": "20"}),
            ({"_id": "n1"}, {"vlan": None}),
            ({}, {"id": None, "name": None, "enabled": None}),
            ({"_id": "n1", "igmp_snooping": True}, {"igmp_snooping": True}),
            ({"_id": "n1", "mdns_enabled": False}, {"mdns_enabled": False}),
            ({"_id": "n1", "network_isolation_enabled": True}, {"network_isolation_enabled": True}),
            (
                {
                    "_id": "wan-1",
                    "purpose": "wan",
                    "name": "Quantum",
                    "wan_networkgroup": "WAN",
                    "wan_type": "dhcp",
                    "wan_dns_preference": "auto",
                    "wan_dns1": "1.1.1.1",
                    "wan_dns2": "8.8.8.8",
                    "wan_load_balance_type": "weighted",
                    "wan_load_balance_weight": 99,
                    "wan_failover_priority": 1,
                    "wan_sla": "sla-1",
                    "report_wan_event": False,
                    "wan_smartq_enabled": False,
                    "wan_vlan_enabled": False,
                    "igmp_proxy_upstream": False,
                    "igmp_proxy_for": "none",
                    "mac_override_enabled": False,
                    "wan_ip_aliases": [],
                },
                {
                    "wan_networkgroup": "WAN",
                    "wan_type": "dhcp",
                    "wan_dns_preference": "auto",
                    "wan_dns1": "1.1.1.1",
                    "wan_dns2": "8.8.8.8",
                    "wan_load_balance_type": "weighted",
                    "wan_load_balance_weight": 99,
                    "wan_failover_priority": 1,
                    "wan_sla": "sla-1",
                    "report_wan_event": False,
                    "wan_smartq_enabled": False,
                    "wan_vlan_enabled": False,
                    "igmp_proxy_upstream": False,
                    "igmp_proxy_for": "none",
                    "mac_override_enabled": False,
                    "wan_ip_aliases": [],
                },
            ),
            (
                {"_id": "wan-1", "purpose": "wan", "igmp_proxy_for": ["net-a", "net-b"]},
                {"igmp_proxy_for": ["net-a", "net-b"]},
            ),
            (
                {
                    "_id": "wan-2",
                    "purpose": "wan",
                    "ipv6_enabled": True,
                    "wan_type_v6": "disabled",
                    "ipv6_setting_preference": "manual",
                    "ipv6_wan_delegation_type": "none",
                    "wan_dhcpv6_pd_size": 64,
                    "wan_dhcpv6_pd_size_auto": False,
                    "wan_ipv6_dns_preference": "auto",
                    "wan_ipv6_dns1": "",
                    "wan_ipv6_dns2": "",
                },
                {
                    "ipv6_enabled": True,
                    "wan_type_v6": "disabled",
                    "ipv6_setting_preference": "manual",
                    "ipv6_wan_delegation_type": "none",
                    "wan_dhcpv6_pd_size": 64,
                    "wan_dhcpv6_pd_size_auto": False,
                    "wan_ipv6_dns_preference": "auto",
                    "wan_ipv6_dns1": "",
                    "wan_ipv6_dns2": "",
                },
            ),
        ],
        ids=[
            "full_corporate_network",
            "id_coalesces_underscore_id",
            "id_coalesces_plain_id",
            "vlan_cast_to_string",
            "vlan_none_stays_none",
            "handles_empty_dict",
            "igmp_snooping_captured",
            "mdns_enabled_captured",
            "network_isolation_enabled_captured",
            "wan_fields_captured",
            "igmp_proxy_for_list_does_not_raise",
            "wan_ipv6_fields_captured",
        ],
    )
    def test_from_controller_fields(self, raw, expected) -> None:
        result = from_controller(raw)
        assert_fields(result, expected)


class TestStrictValidation:
    def test_update_rejects_mixed_read_only_field(self) -> None:
        with pytest.raises(ValueError, match="mdns_enabled"):
            validate_update({"enabled": False, "mdns_enabled": False})

    def test_update_rejects_unknown_and_malformed_values(self) -> None:
        with pytest.raises(ValueError, match="Unknown network field"):
            validate_update({"enabled": False, "unknown": True})
        with pytest.raises(ValueError, match="integer between 1 and 4094"):
            validate_update({"vlan": "bad"})
        with pytest.raises(ValueError, match="valid IPv4 or IPv6 CIDR"):
            validate_update({"ip_subnet": "bad"})

    @pytest.mark.parametrize("field_name", ["wan_dns1", "wan_dns2"])
    @pytest.mark.parametrize("value", ["dns.example.com", "2001:4860:4860::8888", "999.1.1.1"])
    def test_update_rejects_invalid_wan_ipv4_dns(self, field_name: str, value: str) -> None:
        with pytest.raises(ValueError, match="valid IPv4 address"):
            validate_update({field_name: value})

    def test_update_accepts_ipv4_wan_dns_and_empty_clear(self) -> None:
        assert validate_update({"wan_dns1": "1.1.1.1", "wan_dns2": ""}) == {
            "wan_dns1": "1.1.1.1",
            "wan_dns2": "",
        }

    def test_manual_wan_dns_requires_primary_resolver(self) -> None:
        with pytest.raises(ValueError, match="wan_dns1.*required"):
            validate_wan_dns_state(
                {"wan_dns_preference": "auto", "wan_dns1": ""},
                {"wan_dns_preference": "manual"},
            )

    def test_manual_wan_dns_accepts_submitted_or_stored_primary_resolver(self) -> None:
        validate_wan_dns_state(
            {"wan_dns_preference": "auto", "wan_dns1": ""},
            {"wan_dns_preference": "manual", "wan_dns1": "1.1.1.1"},
        )
        validate_wan_dns_state(
            {"wan_dns_preference": "auto", "wan_dns1": "8.8.8.8"},
            {"wan_dns_preference": "manual"},
        )

    @pytest.mark.parametrize("stored_primary", ["dns.example.com", "2001:4860:4860::8888", "999.1.1.1"])
    def test_manual_wan_dns_rejects_invalid_stored_primary_resolver(self, stored_primary: str) -> None:
        with pytest.raises(ValueError, match="effective 'wan_dns1'.*valid IPv4"):
            validate_wan_dns_state(
                {"wan_dns_preference": "auto", "wan_dns1": stored_primary},
                {"wan_dns_preference": "manual"},
            )

    def test_unrelated_update_does_not_reject_existing_manual_dns_state(self) -> None:
        validate_wan_dns_state(
            {"wan_dns_preference": "manual", "wan_dns1": ""},
            {"name": "Renamed WAN"},
        )

    @pytest.mark.parametrize("value", [True, False, 1.5, 99.9])
    def test_update_rejects_lossy_wan_load_balance_weight(self, value: object) -> None:
        with pytest.raises(ValueError, match="must be an integer"):
            validate_update({"wan_load_balance_weight": value})

    @pytest.mark.parametrize("value", [-1, 101, 500])
    def test_update_rejects_out_of_range_wan_load_balance_weight(self, value: int) -> None:
        with pytest.raises(ValueError, match="between 0 and 100"):
            validate_update({"wan_load_balance_weight": value})

    @pytest.mark.parametrize("value", [-1, 150])
    def test_read_path_tolerates_out_of_range_wan_load_balance_weight(self, value: int) -> None:
        # The shared model also parses controller reads; a legacy out-of-range
        # weight on one row must not break whole-site listings.
        n = from_controller({"_id": "n1", "name": "WAN", "wan_load_balance_weight": value})
        assert n.wan_load_balance_weight == value

    def test_update_accepts_real_controller_fields_missing_from_early_allowlist(self) -> None:
        # Real networkconf fields that REST callers wrote successfully before
        # strict validation; the allowlist must keep a write path for them.
        assert validate_update({"ipv6_ra_enabled": False}) == {"ipv6_ra_enabled": False}
        assert validate_update({"auto_scale_enabled": True}) == {"auto_scale_enabled": True}

    def test_update_accepts_firewall_zone_and_wan_monitor_fields(self) -> None:
        assert validate_update(
            {
                "firewall_zone_id": "zone-v2-1",
                "wan_sla": "sla-1",
                "report_wan_event": False,
            }
        ) == {
            "firewall_zone_id": "zone-v2-1",
            "wan_sla": "sla-1",
            "report_wan_event": False,
        }

    def test_update_normalizes_string_vlan_to_controller_int(self) -> None:
        # Callers may send vlan as a string (the documented tool format); the
        # payload is normalized to the controller-native int so exact
        # verification does not misread the echoed int as a coercion.
        assert validate_update({"vlan": "100"}) == {"vlan": 100}

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("wan_vlan_enabled", "yes"),
            ("wan_smartq_enabled", "false"),
            ("wan_failover_priority", 1.0),
            ("vlan", True),
        ],
    )
    def test_update_rejects_type_coercion(self, field: str, value: object) -> None:
        with pytest.raises(ValueError):
            validate_update({field: value})

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("wan_type", "automatic"),
            ("wan_networkgroup", "LAN"),
            ("wan_load_balance_type", "round-robin"),
            ("wan_type_v6", "automatic"),
            ("ipv6_wan_delegation_type", "dhcpv6"),
            ("ipv6_interface_type", "automatic"),
            ("ipv6_ra_priority", "urgent"),
            ("ipv6_client_address_assignment", "automatic"),
        ],
    )
    def test_update_rejects_unknown_enum_values(self, field: str, value: str) -> None:
        with pytest.raises(ValueError, match=f"Invalid '{field}'"):
            validate_update({field: value})

    @pytest.mark.parametrize("value", ["none", "pd", "single_network", "static"])
    def test_update_accepts_ipv6_wan_delegation_types(self, value: str) -> None:
        assert validate_update({"ipv6_wan_delegation_type": value}) == {"ipv6_wan_delegation_type": value}

    def test_create_enforces_cross_field_requirements_and_preserves_integer_vlan(self) -> None:
        assert validate_create({"name": "Lab", "purpose": "vlan-only", "vlan": 4092}) == {
            "name": "Lab",
            "purpose": "vlan-only",
            "vlan": 4092,
            "enabled": True,
        }
        with pytest.raises(ValueError, match="dhcpd_start"):
            validate_create({"name": "LAN", "purpose": "corporate", "ip_subnet": "10.0.0.1/24"})

    def test_create_rejects_manual_wan_dns_without_primary(self) -> None:
        with pytest.raises(ValueError, match="wan_dns1.*required"):
            validate_create(
                {
                    "name": "WAN",
                    "purpose": "wan",
                    "ip_subnet": "192.0.2.2/24",
                    "dhcpd_enabled": False,
                    "wan_dns_preference": "manual",
                }
            )


class TestToControllerCreate:
    def test_full_model(self) -> None:
        model = Network(
            name="IoT",
            purpose="corporate",
            vlan_enabled=True,
            vlan="20",
            ip_subnet="10.20.0.1/24",
            dhcpd_enabled=True,
            dhcpd_start="10.20.0.100",
            dhcpd_stop="10.20.0.200",
        )
        payload = to_controller_create(model)
        assert payload["name"] == "IoT"
        assert payload["purpose"] == "corporate"
        assert payload["vlan_enabled"] is True
        assert payload["vlan"] == "20"
        assert payload["ip_subnet"] == "10.20.0.1/24"


class TestToControllerUpdate:
    @pytest.mark.parametrize(
        "fields, expected, absent, present",
        [
            ({"id": "ignore-me", "name": "New Name"}, {"name": "New Name"}, ("id",), ()),
            ({"site_id": "ignore", "name": "Test"}, {}, ("site_id",), ()),
            ({"name": None, "dhcpd_enabled": True}, {"dhcpd_enabled": True}, ("name",), ()),
            ({"enabled": True, "name": "Test"}, {"enabled": True}, (), ()),
            ({"unknown_key": "value", "name": "Valid"}, {"name": "Valid"}, ("unknown_key",), ()),
            (
                {"dhcpd_start": "10.0.0.100", "dhcpd_stop": "10.0.0.200", "dhcpd_leasetime": 86400},
                {"dhcpd_start": "10.0.0.100", "dhcpd_stop": "10.0.0.200", "dhcpd_leasetime": 86400},
                (),
                (),
            ),
            (
                {
                    "wan_type": "dhcp",
                    "wan_dns1": "1.1.1.1",
                    "wan_dns2": "8.8.8.8",
                    "wan_load_balance_weight": 50,
                    "igmp_proxy_for": "none",
                },
                {
                    "wan_type": "dhcp",
                    "wan_dns1": "1.1.1.1",
                    "wan_dns2": "8.8.8.8",
                    "wan_load_balance_weight": 50,
                    "igmp_proxy_for": "none",
                },
                (),
                (),
            ),
            (
                {"wan_smartq_enabled": False, "wan_vlan_enabled": False},
                {"wan_smartq_enabled": False, "wan_vlan_enabled": False},
                (),
                (),
            ),
            (
                {
                    "ipv6_enabled": True,
                    "wan_type_v6": "dhcpv6",
                    "wan_dhcpv6_pd_size": 56,
                    "wan_dhcpv6_pd_size_auto": False,
                    "wan_ipv6_dns1": "2001:4860:4860::8888",
                    "wan_ipv6_dns2": None,
                },
                {
                    "ipv6_enabled": True,
                    "wan_type_v6": "dhcpv6",
                    "wan_dhcpv6_pd_size": 56,
                    "wan_dhcpv6_pd_size_auto": False,
                    "wan_ipv6_dns1": "2001:4860:4860::8888",
                },
                ("wan_ipv6_dns2",),
                (),
            ),
        ],
        ids=[
            "filters_out_read_only_id",
            "filters_out_site_id",
            "drops_none_values",
            "passes_boolean_false",
            "drops_unrecognised_keys",
            "dhcp_fields_passthrough",
            "wan_fields_passthrough",
            "wan_bool_false_preserved",
            "wan_ipv6_fields_passthrough",
        ],
    )
    def test_to_controller_update_payload(self, fields, expected, absent, present) -> None:
        result = to_controller_update(fields)
        assert_fields(result, expected)
        for key in absent:
            assert key not in result
        for key in present:
            assert key in result


class TestLanIpv6Fields:
    """Per-LAN IPv6 settings.

    The model previously carried only WAN-scoped IPv6 fields, so every
    LAN-side key was rejected as unknown even though get_network_details
    returns all of them — dual-stack LAN work was unreachable through the tool.
    """

    LAN_IPV6_FIELDS = (
        "ipv6_interface_type",
        "ipv6_aliases",
        "ipv6_ra_priority",
        "ipv6_ra_preferred_lifetime",
        "ipv6_client_address_assignment",
        "ipv6_pd_interface",
        "ipv6_pd_prefixid",
        "ipv6_pd_auto_prefixid_enabled",
        "ipv6_pd_start",
        "ipv6_pd_stop",
        "dhcpdv6_enabled",
        "dhcpdv6_allow_slaac",
        "dhcpdv6_dns_auto",
        "dhcpdv6_leasetime",
        "dhcpdv6_start",
        "dhcpdv6_stop",
    )

    def test_lan_ipv6_fields_are_mutable(self) -> None:
        for field in self.LAN_IPV6_FIELDS:
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_from_controller_reads_lan_ipv6_fields(self) -> None:
        network = from_controller(
            {
                "_id": "net-v6",
                "ipv6_interface_type": "pd",
                "ipv6_aliases": ["fd00:0:0:50::1/64"],
                "ipv6_ra_priority": "high",
                "ipv6_ra_preferred_lifetime": 14400,
                "ipv6_client_address_assignment": "slaac",
                "ipv6_pd_interface": "wan",
                "ipv6_pd_auto_prefixid_enabled": True,
                "ipv6_pd_start": "::2",
                "ipv6_pd_stop": "::7d1",
                "dhcpdv6_allow_slaac": True,
                "dhcpdv6_dns_auto": True,
                "dhcpdv6_leasetime": 86400,
                "dhcpdv6_start": "::2",
                "dhcpdv6_stop": "::7d1",
            }
        )
        assert network.ipv6_interface_type == "pd"
        assert network.ipv6_aliases == ["fd00:0:0:50::1/64"]
        assert network.ipv6_ra_priority == "high"
        assert network.ipv6_ra_preferred_lifetime == 14400
        assert network.ipv6_client_address_assignment == "slaac"
        assert network.ipv6_pd_interface == "wan"
        assert network.ipv6_pd_auto_prefixid_enabled is True
        assert network.ipv6_pd_start == "::2"
        assert network.ipv6_pd_stop == "::7d1"
        assert network.dhcpdv6_allow_slaac is True
        assert network.dhcpdv6_dns_auto is True
        assert network.dhcpdv6_leasetime == 86400
        assert network.dhcpdv6_start == "::2"
        assert network.dhcpdv6_stop == "::7d1"

    def test_ipv6_aliases_survives_update_filter(self) -> None:
        """The reproducer from the bug report: a single ipv6_aliases write."""
        assert to_controller_update({"ipv6_aliases": ["fd00:0:0:50::1/64"]}) == {"ipv6_aliases": ["fd00:0:0:50::1/64"]}

    def test_validate_update_accepts_ipv6_aliases(self) -> None:
        """The public validator no longer rejects it as an unknown field."""
        assert validate_update({"ipv6_aliases": ["fd00:0:0:50::1/64"]}) == {"ipv6_aliases": ["fd00:0:0:50::1/64"]}

    def test_lan_ipv6_bool_false_preserved(self) -> None:
        result = to_controller_update({"ipv6_pd_auto_prefixid_enabled": False, "dhcpdv6_enabled": False})
        assert result["ipv6_pd_auto_prefixid_enabled"] is False
        assert result["dhcpdv6_enabled"] is False

    def test_numeric_prefixid_is_coerced_to_string(self) -> None:
        """`vlan` is coerced the same way; without it one numeric value fails
        model validation for the whole site listing."""
        assert from_controller({"_id": "n", "ipv6_pd_prefixid": 50}).ipv6_pd_prefixid == "50"

    def test_absent_prefixid_stays_none(self) -> None:
        assert from_controller({"_id": "n"}).ipv6_pd_prefixid is None


def _guest_create(**overrides: object) -> dict:
    fields: dict = {
        "name": "Visitors",
        "purpose": "guest",
        "firewall_zone_id": "hotspot-zone",
        "vlan_enabled": True,
        "vlan": 3900,
        "ip_subnet": "192.0.2.1/29",
        "dhcpd_enabled": False,
        "network_isolation_enabled": False,
    }
    fields.update(overrides)
    return fields


class TestGuestCreate:
    def test_create_accepts_explicit_guest_with_zone(self) -> None:
        payload = validate_create(_guest_create())
        assert payload["purpose"] == "guest"
        assert payload["firewall_zone_id"] == "hotspot-zone"
        assert payload["network_isolation_enabled"] is False

    @pytest.mark.parametrize("zone", [None, "", "   "])
    def test_create_rejects_guest_without_zone(self, zone: object) -> None:
        fields = _guest_create()
        if zone is None:
            del fields["firewall_zone_id"]
        else:
            fields["firewall_zone_id"] = zone
        with pytest.raises(ValueError, match="Internal firewall zone"):
            validate_create(fields)

    def test_create_reports_missing_hotspot_zone_before_other_requirements(self) -> None:
        with pytest.raises(ValueError, match="Internal firewall zone"):
            validate_create({"name": "Guest", "purpose": "guest"})

    def test_create_rejects_guest_with_network_isolation(self) -> None:
        with pytest.raises(ValueError, match="network_isolation_enabled"):
            validate_create(_guest_create(network_isolation_enabled=True))

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("gateway_type", "switch"),
            ("sdwan_underlay", True),
            ("l3_interface_type", "vlan"),
        ],
    )
    def test_create_rejects_switch_and_sdwan_fields(self, field: str, value: object) -> None:
        with pytest.raises(ValueError, match="Unknown network field"):
            validate_create(_guest_create(**{field: value}))

    def test_update_still_rejects_guest_purpose(self) -> None:
        with pytest.raises(ValueError, match="Hotspot zone"):
            validate_update({"purpose": "guest"})
        with pytest.raises(ValueError, match="Hotspot zone"):
            validate_update({"purpose": "guest", "firewall_zone_id": "hotspot-zone"})

    def test_corporate_create_is_unchanged(self) -> None:
        payload = validate_create(_guest_create(purpose="corporate"))
        assert payload["purpose"] == "corporate"


class TestGuestCreateFields:
    """Raw-dict checks shared by the model and direct manager callers."""

    def test_accepts_supported_shape_with_neutral_values(self) -> None:
        validate_guest_create_fields(
            _guest_create(gateway_type="default", gateway_device="", sdwan_underlay=False, sdwan_remote_site_id="")
        )

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("gateway_type", "switch"),
            ("gateway_device", "aa:bb:cc:dd:ee:ff"),
            ("l3_interface_type", "vlan"),
            ("sdwan_underlay", True),
            ("sdwan_remote_site_id", "remote-site"),
        ],
    )
    def test_rejects_switch_l3_and_sdwan_inputs(self, field: str, value: object) -> None:
        with pytest.raises(ValueError, match=field):
            validate_guest_create_fields(_guest_create(**{field: value}))

    @pytest.mark.parametrize("value", [True, 1, "true", "false", 0, "", [], {}])
    def test_rejects_isolation_unless_absent_none_or_strict_false(self, value: object) -> None:
        with pytest.raises(ValueError, match="network_isolation_enabled"):
            validate_guest_create_fields(_guest_create(network_isolation_enabled=value))

    @pytest.mark.parametrize("value", [None, False])
    def test_accepts_isolation_none_or_strict_false(self, value: object) -> None:
        validate_guest_create_fields(_guest_create(network_isolation_enabled=value))

    def test_accepts_absent_isolation(self) -> None:
        fields = _guest_create()
        del fields["network_isolation_enabled"]
        validate_guest_create_fields(fields)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("sdwan_underlay", 0),
            ("sdwan_underlay", 1),
            ("sdwan_underlay", "false"),
            ("gateway_type", "DEFAULT"),
        ],
    )
    def test_neutral_values_match_strictly(self, field: str, value: object) -> None:
        with pytest.raises(ValueError, match=field):
            validate_guest_create_fields(_guest_create(**{field: value}))

    @pytest.mark.parametrize("zone", [" hotspot-zone", "hotspot-zone ", "\thotspot-zone\n"])
    def test_rejects_zone_id_with_surrounding_whitespace(self, zone: str) -> None:
        with pytest.raises(ValueError, match="whitespace"):
            validate_guest_create_fields(_guest_create(firewall_zone_id=zone))
        with pytest.raises(ValueError, match="whitespace"):
            validate_create(_guest_create(firewall_zone_id=zone))

    @pytest.mark.parametrize("zone", [None, "", 123])
    def test_rejects_missing_or_non_string_zone(self, zone: object) -> None:
        with pytest.raises(ValueError, match="Hotspot zone"):
            validate_guest_create_fields(_guest_create(firewall_zone_id=zone))


class TestHotspotZone:
    def test_matches_canonical_zone_key(self) -> None:
        assert is_hotspot_zone({"_id": "z", "zone_key": "hotspot", "name": "Guests"}) is True

    @pytest.mark.parametrize(
        "zone",
        [
            {"_id": "z", "name": "Hotspot", "zone_key": "internal"},
            {"_id": "z", "name": "Hotspot", "default_zone": True},
            {"_id": "z", "zone_key": "Hotspot "},
            {"_id": "z", "zone_key": None},
        ],
    )
    def test_rejects_name_only_or_non_canonical_keys(self, zone: dict) -> None:
        assert is_hotspot_zone(zone) is False


class TestGuestCreateWire:
    def test_translates_to_ui_wire_purpose_without_mutating_input(self) -> None:
        requested = _guest_create(networkgroup="LAN")
        original = dict(requested)

        wire = to_guest_create_wire(requested)

        assert wire == {**original, "purpose": "corporate"}
        assert requested == original
        assert wire is not requested

    def test_rejects_non_guest_input(self) -> None:
        with pytest.raises(ValueError, match="guest"):
            to_guest_create_wire(_guest_create(purpose="corporate"))
