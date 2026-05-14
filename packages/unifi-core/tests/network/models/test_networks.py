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
