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
    shape_voucher_list,
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
    network = {
        "_id": "n1",
        "name": "LAN",
        "purpose": "corporate",
        "dhcpd_enabled": True,
        "wan_type": "dhcp",
        "wan_dns1": "1.1.1.1",
        "wan_dns2": "8.8.8.8",
    }
    result = shape_network_details(
        network,
        site="default",
        network_id="n1",
        include="dhcp,wan,typo",
        summary=True,
    )

    assert result["details"]["dhcpd_enabled"] is True
    assert result["details"]["wan_type"] == "dhcp"
    assert result["details"]["wan_dns1"] == "1.1.1.1"
    assert result["details"]["wan_dns2"] == "8.8.8.8"
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
    assert "protocol" not in result["policies"][0]
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

    assert plain_entry["protocol"] == "all"
    assert plain_entry["destination"] == {"zone_id": "z2", "matching_target": "ANY"}


def test_shape_firewall_policy_list_summary_hides_selectors_the_controller_ignores() -> None:
    """A residual port under port_matching_type ANY must not read as a port match."""
    policies = [
        {
            "_id": "p-stale",
            "name": "Stale",
            "enabled": True,
            "action": "ALLOW",
            "index": 1,
            "source": {"zone_id": "z1", "matching_target": "ANY", "port_matching_type": "ANY", "port": "53"},
            "destination": {
                "zone_id": "z2",
                "matching_target": "ANY",
                "port_matching_type": "SPECIFIC",
                "port_group_id": "g1",
            },
        },
        {
            "_id": "p-no-enum",
            "name": "No enum at all",
            "enabled": True,
            "action": "ALLOW",
            "index": 2,
            "source": {"zone_id": "z1", "matching_target": "ANY", "port": "53"},
            "destination": {"zone_id": "z2", "matching_target": "ANY"},
        },
    ]

    entry, no_enum = shape_firewall_policy_list(policies, site="default", summary=True)["policies"]

    assert entry["source"] == {"zone_id": "z1", "matching_target": "ANY"}
    assert entry["destination"] == {"zone_id": "z2", "matching_target": "ANY", "port_matching_type": "SPECIFIC"}
    # Every observed controller emits port_matching_type; a port with no enum at all is treated as inert.
    assert no_enum["source"] == {"zone_id": "z1", "matching_target": "ANY"}


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


def test_shape_device_list_last_seen_is_utc_aware() -> None:
    """last_seen must be a timezone-aware UTC ISO string, not the server's local time."""
    device = {"_id": "d1", "mac": "aa", "name": "AP", "type": "uap", "state": 1, "last_seen": 1_700_000_000}

    shaped = shape_device_list([device], site="default")

    assert shaped["devices"][0]["last_seen"] == "2023-11-14T22:13:20+00:00"


def test_shape_firewall_policy_list_summary_shows_client_and_inversion_selectors() -> None:
    policies = [
        {
            "_id": "p-client",
            "name": "Admin workstations",
            "enabled": True,
            "action": "ALLOW",
            "index": 1,
            "source": {
                "zone_id": "z1",
                "matching_target": "CLIENT",
                "client_macs": ["aa:bb:cc:dd:ee:ff"],
            },
            "destination": {"zone_id": "z2", "matching_target": "ANY", "client_macs": ["aa:bb:cc:dd:ee:ff"]},
        }
    ]

    entry = shape_firewall_policy_list(policies, site="default", summary=True)["policies"][0]

    assert entry["source"]["client_macs"] == ["aa:bb:cc:dd:ee:ff"]
    assert "client_macs" not in entry["destination"]


def test_shape_firewall_policy_list_summary_keeps_selectors_under_an_unknown_target() -> None:
    """A target this project has not seen may still be enforcing its selector; hiding it
    would report a narrow rule as if it matched the whole zone."""
    policies = [
        {
            "_id": "p-future",
            "name": "Future target",
            "enabled": True,
            "action": "BLOCK",
            "index": 1,
            "source": {"zone_id": "z1", "matching_target": "CLIENT_GROUP", "client_macs": ["aa:bb:cc:dd:ee:ff"]},
            "destination": {
                "zone_id": "z2",
                "matching_target": "ANY",
                "port_matching_type": "PORT_GROUP",
                "port_group_id": "g1",
            },
        }
    ]

    entry = shape_firewall_policy_list(policies, site="default", summary=True)["policies"][0]

    assert entry["source"]["client_macs"] == ["aa:bb:cc:dd:ee:ff"]
    assert entry["destination"]["port_group_id"] == "g1"


