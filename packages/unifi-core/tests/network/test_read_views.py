from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.network.managers.client_manager import ClientManager
from unifi_core.network.read_views import (
    shape_alerts,
    shape_client_details,
    shape_client_list,
    shape_dashboard,
    shape_device_details,
    shape_device_list,
    shape_firewall_policy_list,
    shape_network_details,
    shape_network_list,
    shape_rogue_ap_list,
    shape_wlan_list,
)


def test_shape_client_list_applies_all_public_options() -> None:
    clients = [
        {"_id": "c1", "mac": "aa", "name": "Phone", "ip": "10.0.0.2", "is_wired": False, "signal": -45},
        {"_id": "c2", "mac": "bb", "name": "Desk", "ip": "10.0.0.3", "is_wired": True},
    ]

    result = shape_client_list(
        clients,
        site="default",
        filter_type="wireless",
        search="phone",
        limit=1,
        fields="mac,connection_type,naame",
    )

    assert result["total_count"] == 1
    assert result["clients"] == [{"mac": "aa", "connection_type": "Wireless"}]
    assert result["unknown_fields"] == ["naame"]


def test_shape_client_details_supports_full_summary_and_missing() -> None:
    raw = {"mac": "aa", "name": "Phone", "ip": "10.0.0.2", "is_wired": False, "signal": -45, "tx_bytes": 4}
    client = SimpleNamespace(raw=raw)

    full = shape_client_details(client, site="default", mac_address="aa", summary=False)
    summary = shape_client_details(
        client,
        site="default",
        mac_address="aa",
        include="wireless,traffic,typo",
        summary=True,
    )
    missing = shape_client_details(None, site="default", mac_address="missing")

    assert full["client"]["signal"] == -45
    assert summary["client"]["signal"] == -45
    assert summary["client"]["tx_bytes"] == 4
    assert summary["unknown_sections"] == ["typo"]
    assert missing == {"success": False, "error": "Client not found with MAC address: missing"}


def test_shape_device_list_applies_filters_limit_and_both_detail_modes() -> None:
    switch = {
        "_id": "d1",
        "mac": "aa",
        "name": "Office Switch",
        "type": "usw",
        "state": 1,
        "port_table": [{"up": True, "poe_enable": True}],
    }
    offline = {"_id": "d2", "mac": "bb", "name": "Offline Switch", "type": "usw", "state": 0}

    compact = shape_device_list(
        [switch, offline],
        site="default",
        device_type="switch",
        status="online",
        search="office",
        limit=1,
        include_details=True,
        summary=True,
    )
    raw = shape_device_list([switch], site="default", include_details=True, summary=False)

    assert compact["total_count"] == 1
    assert compact["devices"][0]["total_ports"] == 1
    assert "ports" not in compact["devices"][0]
    assert raw["devices"][0]["ports"] == switch["port_table"]


def test_shape_device_details_supports_sections_and_missing() -> None:
    raw = {
        "mac": "aa",
        "name": "Switch",
        "type": "usw",
        "state": 1,
        "port_table": [{"port_idx": 1, "up": True, "last_connection": {"mac": "cc"}}],
        "lldp_table": [{"local_port_idx": 1, "chassis_id": "dd", "chassis_name": "AP", "port_id": "eth0"}],
    }

    result = shape_device_details(
        SimpleNamespace(raw=raw),
        site="default",
        mac_address="aa",
        include="ports,typo",
        summary=True,
    )

    assert result["device"]["port_summary"][0]["lldp_neighbor"]["name"] == "AP"
    assert result["unknown_sections"] == ["typo"]
    assert shape_device_details(None, site="default", mac_address="missing")["success"] is False


def test_shape_device_details_normalizes_radio_summary_channel() -> None:
    raw = {
        "mac": "aa",
        "name": "Gateway",
        "type": "udm",
        "state": 1,
        "radio_table": [
            {"radio": "ng", "channel": 11, "tx_power": 6},
            {"radio": "6e", "channel": "auto", "tx_power": 21},
        ],
    }

    result = shape_device_details(
        SimpleNamespace(raw=raw),
        site="default",
        mac_address="aa",
        include="radios",
        summary=True,
    )

    assert result["device"]["radio_summary"] == [
        {"radio": "ng", "channel": 11, "tx_power": 6},
        {"radio": "6e", "channel": 0, "tx_power": 21},
    ]


def test_shape_network_list_applies_every_filter_and_projection() -> None:
    networks = [
        {"_id": "n1", "name": "Guest", "purpose": "guest", "vlan": 20, "enabled": True},
        {"_id": "n2", "name": "LAN", "purpose": "corporate", "vlan": 1, "enabled": True},
    ]

    result = shape_network_list(
        networks,
        site="default",
        search="20",
        purpose="Guest",
        limit=1,
        fields="_id,name,vlann",
    )

    assert result["networks"] == [{"_id": "n1", "name": "Guest"}]
    assert result["unknown_fields"] == ["vlann"]


def test_shape_network_details_supports_sections_and_missing() -> None:
    network = {"_id": "n1", "name": "LAN", "purpose": "corporate", "dhcpd_enabled": True, "wan_type": "dhcp"}
    result = shape_network_details(
        network,
        site="default",
        network_id="n1",
        include="dhcp,wan,typo",
        summary=True,
    )

    assert result["details"]["dhcpd_enabled"] is True
    assert result["details"]["wan_type"] == "dhcp"
    assert result["unknown_sections"] == ["typo"]
    assert shape_network_details(None, site="default", network_id="missing")["success"] is False


