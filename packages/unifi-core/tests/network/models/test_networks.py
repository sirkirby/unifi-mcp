"""Unit tests for the Network Network CRUD domain model."""

from __future__ import annotations

from unifi_core.network.models.networks import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    Network,
    from_controller,
    to_controller_create,
    to_controller_update,
)


class TestFieldSets:
    def test_mutable_fields_contains_core_fields(self) -> None:
        for field in ("name", "purpose", "enabled", "vlan_enabled", "vlan", "ip_subnet"):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mutable_fields_contains_dhcp_fields(self) -> None:
        for field in ("dhcpd_enabled", "dhcpd_start", "dhcpd_stop", "dhcpd_leasetime"):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mutable_fields_contains_multicast_fields(self) -> None:
        for field in ("igmp_snooping", "mdns_enabled", "igmp_flood_unknown_multicast"):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

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
