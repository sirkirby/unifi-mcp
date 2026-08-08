"""Network config cluster serializer unit tests (Phase 4A PR1 Cluster 3).

Covers VPN clients/servers, DNS records, static + active + traffic routes,
AP groups, and the mutation-ack registrations for create/update/delete on
networks, wlans, dns, routes, and ap_groups.
"""

from unifi_api.serializers._registry import (
    discover_serializers,
    serializer_registry_singleton,
)


def _registry():
    discover_serializers(manifest_tool_names=set())
    return serializer_registry_singleton()


# ---- VPN clients ----


def test_vpn_client_list_serializer_shape() -> None:
    """Phase 6 PR2 Task 21 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.vpn import VpnClient

    sample = {
        "_id": "vc1",
        "name": "Wireguard-Home",
        "purpose": "vpn-client",
        "vpn_type": "wireguard-client",
        "enabled": True,
        "wireguard_client_peer_endpoint": "vpn.example.com:51820",
        "wireguard_client_last_handshake": 1700000000,
    }
    out = VpnClient.from_manager_output(sample).to_dict()
    assert out["id"] == "vc1"
    assert out["name"] == "Wireguard-Home"
    assert out["type"] == "wireguard-client"
    assert out["enabled"] is True
    assert out["server_address"] == "vpn.example.com:51820"
    assert VpnClient.render_hint("list")["kind"] == "list"


def test_vpn_client_detail_serializer_shape() -> None:
    from unifi_api.graphql.types.network.vpn import VpnClient

    sample = {
        "_id": "vc2",
        "name": "OpenVPN-Site",
        "purpose": "vpn-client",
        "vpn_type": "openvpn-client",
        "enabled": False,
    }
    out = VpnClient.from_manager_output(sample).to_dict()
    assert out["id"] == "vc2"
    assert out["type"] == "openvpn-client"
    assert out["enabled"] is False
    assert VpnClient.render_hint("detail")["kind"] == "detail"


# ---- VPN servers ----


def test_vpn_server_list_serializer_shape() -> None:
    from unifi_api.graphql.types.network.vpn import VpnServer

    sample = {
        "_id": "vs1",
        "name": "Remote Access",
        "purpose": "remote-user-vpn",
        "vpn_type": "wireguard-server",
        "enabled": True,
        "wireguard_server_listen_port": 51820,
        "wireguard_server_subnet": "10.10.0.0/24",
    }
    out = VpnServer.from_manager_output(sample).to_dict()
    assert out["id"] == "vs1"
    assert out["name"] == "Remote Access"
    assert out["type"] == "wireguard-server"
    assert out["listen_port"] == 51820
    assert out["allowed_subnets"] == ["10.10.0.0/24"]
    assert VpnServer.render_hint("list")["kind"] == "list"


def test_vpn_server_detail_serializer_shape() -> None:
    from unifi_api.graphql.types.network.vpn import VpnServer

    sample = {
        "_id": "vs2",
        "name": "L2TP",
        "purpose": "vpn-server",
        "vpn_type": "l2tp-server",
        "enabled": True,
    }
    out = VpnServer.from_manager_output(sample).to_dict()
    assert out["id"] == "vs2"
    assert out["type"] == "l2tp-server"
    assert VpnServer.render_hint("detail")["kind"] == "detail"


# ---- DNS records ----


def test_dns_record_list_serializer_shape() -> None:
    """Phase 6 PR2 Task 21 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.dns import DnsRecord

    sample = {
        "_id": "dns1",
        "key": "router.local",
        "value": "192.168.1.1",
        "record_type": "A",
        "ttl": 300,
        "enabled": True,
    }
    out = DnsRecord.from_manager_output(sample).to_dict()
    assert out["id"] == "dns1"
    assert out["hostname"] == "router.local"
    assert out["ip"] == "192.168.1.1"
    assert out["type"] == "A"
    assert out["ttl"] == 300
    assert out["enabled"] is True
    assert DnsRecord.render_hint("list")["kind"] == "list"


def test_dns_record_detail_serializer_shape() -> None:
    from unifi_api.graphql.types.network.dns import DnsRecord

    sample = {
        "_id": "dns2",
        "key": "alias.local",
        "value": "router.local",
        "record_type": "CNAME",
        "ttl": 0,
        "enabled": False,
    }
    out = DnsRecord.from_manager_output(sample).to_dict()
    assert out["id"] == "dns2"
    assert out["hostname"] == "alias.local"
    assert out["type"] == "CNAME"
    assert out["enabled"] is False
    assert DnsRecord.render_hint("detail")["kind"] == "detail"


# ---- Static routes ----


