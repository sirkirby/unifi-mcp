"""Unit tests for the Network VpnClient + VpnServer CRUD domain models."""

from __future__ import annotations

from unifi_core.network.models.vpn import (
    VPNCLIENT_MUTABLE_FIELDS,
    VPNCLIENT_READ_ONLY_FIELDS,
    VPNSERVER_MUTABLE_FIELDS,
    VPNSERVER_READ_ONLY_FIELDS,
    VpnClient,
    VpnServer,
    from_controller,
    to_controller_create,
    to_controller_update,
    vpn_server_from_controller,
)


class TestVpnClientFieldSets:
    def test_mutable_fields_contains_expected(self) -> None:
        for field in ("name", "enabled", "type", "server_address"):
            assert field in VPNCLIENT_MUTABLE_FIELDS, f"Expected {field!r} in VPNCLIENT_MUTABLE_FIELDS"

    def test_mutable_fields_excludes_id(self) -> None:
        assert "id" not in VPNCLIENT_MUTABLE_FIELDS

    def test_read_only_fields_contains_id(self) -> None:
        assert "id" in VPNCLIENT_READ_ONLY_FIELDS

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = VPNCLIENT_MUTABLE_FIELDS & VPNCLIENT_READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_cover_all_model_fields(self) -> None:
        all_fields = frozenset(VpnClient.model_fields.keys())
        assert VPNCLIENT_MUTABLE_FIELDS | VPNCLIENT_READ_ONLY_FIELDS == all_fields


class TestVpnServerFieldSets:
    def test_server_has_no_mutable_fields(self) -> None:
        assert VPNSERVER_MUTABLE_FIELDS == frozenset()

    def test_all_server_fields_are_read_only(self) -> None:
        all_fields = frozenset(VpnServer.model_fields.keys())
        assert VPNSERVER_READ_ONLY_FIELDS == all_fields


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

    def test_omits_none_fields(self) -> None:
        model = VpnClient(name="Minimal")
        payload = to_controller_create(model)
        assert "server_address" not in payload
        assert "enabled" not in payload


class TestToControllerUpdate:
    def test_filters_out_id(self) -> None:
        result = to_controller_update({"id": "ignore-me", "enabled": True})
        assert "id" not in result
        assert result["enabled"] is True

    def test_maps_type_to_vpn_type(self) -> None:
        result = to_controller_update({"type": "wireguard-client"})
        assert "vpn_type" in result
        assert result["vpn_type"] == "wireguard-client"
        assert "type" not in result

    def test_drops_none_values(self) -> None:
        result = to_controller_update({"name": None, "enabled": False})
        assert "name" not in result
        assert result["enabled"] is False

    def test_drops_unrecognised_keys(self) -> None:
        result = to_controller_update({"unknown": "value", "name": "Valid"})
        assert "unknown" not in result
        assert result["name"] == "Valid"