def test_summary_suppression_covers_exactly_the_write_side_selectors() -> None:
    """A canary on the write-side table, not a test of the shaper: read_views imports
    SELECTOR_ACTIVATORS, so adding a row there changes every list response. Fail here
    and decide deliberately what the summary should do with the new selector."""
    from unifi_core.network.models.firewall import SELECTOR_ACTIVATORS

    assert {selector for selector, _, _ in SELECTOR_ACTIVATORS} == {"client_macs", "port", "port_group_id"}


def test_shape_firewall_policy_list_summary_hides_address_selectors_under_another_target() -> None:
    """Showing `ips` beside `matching_target: ANY` reports a zone-wide rule as
    address-scoped — the reading this summary must never produce."""
    policies = [
        {
            "_id": "p-stale-ips",
            "name": "Zone wide",
            "enabled": True,
            "action": "ALLOW",
            "index": 1,
            "source": {
                "zone_id": "zA",
                "matching_target": "ANY",
                "matching_target_type": "SPECIFIC",
                "ips": ["10.0.0.5"],
                "ip_group_id": "grp-admins",
                "network_ids": ["net-mgmt"],
                "match_opposite_ips": True,
                "port_matching_type": "ANY",
                "port": "22",
            },
            "destination": {
                "zone_id": "zB",
                "matching_target": "NETWORK",
                "matching_target_type": "OBJECT",
                "network_ids": ["net-iot"],
                "ips": ["10.0.0.9"],
            },
        }
    ]

    entry = shape_firewall_policy_list(policies, site="default", summary=True)["policies"][0]

    assert entry["source"] == {"zone_id": "zA", "matching_target": "ANY", "matching_target_type": "SPECIFIC"}
    assert entry["destination"]["network_ids"] == ["net-iot"]
    assert "ips" not in entry["destination"]


@pytest.mark.parametrize(
    ("endpoint", "shown"),
    [
        ({"matching_target": "NETWORK", "network_ids": ["n1"], "match_opposite_networks": True}, True),
        ({"matching_target": "ANY", "match_opposite_networks": True}, False),
        (
            {"matching_target": "ANY", "port_matching_type": "SPECIFIC", "port": "53", "match_opposite_ports": True},
            True,
        ),
        ({"matching_target": "ANY", "port_matching_type": "ANY", "match_opposite_ports": True}, False),
        (
            {
                "matching_target": "ANY",
                "port_matching_type": "OBJECT",
                "port_group_id": "ports",
                "match_opposite_ports": True,
            },
            True,
        ),
    ],
)
def test_shape_firewall_policy_list_summary_gates_the_inversion_flags(endpoint: dict, shown: bool) -> None:
    """An inversion flag reverses a rule's meaning. Showing one on a rule that does not
    invert, or hiding one that does, is the same error in opposite directions."""
    flag = "match_opposite_networks" if "match_opposite_networks" in endpoint else "match_opposite_ports"
    policies = [
        {
            "_id": "p1",
            "name": "Inversion",
            "enabled": True,
            "action": "BLOCK",
            "index": 1,
            "source": {"zone_id": "z1", "matching_target": "ANY"},
            "destination": {"zone_id": "z2", **endpoint},
        }
    ]

    entry = shape_firewall_policy_list(policies, site="default", summary=True)["policies"][0]

    assert (flag in entry["destination"]) is shown


def test_shape_voucher_list_applies_filtering_paging_and_projection() -> None:
    vouchers = [
        {"_id": "v1", "code": "ABC1", "note": "Conf", "duration": 1440, "quota": 1, "create_time": 1000},
        {"_id": "v2", "code": "ABC2", "note": "Lounge", "duration": 2880, "quota": 0, "create_time": 2000},
        {"_id": "v3", "code": "XYZ3", "note": "Speaker", "duration": 720, "quota": 1, "create_time": 3000},
    ]

    # No args -> legacy envelope, controller order preserved
    unshaped = shape_voucher_list(vouchers, site="default")
    assert unshaped["success"] is True
    assert set(unshaped.keys()) == {"success", "site", "count", "vouchers"}
    assert unshaped["count"] == 3
    assert [v["id"] for v in unshaped["vouchers"]] == ["v1", "v2", "v3"]

    # Search + limit + offset + projection
    # search="abc" matches v1 (1000) and v2 (2000).
    # Sorted by created_at desc: v2 (2000) at index 0, v1 (1000) at index 1.
    shaped = shape_voucher_list(
        vouchers,
        site="default",
        search="abc",
        limit=1,
        offset=1,
        fields="id,code",
    )
    assert shaped["success"] is True
    assert shaped["total_count"] == 2
    assert shaped["count"] == 1
    assert shaped["limit"] == 1
    assert shaped["offset"] == 1
    assert "total" not in shaped
    assert "returned_count" not in shaped
    assert len(shaped["vouchers"]) == 1
    assert shaped["vouchers"][0] == {"id": "v1", "code": "ABC1"}


