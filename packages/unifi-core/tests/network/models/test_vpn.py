"""Unit tests for the Network VpnClient + VpnServer CRUD domain models."""

from __future__ import annotations

import pytest
from unifi_core.network.models.vpn import (
    VPNSERVER_MUTABLE_FIELDS,
    VPNSERVER_READ_ONLY_FIELDS,
    VpnClient,
    VpnServer,
    from_controller,
    is_vpn_network,
    to_controller_create,
    to_controller_update,
    vpn_server_from_controller,
)

from .model_assertions import assert_fields


class TestVpnClassification:
    def test_recognizes_all_networkconf_vpn_purposes(self) -> None:
        for purpose in ("site-vpn", "remote-user-vpn", "vpn-client", "vpn-server"):
            assert is_vpn_network({"purpose": purpose}) is True

    def test_recognizes_vpn_type_fallbacks(self) -> None:
        assert is_vpn_network({"purpose": "corporate", "vpn_type": "wireguard-client"}) is True
        assert is_vpn_network({"purpose": "corporate", "vpn_type": "openvpn-server"}) is True

    def test_rejects_non_vpn_network(self) -> None:
        assert is_vpn_network({"purpose": "corporate"}) is False


class TestVpnServerFieldSets:
    def test_server_has_only_alternate_address_mutable_fields(self) -> None:
        assert VPNSERVER_MUTABLE_FIELDS == frozenset({"alternate_address_enabled", "alternate_address"})

    def test_remaining_server_fields_are_read_only(self) -> None:
        all_fields = frozenset(VpnServer.model_fields.keys())
        assert VPNSERVER_READ_ONLY_FIELDS == all_fields - VPNSERVER_MUTABLE_FIELDS


class TestFromControllerVpnClient:
    def test_wireguard_client(self) -> None:
        raw = {
            "_id": "vpn-c-1",
            "name": "WireGuard Home",
            "vpn_type": "wireguard-client",
            "enabled": True,
            "wireguard_client_peer_endpoint": "vpn.example.com:51820",
        }
        client = from_controller(raw)
        assert client.id == "vpn-c-1"
        assert client.name == "WireGuard Home"
        assert client.type == "wireguard-client"
        assert client.enabled is True
        assert client.server_address == "vpn.example.com:51820"

    def test_purpose_fallback_for_type(self) -> None:
        raw = {"_id": "vpn-c-2", "purpose": "vpn-client"}
        client = from_controller(raw)
        assert client.type == "vpn-client"

    def test_openvpn_server_address(self) -> None:
        raw = {"_id": "vpn-c-3", "openvpn_remote_host": "openvpn.example.com"}
        client = from_controller(raw)
        assert client.server_address == "openvpn.example.com"

    def test_handles_empty_dict(self) -> None:
        client = from_controller({})
        assert client.id is None
        assert client.name is None
        assert client.enabled is None


class TestVpnServerFromController:
    def test_wireguard_server(self) -> None:
        raw = {
            "_id": "vpn-s-1",
            "name": "WireGuard Server",
            "vpn_type": "wireguard-server",
            "enabled": True,
            "wireguard_server_listen_port": 51820,
            "wireguard_server_subnet": "10.8.0.0/24",
        }
        server = vpn_server_from_controller(raw)
        assert server.id == "vpn-s-1"
        assert server.name == "WireGuard Server"
        assert server.type == "wireguard-server"
        assert server.enabled is True
        assert server.listen_port == 51820
        assert server.allowed_subnets == ["10.8.0.0/24"]

    def test_allowed_subnets_as_list(self) -> None:
        raw = {"_id": "vpn-s-2", "allowed_subnets": ["10.8.0.0/24", "10.9.0.0/24"]}
        server = vpn_server_from_controller(raw)
        assert server.allowed_subnets == ["10.8.0.0/24", "10.9.0.0/24"]

    def test_handles_empty_dict(self) -> None:
        server = vpn_server_from_controller({})
        assert server.id is None
        assert server.listen_port is None
        assert server.allowed_subnets is None


class TestToControllerCreate:
    def test_maps_type_to_vpn_type(self) -> None:
        model = VpnClient(name="WG Client", type="wireguard-client")
        payload = to_controller_create(model)
        assert payload["vpn_type"] == "wireguard-client"
        assert "type" not in payload

    def test_excludes_id(self) -> None:
        model = VpnClient(id="should-not-appear", name="Test")
        payload = to_controller_create(model)
        assert "id" not in payload


class TestToControllerUpdate:
    @pytest.mark.parametrize(
        "fields, expected, absent, present",
        [
            ({"id": "ignore-me", "enabled": True}, {"enabled": True}, ("id",), ()),
            ({"type": "wireguard-client"}, {"vpn_type": "wireguard-client"}, ("type",), ("vpn_type",)),
            ({"name": None, "enabled": False}, {"enabled": False}, ("name",), ()),
            ({"unknown": "value", "name": "Valid"}, {"name": "Valid"}, ("unknown",), ()),
        ],
        ids=["filters_out_id", "maps_type_to_vpn_type", "drops_none_values", "drops_unrecognised_keys"],
    )
    def test_to_controller_update_payload(self, fields, expected, absent, present) -> None:
        result = to_controller_update(fields)
        assert_fields(result, expected)
        for key in absent:
            assert key not in result
        for key in present:
            assert key in result
