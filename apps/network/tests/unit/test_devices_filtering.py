"""Tests for list_devices compression and get_device_details section selection."""

import os
from inspect import signature
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import TypeAdapter, ValidationError

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")

SWITCH_RAW = {
    "mac": "aa:bb:cc:00:00:10",
    "name": "Switch-A",
    "ip": "192.0.2.20",
    "type": "usw",
    "model": "US24",
    "state": 1,
    "version": "6.0.0",
    "adopted": True,
    "port_table": [
        {
            "port_idx": 1,
            "name": "Port 1",
            "up": True,
            "speed": 1000,
            "poe_enable": True,
            "poe_power": "3.2",
            "last_connection": {"mac": "aa:bb:cc:00:00:99"},
        },
        {"port_idx": 2, "name": "Port 2", "up": False, "speed": 0, "poe_enable": False},
    ],
    "lldp_table": [{"local_port_idx": 1, "chassis_id": "aa:bb:cc:00:00:11", "chassis_name": "AP-1", "port_id": "eth0"}],
}

GATEWAY_RAW = {
    "mac": "aa:bb:cc:00:00:20",
    "name": "UDM",
    "ip": "192.0.2.1",
    "type": "udm",
    "model": "UDMPRO",
    "state": 1,
    "wan1": {"ip": "203.0.113.5", "up": True},
    "wan2": {},
    "network_table": [{"_id": "n1"}, {"_id": "n2"}],
    "system-stats": {"cpu": "12.5", "mem": "40.0"},
}

ROGUE_APS = [
    {
        "_id": f"id-{index}",
        "bssid": f"00:00:00:00:00:{index:02x}",
        "essid": f"ssid-{index}",
        "channel": 36,
        "signal": -40 - index,
        "band": 5,
        "bw": 80,
        "security": "WPA2",
        "ap_mac": "aa:bb:cc:dd:ee:ff",
        "ap_name": "Office AP",
        "last_seen": 1_700_000_000 + index,
        "site_id": "private-controller-field",
    }
    for index in range(5)
]


def _mock_conn():
    c = MagicMock()
    c.site = "default"
    return c


def _detail_mock(raw):
    d = MagicMock()
    d.raw = raw
    return d


@pytest.mark.asyncio
async def test_get_device_details_default_preserves_pre_pr_full_raw_object():
    # Regression guard for the default contract: no-args must return the full raw
    # device object (port_table present, port_summary absent). Existing callers
    # of unifi_get_device_details before this PR received the full raw object.
    with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
        mock_dm.get_device_details = AsyncMock(return_value=_detail_mock(SWITCH_RAW))
        mock_dm._connection = _mock_conn()

        from unifi_network_mcp.tools.devices import get_device_details

        result = await get_device_details("aa:bb:cc:00:00:10")

    assert result["success"] is True
    assert result["summary_mode"] is False
    assert result["device"] == SWITCH_RAW
    # raw keys present; summary keys absent
    assert "port_table" in result["device"]
    assert "lldp_table" in result["device"]
    assert "port_summary" not in result["device"]


@pytest.mark.asyncio
async def test_get_device_details_ports_resolves_lldp_neighbor():
    # Opt-in summary path: summary=True, include="ports" -> port_summary with LLDP resolved.
    with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
        mock_dm.get_device_details = AsyncMock(return_value=_detail_mock(SWITCH_RAW))
        mock_dm._connection = _mock_conn()

        from unifi_network_mcp.tools.devices import get_device_details

        result = await get_device_details("aa:bb:cc:00:00:10", summary=True, include="ports")

    assert result["success"] is True and result["summary_mode"] is True
    port1 = next(pp for pp in result["device"]["port_summary"] if pp["port_idx"] == 1)
    assert port1["lldp_neighbor"]["name"] == "AP-1"
    assert port1["last_seen_mac"] == "aa:bb:cc:00:00:99"
    port2 = next(pp for pp in result["device"]["port_summary"] if pp["port_idx"] == 2)
    assert port2["lldp_neighbor"] is None


@pytest.mark.asyncio
async def test_list_devices_search_reports_total():
    with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
        mock_dm.get_devices = AsyncMock(return_value=[SWITCH_RAW, GATEWAY_RAW])
        mock_dm._connection = _mock_conn()

        from unifi_network_mcp.tools.devices import list_devices

        result = await list_devices(search="udm")

    assert result["total_count"] == 1 and result["returned_count"] == 1
    assert result["devices"][0]["name"] == "UDM"
    # back-compat: legacy `count` key preserved alongside returned_count
    assert result["count"] == result["returned_count"]


@pytest.mark.asyncio
async def test_list_devices_switch_summary_replaces_raw_table():
    with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
        mock_dm.get_devices = AsyncMock(return_value=[SWITCH_RAW])
        mock_dm._connection = _mock_conn()

        from unifi_network_mcp.tools.devices import list_devices

        result = await list_devices(device_type="switch", include_details=True)

    dev = result["devices"][0]
    assert dev["total_ports"] == 2 and dev["ports_up"] == 1
    assert "port_table" not in dev  # compressed, not raw


