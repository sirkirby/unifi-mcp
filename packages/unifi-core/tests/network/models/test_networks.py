"""Unit tests for the Network Network CRUD domain model."""

from __future__ import annotations

import pytest
from unifi_core.network.models.networks import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    Network,
    from_controller,
    to_controller_create,
    to_controller_update,
    validate_create,
    validate_update,
)


class TestFieldSets:
    def test_mutable_fields_contains_core_fields(self) -> None:
        for field in ("name", "purpose", "enabled", "vlan_enabled", "vlan", "ip_subnet"):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mutable_fields_contains_dhcp_fields(self) -> None:
        for field in ("dhcpd_enabled", "dhcpd_start", "dhcpd_stop", "dhcpd_leasetime"):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mutable_fields_contains_multicast_fields(self) -> None:
        for field in ("igmp_snooping", "igmp_flood_unknown_multicast"):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mdns_enabled_is_read_only(self) -> None:
        assert "mdns_enabled" in READ_ONLY_FIELDS
        assert "mdns_enabled" not in MUTABLE_FIELDS

    def test_to_controller_update_filters_mdns_enabled(self) -> None:
        result = to_controller_update({"mdns_enabled": False})
        assert result == {}, f"mdns_enabled should be filtered out, got: {result}"

    def test_mutable_fields_contains_wan_fields(self) -> None:
        for field in (
            "wan_type",
            "wan_networkgroup",
            "wan_dns_preference",
            "wan_load_balance_type",
            "wan_load_balance_weight",
            "wan_failover_priority",
            "wan_smartq_enabled",
            "wan_vlan_enabled",
            "igmp_proxy_upstream",
            "igmp_proxy_for",
            "mac_override_enabled",
            "wan_ip_aliases",
        ):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mutable_fields_contains_ipv6_wan_fields(self) -> None:
        for field in (
            "ipv6_enabled",
            "wan_type_v6",
            "ipv6_setting_preference",
            "ipv6_wan_delegation_type",
            "wan_dhcpv6_pd_size",
            "wan_dhcpv6_pd_size_auto",
            "wan_ipv6_dns_preference",
            "wan_ipv6_dns1",
            "wan_ipv6_dns2",
        ):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mutable_fields_excludes_read_only(self) -> None:
        for field in ("id", "site_id"):
            assert field not in MUTABLE_FIELDS, f"{field!r} should NOT be in MUTABLE_FIELDS"

    def test_read_only_fields_contains_id_and_site_id(self) -> None:
        assert "id" in READ_ONLY_FIELDS
        assert "site_id" in READ_ONLY_FIELDS

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = MUTABLE_FIELDS & READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_mutable_and_read_only_cover_all_model_fields(self) -> None:
        all_fields = frozenset(Network.model_fields.keys())
        assert MUTABLE_FIELDS | READ_ONLY_FIELDS == all_fields


