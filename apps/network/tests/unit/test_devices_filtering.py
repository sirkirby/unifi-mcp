"""Tests for list_devices compression and get_device_details section selection."""

import os
from copy import deepcopy
from inspect import signature
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import TypeAdapter, ValidationError

from unifi_core.redaction import REDACTED

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
@pytest.mark.parametrize("redact", [True, False])
async def test_device_details_redacts_credentials_at_response_boundary(monkeypatch, redact):
    monkeypatch.setenv("UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS", str(redact).lower())
    keys = ["x_authkey", "x_vwirekey", "syslog_key", "guest_token", "x_inform_authkey", "x_ssh_sha512passwd"]
    secrets = dict.fromkeys(keys, "synthetic-device-secret")
    raw = {**deepcopy(SWITCH_RAW), **secrets, "nested": [secrets.copy()], "x_ssh_hostkey_fingerprint": "public"}
    original = deepcopy(raw)
    with patch("unifi_network_mcp.tools.devices.device_manager") as manager:
        manager.get_device_details = AsyncMock(return_value=_detail_mock(raw))
        manager._connection = _mock_conn()
        from unifi_network_mcp.tools.devices import get_device_details

        result = await get_device_details(raw["mac"])

    assert result["success"] is True
    for key in keys:
        expected = REDACTED if redact else secrets[key]
        assert result["device"][key] == expected
        assert result["device"]["nested"][0][key] == expected
    assert result["device"]["x_ssh_hostkey_fingerprint"] == "public"
    assert result["device"]["mac"] == raw["mac"]
    assert raw == original


@pytest.mark.asyncio
@pytest.mark.parametrize("redact", [True, False])
async def test_device_list_redacts_nested_raw_tables(monkeypatch, redact):
    monkeypatch.setenv("UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS", str(redact).lower())
    raw = deepcopy(GATEWAY_RAW)
    raw["network_table"] = [{"name": "VPN", "x_ca_key": "synthetic-vpn-key", "x_ca_crt": "public"}]
    original = deepcopy(raw)
    with patch("unifi_network_mcp.tools.devices.device_manager") as manager:
        manager.get_devices = AsyncMock(return_value=[raw])
        manager._connection = _mock_conn()
        from unifi_network_mcp.tools.devices import list_devices

        result = await list_devices(include_details=True, summary=False)

    assert result["success"] is True
    network = result["devices"][0]["network_table"][0]
    assert network["x_ca_key"] == (REDACTED if redact else "synthetic-vpn-key")
    assert network["x_ca_crt"] == "public"
    assert raw == original


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


@pytest.mark.asyncio
@pytest.mark.parametrize("redact", [True, False])
async def test_device_projection_preserves_nested_response_policy(monkeypatch, redact):
    monkeypatch.setenv("UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS", str(redact).lower())
    raw = {**deepcopy(SWITCH_RAW), "port_table": [{"port_idx": 1, "x_password": "synthetic-port-secret"}]}
    with patch("unifi_network_mcp.tools.devices.device_manager") as manager:
        manager.get_devices = AsyncMock(return_value=[raw])
        manager._connection = _mock_conn()
        from unifi_network_mcp.tools.devices import list_devices

        result = await list_devices(fields="mac,ports", include_details=True, summary=False)
    assert result["success"] is True
    assert set(result["devices"][0]) == {"mac", "ports"}
    assert result["devices"][0]["ports"][0]["x_password"] == (REDACTED if redact else "synthetic-port-secret")