@pytest.mark.asyncio
async def test_list_devices_gateway_summary_flattened():
    with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
        mock_dm.get_devices = AsyncMock(return_value=[GATEWAY_RAW])
        mock_dm._connection = _mock_conn()

        from unifi_network_mcp.tools.devices import list_devices

        result = await list_devices(device_type="gateway", include_details=True)

    dev = result["devices"][0]
    assert dev["wan1_ip"] == "203.0.113.5" and dev["wan1_up"] is True
    assert dev["network_count"] == 2 and dev["cpu_usage"] == "12.5"


@pytest.mark.asyncio
async def test_get_device_details_surfaces_unknown_include_sections():
    # Typos in include must surface as `unknown_sections` so LLM callers can self-correct.
    with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
        mock_dm.get_device_details = AsyncMock(return_value=_detail_mock(SWITCH_RAW))
        mock_dm._connection = _mock_conn()

        from unifi_network_mcp.tools.devices import get_device_details

        result = await get_device_details("aa:bb:cc:00:00:10", summary=True, include="basic,prts")

    # known section still applied (basic fields present)
    assert result["device"]["mac"] == SWITCH_RAW["mac"]
    # typo surfaced
    assert result.get("unknown_sections") == ["prts"]


@pytest.mark.asyncio
async def test_get_device_details_not_found_returns_failure():
    # A falsy device must yield success=False, not a silent {success: True, device: None}.
    with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
        mock_dm.get_device_details = AsyncMock(return_value=None)
        mock_dm._connection = _mock_conn()

        from unifi_network_mcp.tools.devices import get_device_details

        result = await get_device_details("aa:bb:cc:99:99:99")

    assert result["success"] is False


@pytest.mark.asyncio
async def test_list_devices_include_details_summary_false_returns_raw_tables():
    # summary=False with include_details=True returns the pre-PR legacy raw shape
    # (port_table, wan1, network_table, system_stats) instead of the compressed
    # summaries; lets callers who need full tables opt out of compression.
    with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
        mock_dm.get_devices = AsyncMock(return_value=[SWITCH_RAW, GATEWAY_RAW])
        mock_dm._connection = _mock_conn()

        from unifi_network_mcp.tools.devices import list_devices

        result = await list_devices(include_details=True, summary=False)

    sw = next(d for d in result["devices"] if d["name"] == "Switch-A")
    gw = next(d for d in result["devices"] if d["name"] == "UDM")
    # switch: raw port table present (under legacy 'ports' key), compressed keys absent
    assert sw["ports"] == SWITCH_RAW["port_table"]
    assert sw["total_ports"] == len(SWITCH_RAW["port_table"])
    assert "ports_up" not in sw
    assert "ports_poe_enabled" not in sw
    # legacy poe_info wrapper present
    assert "poe_info" in sw and isinstance(sw["poe_info"], dict)
    # gateway: raw wan/network tables present, flattened keys absent
    assert gw["wan1"] == GATEWAY_RAW["wan1"]
    assert gw["network_table"] == GATEWAY_RAW["network_table"]
    assert gw["system_stats"] == GATEWAY_RAW["system-stats"]
    assert "wan1_ip" not in gw
    assert "network_count" not in gw
    assert "cpu_usage" not in gw


@pytest.mark.asyncio
async def test_get_device_details_summary_include_all_returns_every_section():
    # include="all" populates every section: basic + ports + radios (if any) + stats +
    # uplink (if any) + lldp.
    with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
        mock_dm.get_device_details = AsyncMock(return_value=_detail_mock(SWITCH_RAW))
        mock_dm._connection = _mock_conn()

        from unifi_network_mcp.tools.devices import get_device_details

        result = await get_device_details("aa:bb:cc:00:00:10", summary=True, include="all")

    d = result["device"]
    assert d["mac"] == SWITCH_RAW["mac"]  # basic
    assert d["port_count"] == len(SWITCH_RAW["port_table"])  # ports
    assert d["lldp_table"] == SWITCH_RAW["lldp_table"]  # lldp


@pytest.mark.asyncio
async def test_get_device_details_port_last_seen_mac_without_lldp_neighbor():
    # When a port has last_seen_mac but no LLDP entry, lldp_neighbor must be None
    # (wireless client traffic case — last_seen_mac is the wireless client's MAC,
    # not infrastructure).
    raw = {
        **SWITCH_RAW,
        "port_table": [
            {
                "port_idx": 7,
                "name": "Port 7",
                "up": True,
                "speed": 100,
                "poe_enable": False,
                # last_seen_mac is a wireless client's MAC -> no LLDP entry expected
                "last_connection": {"mac": "aa:bb:cc:00:00:cc"},
            },
        ],
        "lldp_table": [],  # no LLDP infrastructure on this port
    }
    with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
        mock_dm.get_device_details = AsyncMock(return_value=_detail_mock(raw))
        mock_dm._connection = _mock_conn()

        from unifi_network_mcp.tools.devices import get_device_details

        result = await get_device_details("aa:bb:cc:00:00:10", summary=True, include="ports")

    port = result["device"]["port_summary"][0]
    assert port["last_seen_mac"] == "aa:bb:cc:00:00:cc"
    assert port["lldp_neighbor"] is None  # not infrastructure — wireless client traffic