def test_shape_wlan_list_filters_searches_and_limits() -> None:
    wlans = [
        {"_id": "w1", "name": "Guest WiFi", "enabled": True, "security": "open"},
        {"_id": "w2", "name": "Staff", "enabled": False, "security": "wpapsk"},
    ]
    result = shape_wlan_list(wlans, site="default", search="guest", enabled_only=True, limit=1)

    assert result["total_count"] == 1
    assert result["wlans"][0]["id"] == "w1"


def test_shape_firewall_policy_list_applies_filters_and_shapes() -> None:
    policies = [
        {
            "_id": "p1",
            "name": "Allow Guest",
            "enabled": True,
            "action": "ALLOW",
            "index": 1,
            "source": {"zone_id": "z1"},
            "destination": {"zone_id": "z2"},
        },
        {"_id": "p2", "name": "Disabled", "enabled": False, "action": "BLOCK", "index": 2},
    ]
    result = shape_firewall_policy_list(
        policies,
        site="default",
        search="guest",
        action="allow",
        enabled_only=True,
        limit=1,
        summary=True,
    )
    full = shape_firewall_policy_list(policies[:1], site="default", summary=False)

    assert result["policies"][0]["id"] == "p1"
    assert result["returned_count"] == 1
    assert "source" in full["policies"][0]
    assert shape_firewall_policy_list([], site="default")["note"]


def test_shape_firewall_policy_list_summary_surfaces_port_matching() -> None:
    policies = [
        {
            "_id": "p-port",
            "name": "Block external DNS",
            "enabled": True,
            "action": "BLOCK",
            "index": 1,
            "protocol": "tcp_udp",
            "source": {
                "zone_id": "z1",
                "matching_target": "IP",
                "matching_target_type": "OBJECT",
                "ip_group_id": "resolvers",
                "match_opposite_ips": True,
                "port_matching_type": "ANY",
                "match_opposite_ports": False,
            },
            "destination": {
                "zone_id": "z2",
                "matching_target": "ANY",
                "port_matching_type": "SPECIFIC",
                "port": "53,853",
                "match_opposite_ports": False,
            },
        },
        {
            "_id": "p-plain",
            "name": "Allow all",
            "enabled": True,
            "action": "ALLOW",
            "index": 2,
            "protocol": "all",
            "source": {"zone_id": "z1", "matching_target": "ANY", "port_matching_type": "ANY"},
            "destination": {"zone_id": "z2", "matching_target": "ANY", "port_matching_type": "ANY"},
        },
    ]

    result = shape_firewall_policy_list(policies, site="default", summary=True)
    port_entry, plain_entry = result["policies"]

    assert port_entry["protocol"] == "tcp_udp"
    assert port_entry["destination"] == {
        "zone_id": "z2",
        "matching_target": "ANY",
        "port_matching_type": "SPECIFIC",
        "port": "53,853",
    }
    assert port_entry["source"]["ip_group_id"] == "resolvers"
    assert port_entry["source"]["match_opposite_ips"] is True
    assert "match_opposite_ports" not in port_entry["source"]
    assert "port_matching_type" not in port_entry["source"]

    assert "protocol" not in plain_entry
    assert plain_entry["destination"] == {"zone_id": "z2", "matching_target": "ANY"}


def test_shape_rogue_ap_list_applies_filters_pagination_and_shape() -> None:
    aps = [
        {"bssid": "a", "essid": "one", "channel": 36, "signal": -50, "extra": 1},
        {"bssid": "b", "essid": "two", "channel": 36, "signal": -40, "extra": 2},
        {"bssid": "c", "essid": "three", "channel": 1, "signal": -30, "extra": 3},
    ]
    result = shape_rogue_ap_list(
        aps,
        site="default",
        within_hours=12,
        channel=36,
        min_signal=-60,
        limit=1,
        offset=1,
        summary=False,
    )

    assert result["rogue_aps"] == [aps[1]]
    assert result["next_offset"] is None
    assert result["filters"] == {"channel": 36, "min_signal": -60}


def test_shape_alerts_and_dashboard_apply_non_default_options() -> None:
    alerts = shape_alerts([{"id": 1}, {"id": 2}], site="default", limit=1, include_archived=True)
    dashboard = shape_dashboard(
        [{"num_sta": 2, "wan_activity": [1], "radio_activity": [2]}],
        site="default",
        summary=True,
        history_seconds=3600,
    )

    assert alerts["alerts"] == [{"id": 1}]
    assert alerts["include_archived"] is True
    assert dashboard["dashboard"] == [{"num_sta": 2}]
    assert dashboard["omitted_sections"] == ["radio_activity", "wan_activity"]


@pytest.mark.asyncio
async def test_client_manager_include_offline_selects_all_client_path() -> None:
    manager = ClientManager(MagicMock())
    manager.get_all_clients = AsyncMock(return_value=[{"mac": "offline"}])

    result = await manager.get_clients(include_offline=True)

    assert result == [{"mac": "offline"}]
    manager.get_all_clients.assert_awaited_once_with()