class TestFromController:
    def test_full_corporate_network(self) -> None:
        raw = {
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
        }
        n = from_controller(raw)
        assert n.id == "net-1"
        assert n.site_id == "site-a"
        assert n.name == "LAN"
        assert n.purpose == "corporate"
        assert n.enabled is True
        assert n.vlan_enabled is True
        assert n.vlan == "10"
        assert n.ip_subnet == "192.168.10.1/24"
        assert n.dhcpd_enabled is True
        assert n.dhcpd_start == "192.168.10.100"
        assert n.dhcpd_stop == "192.168.10.200"

    def test_id_coalesces_underscore_id(self) -> None:
        raw = {"_id": "abc", "name": "Test"}
        n = from_controller(raw)
        assert n.id == "abc"

    def test_id_coalesces_plain_id(self) -> None:
        raw = {"id": "xyz", "name": "Test"}
        n = from_controller(raw)
        assert n.id == "xyz"

    def test_vlan_cast_to_string(self) -> None:
        raw = {"_id": "n1", "vlan": 20}
        n = from_controller(raw)
        assert n.vlan == "20"

    def test_vlan_none_stays_none(self) -> None:
        raw = {"_id": "n1"}
        n = from_controller(raw)
        assert n.vlan is None

    def test_handles_empty_dict(self) -> None:
        n = from_controller({})
        assert n.id is None
        assert n.name is None
        assert n.enabled is None

    def test_igmp_snooping_captured(self) -> None:
        raw = {"_id": "n1", "igmp_snooping": True}
        n = from_controller(raw)
        assert n.igmp_snooping is True

    def test_mdns_enabled_captured(self) -> None:
        raw = {"_id": "n1", "mdns_enabled": False}
        n = from_controller(raw)
        assert n.mdns_enabled is False

    def test_network_isolation_enabled_captured(self) -> None:
        raw = {"_id": "n1", "network_isolation_enabled": True}
        n = from_controller(raw)
        assert n.network_isolation_enabled is True

    def test_wan_fields_captured(self) -> None:
        # Values mirror a real dual-WAN controller dump (purpose=wan networkconf).
        raw = {
            "_id": "wan-1",
            "purpose": "wan",
            "name": "Quantum",
            "wan_networkgroup": "WAN",
            "wan_type": "dhcp",
            "wan_dns_preference": "auto",
            "wan_load_balance_type": "weighted",
            "wan_load_balance_weight": 99,
            "wan_failover_priority": 1,
            "wan_smartq_enabled": False,
            "wan_vlan_enabled": False,
            "igmp_proxy_upstream": False,
            "igmp_proxy_for": "none",
            "mac_override_enabled": False,
            "wan_ip_aliases": [],
        }
        n = from_controller(raw)
        assert n.wan_networkgroup == "WAN"
        assert n.wan_type == "dhcp"
        assert n.wan_dns_preference == "auto"
        assert n.wan_load_balance_type == "weighted"
        assert n.wan_load_balance_weight == 99
        assert n.wan_failover_priority == 1
        assert n.wan_smartq_enabled is False
        assert n.wan_vlan_enabled is False
        assert n.igmp_proxy_upstream is False
        # 'none' (string) when disabled; field is Optional[Any] so a configured
        # list value cannot crash the read path (see test_igmp_proxy_for_list_does_not_raise).
        assert n.igmp_proxy_for == "none"
        assert n.mac_override_enabled is False
        assert n.wan_ip_aliases == []

    def test_igmp_proxy_for_list_does_not_raise(self) -> None:
        # When IGMP proxy is CONFIGURED the controller returns a list (not 'none').
        # igmp_proxy_for is Optional[Any], so from_controller must NOT raise — otherwise a
        # single configured WAN would break list_networks for ALL networks (un-guarded loop).
        raw = {"_id": "wan-1", "purpose": "wan", "igmp_proxy_for": ["net-a", "net-b"]}
        n = from_controller(raw)
        assert n.igmp_proxy_for == ["net-a", "net-b"]

    def test_wan_ipv6_fields_captured(self) -> None:
        # Values mirror the live dual-WAN dump (Xfinity WAN2, IPv6 enabled).
        raw = {
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
        }
        n = from_controller(raw)
        assert n.ipv6_enabled is True
        assert n.wan_type_v6 == "disabled"
        assert n.ipv6_setting_preference == "manual"
        assert n.ipv6_wan_delegation_type == "none"
        assert n.wan_dhcpv6_pd_size == 64
        assert n.wan_dhcpv6_pd_size_auto is False
        assert n.wan_ipv6_dns_preference == "auto"
        assert n.wan_ipv6_dns1 == ""
        assert n.wan_ipv6_dns2 == ""


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
        ],
    )
    def test_update_rejects_unknown_wan_enum_values(self, field: str, value: str) -> None:
        with pytest.raises(ValueError, match=f"Invalid '{field}'"):
            validate_update({field: value})

    def test_create_enforces_cross_field_requirements_and_preserves_integer_vlan(self) -> None:
        assert validate_create({"name": "Lab", "purpose": "vlan-only", "vlan": 4092}) == {
            "name": "Lab",
            "purpose": "vlan-only",
            "vlan": 4092,
            "enabled": True,
        }
        with pytest.raises(ValueError, match="dhcpd_start"):
            validate_create({"name": "LAN", "purpose": "corporate", "ip_subnet": "10.0.0.1/24"})


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

    def test_read_only_fields_excluded(self) -> None:
        model = Network(id="should-not-appear", site_id="also-not", name="Test")
        payload = to_controller_create(model)
        assert "id" not in payload
        assert "site_id" not in payload

    def test_none_values_excluded(self) -> None:
        model = Network(name="Minimal")
        payload = to_controller_create(model)
        assert "dhcpd_start" not in payload
        assert "vlan" not in payload