def test_route_list_serializer_shape() -> None:
    """Phase 6 PR2 Task 21 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.route import Route

    sample = {
        "_id": "r1",
        "name": "Office subnet",
        "static-route_network": "10.0.0.0/24",
        "static-route_nexthop": "192.168.1.1",
        "static-route_distance": 1,
        "enabled": True,
    }
    out = Route.from_manager_output(sample).to_dict()
    assert out["id"] == "r1"
    assert out["name"] == "Office subnet"
    assert out["target_subnet"] == "10.0.0.0/24"
    assert out["gateway"] == "192.168.1.1"
    assert out["distance"] == 1
    assert out["enabled"] is True
    assert Route.render_hint("list")["kind"] == "list"


def test_route_detail_serializer_shape() -> None:
    from unifi_api.graphql.types.network.route import Route

    sample = {
        "_id": "r2",
        "name": "Lab",
        "static-route_network": "172.16.0.0/16",
        "static-route_nexthop": "192.168.99.1",
        "static-route_distance": 5,
        "enabled": False,
    }
    out = Route.from_manager_output(sample).to_dict()
    assert out["id"] == "r2"
    assert out["target_subnet"] == "172.16.0.0/16"
    assert out["gateway"] == "192.168.99.1"
    assert out["distance"] == 5
    assert Route.render_hint("detail")["kind"] == "detail"


# ---- Active routes ----


def test_active_route_list_serializer_shape() -> None:
    from unifi_api.graphql.types.network.route import ActiveRoute

    sample = {
        "nh": [{"intf": "eth0", "via": "192.168.1.1"}],
        "pfx": "0.0.0.0/0",
        "metric": 0,
        "t": "S",
    }
    out = ActiveRoute.from_manager_output(sample).to_dict()
    assert out["target_subnet"] == "0.0.0.0/0"
    # Either gateway or interface should be derivable from nh; both fields exist
    assert "gateway" in out
    assert "interface" in out
    assert ActiveRoute.render_hint("list")["kind"] == "list"


# ---- Traffic routes ----


def test_traffic_route_list_serializer_shape() -> None:
    from unifi_api.graphql.types.network.route import TrafficRoute

    sample = {
        "_id": "tr1",
        "description": "VPN-routed traffic",
        "enabled": True,
        "matching_target": "DOMAIN",
        "domains": [{"domain": "example.com"}],
        "target_devices": [{"client_mac": "aa:bb:cc:dd:ee:ff"}],
        "next_hop": "vpn-iface",
    }
    out = TrafficRoute.from_manager_output(sample).to_dict()
    assert out["id"] == "tr1"
    assert out["name"] == "VPN-routed traffic"
    assert out["enabled"] is True
    assert out["next_hop"] == "vpn-iface"
    assert TrafficRoute.render_hint("list")["kind"] == "list"


def test_traffic_route_detail_serializer_shape() -> None:
    from unifi_api.graphql.types.network.route import TrafficRoute

    sample = {
        "_id": "tr2",
        "description": "Block region",
        "enabled": False,
        "matching_target": "REGION",
    }
    out = TrafficRoute.from_manager_output(sample).to_dict()
    assert out["id"] == "tr2"
    assert out["name"] == "Block region"
    assert out["enabled"] is False
    assert TrafficRoute.render_hint("detail")["kind"] == "detail"


# ---- AP groups ----


def test_ap_group_list_serializer_shape() -> None:
    """Phase 6 PR2 Task 24 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.ap_group import ApGroup

    sample = {
        "_id": "apg1",
        "name": "Office APs",
        "device_macs": ["aa:bb:cc:00:11:22", "aa:bb:cc:00:11:33"],
    }
    out = ApGroup.from_manager_output(sample).to_dict()
    assert out["id"] == "apg1"
    assert out["name"] == "Office APs"
    assert out["ap_count"] == 2
    assert out["device_macs"] == ["aa:bb:cc:00:11:22", "aa:bb:cc:00:11:33"]
    assert ApGroup.render_hint("list")["kind"] == "list"


def test_ap_group_detail_serializer_shape() -> None:
    """Phase 6 PR2 Task 24 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.ap_group import ApGroup

    sample = {"_id": "apg2", "name": "Guest APs", "device_macs": []}
    out = ApGroup.from_manager_output(sample).to_dict()
    assert out["id"] == "apg2"
    assert out["name"] == "Guest APs"
    assert out["ap_count"] == 0
    assert ApGroup.render_hint("detail")["kind"] == "detail"


# ---- Mutation acks ----


def test_vpn_mutation_ack_bool() -> None:
    reg = _registry()
    for tool in ("unifi_update_vpn_client_state", "unifi_delete_vpn_client"):
        s = reg.serializer_for_tool(tool)
        out = s.serialize_action(True, tool_name=tool)
        assert out["success"] is True
        assert out["data"] == {"success": True}
        assert out["render_hint"]["kind"] == "detail"


def test_dns_mutation_ack_dispatches_for_all_mutations() -> None:
    reg = _registry()
    for tool in (
        "unifi_create_dns_record",
        "unifi_update_dns_record",
        "unifi_delete_dns_record",
    ):
        s = reg.serializer_for_tool(tool)
        out = s.serialize_action(True, tool_name=tool)
        assert out["render_hint"]["kind"] == "detail"


def test_route_mutation_ack_dispatches_for_all_mutations() -> None:
    reg = _registry()
    for tool in (
        "unifi_create_route",
        "unifi_update_route",
        "unifi_update_traffic_route",
        "unifi_toggle_traffic_route",
    ):
        s = reg.serializer_for_tool(tool)
        out = s.serialize_action(True, tool_name=tool)
        assert out["render_hint"]["kind"] == "detail"


def test_ap_group_mutation_ack_dispatches_for_all_mutations() -> None:
    reg = _registry()
    for tool in (
        "unifi_create_ap_group",
        "unifi_update_ap_group",
        "unifi_delete_ap_group",
    ):
        s = reg.serializer_for_tool(tool)
        out = s.serialize_action(True, tool_name=tool)
        assert out["render_hint"]["kind"] == "detail"


def test_network_mutation_ack_dispatches() -> None:
    reg = _registry()
    for tool in ("unifi_create_network", "unifi_update_network", "unifi_delete_network"):
        s = reg.serializer_for_tool(tool)
        out = s.serialize_action(True, tool_name=tool)
        assert out["data"] == {"success": True}
        assert out["render_hint"]["kind"] == "detail"


def test_wlan_mutation_ack_dispatches_for_all_mutations() -> None:
    reg = _registry()
    for tool in (
        "unifi_create_wlan",
        "unifi_update_wlan",
        "unifi_delete_wlan",
        "unifi_toggle_wlan",
    ):
        s = reg.serializer_for_tool(tool)
        out = s.serialize_action(True, tool_name=tool)
        assert out["render_hint"]["kind"] == "detail"
