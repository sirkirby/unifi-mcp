"""Tests for list_devices compression and get_device_details section selection."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


def _detail_mock(raw):
    d = MagicMock()
    d.raw = raw
    return d


def _patch_mgr(devices=None, detail=None):
    mock_conn = MagicMock()
    mock_conn.site = "default"
    p = patch("unifi_network_mcp.tools.devices.device_manager")
    mock = p.start()
    mock.get_devices = AsyncMock(return_value=list(devices or []))
    mock.get_device_details = AsyncMock(return_value=detail)
    mock._connection = mock_conn
    return p, mock


@pytest.mark.asyncio
async def test_get_device_details_ports_resolves_lldp_neighbor():
    p, _ = _patch_mgr(detail=_detail_mock(SWITCH_RAW))
    try:
        from unifi_network_mcp.tools.devices import get_device_details

        result = await get_device_details("aa:bb:cc:00:00:10", include="ports")
    finally:
        p.stop()
    assert result["success"] is True and result["summary_mode"] is True
    port1 = next(pp for pp in result["device"]["port_summary"] if pp["port_idx"] == 1)
    assert port1["lldp_neighbor"]["name"] == "AP-1"
    assert port1["last_seen_mac"] == "aa:bb:cc:00:00:99"
    port2 = next(pp for pp in result["device"]["port_summary"] if pp["port_idx"] == 2)
    assert port2["lldp_neighbor"] is None


@pytest.mark.asyncio
async def test_get_device_details_summary_false_returns_raw():
    p, _ = _patch_mgr(detail=_detail_mock(SWITCH_RAW))
    try:
        from unifi_network_mcp.tools.devices import get_device_details

        result = await get_device_details("aa:bb:cc:00:00:10", summary=False)
    finally:
        p.stop()
    assert result["summary_mode"] is False
    assert result["device"] == SWITCH_RAW


@pytest.mark.asyncio
async def test_list_devices_search_reports_total():
    p, _ = _patch_mgr(devices=[SWITCH_RAW, GATEWAY_RAW])
    try:
        from unifi_network_mcp.tools.devices import list_devices

        result = await list_devices(search="udm")
    finally:
        p.stop()
    assert result["total_count"] == 1 and result["returned_count"] == 1
    assert result["devices"][0]["name"] == "UDM"


@pytest.mark.asyncio
async def test_list_devices_switch_summary_replaces_raw_table():
    p, _ = _patch_mgr(devices=[SWITCH_RAW])
    try:
        from unifi_network_mcp.tools.devices import list_devices

        result = await list_devices(device_type="switch", include_details=True)
    finally:
        p.stop()
    dev = result["devices"][0]
    assert dev["total_ports"] == 2 and dev["ports_up"] == 1
    assert "port_table" not in dev  # compressed, not raw


@pytest.mark.asyncio
async def test_list_devices_gateway_summary_flattened():
    p, _ = _patch_mgr(devices=[GATEWAY_RAW])
    try:
        from unifi_network_mcp.tools.devices import list_devices

        result = await list_devices(device_type="gateway", include_details=True)
    finally:
        p.stop()
    dev = result["devices"][0]
    assert dev["wan1_ip"] == "203.0.113.5" and dev["wan1_up"] is True
    assert dev["network_count"] == 2 and dev["cpu_usage"] == "12.5"


@pytest.mark.asyncio
async def test_get_device_details_not_found_returns_failure():
    # A falsy device must yield success=False, not a silent {success: True, device: None}.
    p, _ = _patch_mgr(detail=None)
    try:
        from unifi_network_mcp.tools.devices import get_device_details

        result = await get_device_details("aa:bb:cc:99:99:99")
    finally:
        p.stop()
    assert result["success"] is False


@pytest.mark.asyncio
async def test_list_devices_returns_all_by_default():
    # No limit by default — preserves upstream behavior (no silent truncation).
    p, _ = _patch_mgr(devices=[SWITCH_RAW, GATEWAY_RAW])
    try:
        from unifi_network_mcp.tools.devices import list_devices

        result = await list_devices()
    finally:
        p.stop()
    assert result["total_count"] == 2 and result["returned_count"] == 2
    assert result["limit"] is None