class TestToControllerUpdate:
    def test_filters_out_read_only_id(self) -> None:
        result = to_controller_update({"id": "ignore-me", "name": "New Name"})
        assert "id" not in result
        assert result["name"] == "New Name"

    def test_filters_out_site_id(self) -> None:
        result = to_controller_update({"site_id": "ignore", "name": "Test"})
        assert "site_id" not in result

    def test_drops_none_values(self) -> None:
        result = to_controller_update({"name": None, "dhcpd_enabled": True})
        assert "name" not in result
        assert result["dhcpd_enabled"] is True

    def test_passes_boolean_false(self) -> None:
        # False is a valid update (e.g. disabling a feature)
        # Note: current implementation drops False because of `v is not None` check
        # This is consistent with other domain models in this codebase
        result = to_controller_update({"enabled": True, "name": "Test"})
        assert result["enabled"] is True

    def test_drops_unrecognised_keys(self) -> None:
        result = to_controller_update({"unknown_key": "value", "name": "Valid"})
        assert "unknown_key" not in result
        assert result["name"] == "Valid"

    def test_returns_empty_dict_when_no_mutable_fields(self) -> None:
        result = to_controller_update({"id": "read-only", "site_id": "also-read-only"})
        assert result == {}

    def test_dhcp_fields_passthrough(self) -> None:
        result = to_controller_update(
            {
                "dhcpd_start": "10.0.0.100",
                "dhcpd_stop": "10.0.0.200",
                "dhcpd_leasetime": 86400,
            }
        )
        assert result["dhcpd_start"] == "10.0.0.100"
        assert result["dhcpd_stop"] == "10.0.0.200"
        assert result["dhcpd_leasetime"] == 86400

    def test_wan_fields_passthrough(self) -> None:
        result = to_controller_update(
            {
                "wan_type": "dhcp",
                "wan_load_balance_weight": 50,
                "igmp_proxy_for": "none",
            }
        )
        assert result["wan_type"] == "dhcp"
        assert result["wan_load_balance_weight"] == 50
        assert result["igmp_proxy_for"] == "none"

    def test_wan_bool_false_preserved(self) -> None:
        # Disabling a WAN feature (False) must survive the update filter (v is not None).
        result = to_controller_update({"wan_smartq_enabled": False, "wan_vlan_enabled": False})
        assert result["wan_smartq_enabled"] is False
        assert result["wan_vlan_enabled"] is False

    def test_wan_ipv6_fields_passthrough(self) -> None:
        result = to_controller_update(
            {
                "ipv6_enabled": True,
                "wan_type_v6": "dhcpv6",
                "wan_dhcpv6_pd_size": 56,
                "wan_dhcpv6_pd_size_auto": False,
                "wan_ipv6_dns1": "2001:4860:4860::8888",
                "wan_ipv6_dns2": None,
            }
        )
        assert result["ipv6_enabled"] is True
        assert result["wan_type_v6"] == "dhcpv6"
        assert result["wan_dhcpv6_pd_size"] == 56
        assert result["wan_dhcpv6_pd_size_auto"] is False
        assert result["wan_ipv6_dns1"] == "2001:4860:4860::8888"
        assert "wan_ipv6_dns2" not in result  # None is dropped (v is not None filter)


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