def test_shape_voucher_list_deterministic_sort_and_tie_break() -> None:
    """Shaped calls sort created_at desc with id desc tie-break; unshaped preserves input order."""
    vouchers = [
        {"_id": "id_beta", "code": "BETA", "create_time": 1000},
        {"_id": "id_alpha", "code": "ALPHA", "create_time": 1000},
        {"_id": "id_newest", "code": "NEWEST", "create_time": 2000},
        {"_id": "id_oldest", "code": "OLDEST", "create_time": 500},
    ]

    # Unshaped: preserves controller input order
    unshaped = shape_voucher_list(vouchers, site="default")
    assert [v["id"] for v in unshaped["vouchers"]] == ["id_beta", "id_alpha", "id_newest", "id_oldest"]

    # Shaped (limit=10): sorts created_at desc, ties broken by id desc
    shaped = shape_voucher_list(vouchers, site="default", limit=10)
    assert [v["id"] for v in shaped["vouchers"]] == [
        "id_newest",  # 2000
        "id_beta",  # 1000, id_beta > id_alpha
        "id_alpha",  # 1000, id_alpha
        "id_oldest",  # 500
    ]


def test_shape_voucher_list_ui_hyphenated_digit_search() -> None:
    """Search matches UI hyphenated digit codes against stored digit codes."""
    vouchers = [
        {"_id": "v1", "code": "1234567890", "note": "Standard guest", "create_time": 1000},
        {"_id": "v2", "code": "9876543210", "note": "VIP guest-pass", "create_time": 2000},
    ]

    # Full UI hyphenated search
    res1 = shape_voucher_list(vouchers, site="default", search="12345-67890")
    assert res1["count"] == 1
    assert res1["vouchers"][0]["code"] == "1234567890"

    # Partial UI hyphenated search
    res2 = shape_voucher_list(vouchers, site="default", search="12345-6")
    assert res2["count"] == 1
    assert res2["vouchers"][0]["code"] == "1234567890"

    # Exact hyphenated note match
    res3 = shape_voucher_list(vouchers, site="default", search="guest-pass")
    assert res3["count"] == 1
    assert res3["vouchers"][0]["code"] == "9876543210"

    # Arbitrary punctuation like dot is NOT stripped / generalized
    res4 = shape_voucher_list(vouchers, site="default", search="123.456")
    assert res4["count"] == 0


def test_shape_voucher_list_validates_bounds_and_fields() -> None:
    vouchers = [{"_id": "v1", "code": "ABC1"}]

    assert shape_voucher_list(vouchers, site="default", limit=0)["success"] is False
    assert shape_voucher_list(vouchers, site="default", limit=1001)["success"] is False
    assert shape_voucher_list(vouchers, site="default", offset=-1)["success"] is False
    assert shape_voucher_list(vouchers, site="default", fields="unknown")["success"] is False
    assert shape_voucher_list(vouchers, site="default", fields=["id"])["success"] is False


@pytest.mark.parametrize("fields", [None, "", " , "])
def test_device_projection_empty_preserves_existing_contract(fields) -> None:
    raw = [{"mac": "aa", "name": "Switch", "type": "usw"}]
    assert shape_device_list(raw, site="default", fields=fields) == shape_device_list(raw, site="default")


def test_device_projection_runs_after_filtering_and_detail_controls() -> None:
    raw = [
        {"mac": "aa", "name": "Switch", "type": "usw", "state": 1, "port_table": [{"port_idx": 1}]},
        {"mac": "bb", "name": "AP", "type": "uap", "state": 1},
    ]
    result = shape_device_list(raw, site="default", device_type="switch", fields=" mac, ports,mac ")
    assert result["devices"] == [{"mac": "aa"}]
    assert result["total_count"] == result["count"] == 1
    detailed = shape_device_list(
        raw, site="default", device_type="switch", fields="mac,ports", include_details=True, summary=False
    )
    assert detailed["devices"] == [{"mac": "aa", "ports": [{"port_idx": 1}]}]


@pytest.mark.parametrize("fields", [["name"], 1, "unknown-private-value"])
def test_device_projection_rejects_invalid_fields_even_for_empty_inventory(fields) -> None:
    result = shape_device_list([], site="default", fields=fields)
    assert result["success"] is False
    assert "unknown-private-value" not in result["error"]


def test_device_projection_preserves_public_inventory_provenance_and_unknown_values() -> None:
    raw = [{"source_api": "integration", "integration_id": "public-id", "mac": "aa"}]
    result = shape_device_list(raw, site="default", fields="mac,uptime")
    assert result["devices"] == [{"mac": "aa", "uptime": None}]
    assert result["_meta"]["source_api"] == "integration"
    assert result["_meta"]["complete"] is False