PORT7_RAW = {
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
    "lldp_table": [],
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,expected_ports",
    [
        # LLDP neighbor resolved for port 1; port 2 has none.
        (SWITCH_RAW, {1: ("AP-1", "aa:bb:cc:00:00:99"), 2: (None, None)}),
        # A port with last_seen_mac but no LLDP entry (wireless client traffic) has lldp_neighbor None.
        (PORT7_RAW, {7: (None, "aa:bb:cc:00:00:cc")}),
    ],
)
async def test_get_device_details_ports_summary(raw, expected_ports):
    with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
        mock_dm.get_device_details = AsyncMock(return_value=_detail_mock(raw))
        mock_dm._connection = _mock_conn()

        from unifi_network_mcp.tools.devices import get_device_details

        result = await get_device_details("aa:bb:cc:00:00:10", summary=True, include="ports")

    assert result["success"] is True and result["summary_mode"] is True
    ports = {pp["port_idx"]: pp for pp in result["device"]["port_summary"]}
    assert set(ports) == set(expected_ports)
    for idx, (neighbor_name, last_seen_mac) in expected_ports.items():
        neighbor = ports[idx]["lldp_neighbor"]
        assert (neighbor["name"] if neighbor else None) == neighbor_name
        assert ports[idx]["last_seen_mac"] == last_seen_mac


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "include,expected,unknown_sections",
    [
        # include="all" populates every section: basic + ports + lldp (+ radios/uplink when present).
        (
            "all",
            {
                "mac": SWITCH_RAW["mac"],
                "port_count": len(SWITCH_RAW["port_table"]),
                "lldp_table": SWITCH_RAW["lldp_table"],
            },
            None,
        ),
        # Typos in include surface as `unknown_sections` so LLM callers can self-correct;
        # the known section is still applied.
        ("basic,prts", {"mac": SWITCH_RAW["mac"]}, ["prts"]),
    ],
)
async def test_get_device_details_summary_sections(include, expected, unknown_sections):
    with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
        mock_dm.get_device_details = AsyncMock(return_value=_detail_mock(SWITCH_RAW))
        mock_dm._connection = _mock_conn()

        from unifi_network_mcp.tools.devices import get_device_details

        result = await get_device_details("aa:bb:cc:00:00:10", summary=True, include=include)

    assert {key: result["device"][key] for key in expected} == expected
    assert result.get("unknown_sections") == unknown_sections


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "device_type,raw,expected",
    [
        ("switch", SWITCH_RAW, {"total_ports": 2, "ports_up": 1}),
        (
            "gateway",
            GATEWAY_RAW,
            {"wan1_ip": "203.0.113.5", "wan1_up": True, "network_count": 2, "cpu_usage": "12.5"},
        ),
    ],
)
async def test_list_devices_summary_compresses_raw_tables(device_type, raw, expected):
    with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
        mock_dm.get_devices = AsyncMock(return_value=[raw])
        mock_dm._connection = _mock_conn()

        from unifi_network_mcp.tools.devices import list_devices

        result = await list_devices(device_type=device_type, include_details=True)

    dev = result["devices"][0]
    assert {key: dev[key] for key in expected} == expected
    assert "port_table" not in dev  # compressed, not raw


@pytest.mark.asyncio
@pytest.mark.parametrize("devices", [[SWITCH_RAW, GATEWAY_RAW], []])
async def test_list_devices_returns_all_by_default(devices):
    # No limit by default — preserves upstream behavior (no silent truncation); empty stays well-defined.
    with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
        mock_dm.get_devices = AsyncMock(return_value=list(devices))
        mock_dm._connection = _mock_conn()

        from unifi_network_mcp.tools.devices import list_devices

        result = await list_devices()

    assert result["total_count"] == result["returned_count"] == result["count"] == len(devices)
    assert result["limit"] is None
    assert len(result["devices"]) == len(devices)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs,channel_filter,total,indexes,next_offset,has_more",
    [
        ({"limit": 2, "offset": 2}, None, 5, [2, 3], 4, True),
        ({"limit": 2, "offset": 4}, None, 5, [4], None, False),
        # Filters apply before pagination: channel 36 leaves two of five.
        ({"channel": 36, "limit": 1, "offset": 1}, 36, 2, [4], None, False),
    ],
)
async def test_rogue_aps_full_mode_pagination(kwargs, channel_filter, total, indexes, next_offset, has_more):
    aps = (
        [{**ap, "channel": 1 if index < 3 else 36} for index, ap in enumerate(ROGUE_APS)]
        if channel_filter
        else ROGUE_APS
    )
    with patch("unifi_network_mcp.tools.devices.device_manager") as manager:
        manager.list_rogue_aps = AsyncMock(return_value=aps)
        manager._connection.site = "default"
        from unifi_network_mcp.tools.devices import list_rogue_aps

        result = await list_rogue_aps(summary=False, **kwargs)

    assert result["total_count"] == total
    assert result["returned_count"] == len(indexes)
    assert result["rogue_aps"] == [aps[i] for i in indexes]
    assert result["next_offset"] == next_offset
    assert result["has_more"] is has_more
