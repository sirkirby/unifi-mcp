"""Unit tests for the Network Wlan CRUD domain model."""

from __future__ import annotations

from unifi_core.network.models.wlans import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    Wlan,
    from_controller,
    to_controller_create,
    to_controller_update,
)


class TestFieldSets:
    def test_mutable_fields_contains_core_fields(self) -> None:
        for field in (
            "name",
            "security",
            "x_passphrase",
            "enabled",
            "hide_ssid",
            "guest_policy",
            "network_id",
            "vlan_id",
            "usergroup_id",
            "ap_group_ids",
            "ap_group_mode",
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
        all_fields = frozenset(Wlan.model_fields.keys())
        assert MUTABLE_FIELDS | READ_ONLY_FIELDS == all_fields


class TestFromController:
    def test_full_wlan(self) -> None:
        raw = {
            "_id": "wlan-1",
            "site_id": "site-a",
            "name": "HomeWiFi",
            "security": "wpa2-psk",
            "x_passphrase": "secret123",
            "enabled": True,
            "hide_ssid": False,
            "networkconf_id": "net-1",
            "vlan": 10,
            "usergroup_id": "_default_",
            "ap_group_ids": ["apg-1"],
            "mac_filter_enabled": False,
        }
        wlan = from_controller(raw)
        assert wlan.id == "wlan-1"
        assert wlan.site_id == "site-a"
        assert wlan.name == "HomeWiFi"
        assert wlan.security == "wpa2-psk"
        assert wlan.x_passphrase == "secret123"
        assert wlan.enabled is True
        assert wlan.hide_ssid is False
        assert wlan.network_id == "net-1"
        assert wlan.vlan_id == 10
        assert wlan.usergroup_id == "_default_"
        assert wlan.ap_group_ids == ["apg-1"]
        assert wlan.mac_filter_enabled is False

    def test_network_id_fallback(self) -> None:
        raw = {"_id": "wlan-2", "network_id": "net-2"}
        wlan = from_controller(raw)
        assert wlan.network_id == "net-2"

    def test_networkconf_id_takes_priority(self) -> None:
        raw = {"_id": "wlan-3", "networkconf_id": "primary", "network_id": "fallback"}
        wlan = from_controller(raw)
        assert wlan.network_id == "primary"

    def test_handles_empty_dict(self) -> None:
        wlan = from_controller({})
        assert wlan.id is None
        assert wlan.name is None
        assert wlan.enabled is None


class TestToControllerCreate:
    def test_maps_network_id_to_networkconf_id(self) -> None:
        model = Wlan(name="Test", security="open", network_id="net-1")
        payload = to_controller_create(model)
        assert payload["networkconf_id"] == "net-1"
        assert "network_id" not in payload

    def test_maps_vlan_id_to_vlan(self) -> None:
        model = Wlan(name="Test", security="open", vlan_id=20)
        payload = to_controller_create(model)
        assert payload["vlan"] == 20
        assert "vlan_id" not in payload

    def test_excludes_id_and_site_id(self) -> None:
        model = Wlan(id="should-not-appear", site_id="site", name="Test")
        payload = to_controller_create(model)
        assert "id" not in payload
        assert "site_id" not in payload

    def test_includes_passphrase(self) -> None:
        model = Wlan(name="Secure", security="wpa2-psk", x_passphrase="mysecret")
        payload = to_controller_create(model)
        assert payload["x_passphrase"] == "mysecret"

    def test_omits_none_fields(self) -> None:
        model = Wlan(name="Minimal", security="open")
        payload = to_controller_create(model)
        assert "hide_ssid" not in payload
        assert "guest_policy" not in payload


class TestToControllerUpdate:
    def test_maps_network_id_to_networkconf_id(self) -> None:
        result = to_controller_update({"network_id": "net-2"})
        assert "networkconf_id" in result
        assert result["networkconf_id"] == "net-2"
        assert "network_id" not in result

    def test_maps_vlan_id_to_vlan(self) -> None:
        result = to_controller_update({"vlan_id": 30})
        assert result["vlan"] == 30
        assert "vlan_id" not in result

    def test_filters_out_read_only_id(self) -> None:
        result = to_controller_update({"id": "ignore-me", "name": "New Name"})
        assert "id" not in result
        assert result["name"] == "New Name"

    def test_drops_none_values(self) -> None:
        result = to_controller_update({"name": None, "enabled": True})
        assert "name" not in result
        assert result["enabled"] is True

    def test_drops_unrecognised_keys(self) -> None:
        result = to_controller_update({"unknown": "value", "name": "Valid"})
        assert "unknown" not in result
        assert result["name"] == "Valid"

    def test_toggle_payload(self) -> None:
        result = to_controller_update({"enabled": False})
        assert result == {"enabled": False}