@pytest.mark.asyncio
async def test_list_devices_zero_items_case():
    with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
        mock_dm.get_devices = AsyncMock(return_value=[])
        mock_dm._connection = _mock_conn()

        from unifi_network_mcp.tools.devices import list_devices

        result = await list_devices()

    assert result["total_count"] == 0 and result["returned_count"] == 0
    assert result["count"] == 0
    assert result["devices"] == []


@pytest.mark.asyncio
async def test_list_devices_returns_all_by_default():
    # No limit by default — preserves upstream behavior (no silent truncation).
    with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
        mock_dm.get_devices = AsyncMock(return_value=[SWITCH_RAW, GATEWAY_RAW])
        mock_dm._connection = _mock_conn()

        from unifi_network_mcp.tools.devices import list_devices

        result = await list_devices()

    assert result["total_count"] == 2 and result["returned_count"] == 2
    assert result["limit"] is None


@pytest.mark.asyncio
async def test_rogue_aps_defaults_to_paginated_summary():
    with patch("unifi_network_mcp.tools.devices.device_manager") as manager:
        manager.list_rogue_aps = AsyncMock(return_value=ROGUE_APS)
        manager._connection.site = "default"
        from unifi_network_mcp.tools.devices import list_rogue_aps

        result = await list_rogue_aps(limit=2)

    assert result["total_count"] == 5
    assert result["returned_count"] == 2
    assert result["count"] == 2
    assert result["offset"] == 0
    assert result["next_offset"] == 2
    assert result["has_more"] is True
    assert result["summary_mode"] is True
    assert result["rogue_aps"][0]["ssid"] == "ssid-0"
    assert "site_id" not in result["rogue_aps"][0]


@pytest.mark.asyncio
async def test_rogue_aps_offset_and_full_mode():
    with patch("unifi_network_mcp.tools.devices.device_manager") as manager:
        manager.list_rogue_aps = AsyncMock(return_value=ROGUE_APS)
        manager._connection.site = "default"
        from unifi_network_mcp.tools.devices import list_rogue_aps

        result = await list_rogue_aps(limit=2, offset=2, summary=False)

    assert result["rogue_aps"] == ROGUE_APS[2:4]
    assert result["next_offset"] == 4
    assert result["has_more"] is True


@pytest.mark.asyncio
async def test_rogue_aps_final_page_has_no_continuation():
    with patch("unifi_network_mcp.tools.devices.device_manager") as manager:
        manager.list_rogue_aps = AsyncMock(return_value=ROGUE_APS)
        manager._connection.site = "default"
        from unifi_network_mcp.tools.devices import list_rogue_aps

        result = await list_rogue_aps(limit=2, offset=4, summary=False)

    assert result["returned_count"] == 1
    assert result["next_offset"] is None
    assert result["has_more"] is False


@pytest.mark.asyncio
async def test_rogue_ap_filters_apply_before_pagination():
    mixed_channels = [{**ap, "channel": 1 if index < 3 else 36} for index, ap in enumerate(ROGUE_APS)]
    with patch("unifi_network_mcp.tools.devices.device_manager") as manager:
        manager.list_rogue_aps = AsyncMock(return_value=mixed_channels)
        manager._connection.site = "default"
        from unifi_network_mcp.tools.devices import list_rogue_aps

        result = await list_rogue_aps(channel=36, limit=1, offset=1, summary=False)

    assert result["total_count"] == 2
    assert result["rogue_aps"] == [mixed_channels[4]]
    assert result["has_more"] is False


def test_rogue_ap_pagination_bounds_are_in_schema_and_validate_inputs():
    from unifi_network_mcp.tools.devices import list_rogue_aps

    parameters = signature(list_rogue_aps).parameters
    limit_adapter = TypeAdapter(parameters["limit"].annotation)
    offset_adapter = TypeAdapter(parameters["offset"].annotation)

    assert limit_adapter.json_schema()["minimum"] == 1
    assert limit_adapter.json_schema()["maximum"] == 500
    assert offset_adapter.json_schema()["minimum"] == 0
    assert limit_adapter.validate_python(1) == 1
    assert limit_adapter.validate_python(500) == 500

    for invalid_limit in (0, 501):
        with pytest.raises(ValidationError):
            limit_adapter.validate_python(invalid_limit)
    with pytest.raises(ValidationError):
        offset_adapter.validate_python(-1)
