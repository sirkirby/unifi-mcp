"""unifi_get_site_settings tool."""

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")

SECTIONS = {
    "sections": {
        "super_identity": {"_id": "site-1", "name": "Home", "role": "master"},
        "country": {"code": 840},
        "locale": {"timezone": "Europe/Berlin"},
        "connectivity": {"enabled": True, "uplink_type": "gateway", "x_mesh_psk": "not-for-output"},
        "ntp": {"ntp_server_1": "time.example", "ntp_server_2": "", "setting_preference": "manual"},
    }
}


@pytest.mark.asyncio
async def test_get_site_settings_returns_timezone_connectivity_and_ntp(monkeypatch):
    from unifi_network_mcp.tools import system

    mgr = MagicMock()
    mgr._connection.site = "default"
    mgr.get_site_settings = AsyncMock(return_value=SECTIONS)
    monkeypatch.setattr(system, "system_manager", mgr)

    result = await system.get_site_settings()

    assert result["success"] is True
    settings = result["site_settings"]
    assert settings["country"] == 840
    assert settings["timezone"] == "Europe/Berlin"
    assert settings["connectivity_enabled"] is True
    assert settings["connectivity_uplink_type"] == "gateway"
    assert settings["ntp_servers"] == ["time.example"]
    assert settings["ntp_setting_preference"] == "manual"
    assert "not-for-output" not in repr(result)


@pytest.mark.asyncio
async def test_network_health_preserves_vpn_diagnostics(monkeypatch):
    from unifi_network_mcp.tools import system

    vpn = {
        "subsystem": "vpn",
        "status": "error",
        "site_to_site_enabled": True,
        "site_to_site_num_active": 0,
        "site_to_site_num_inactive": 2,
        "site_to_site_rx_bytes": 0,
        "site_to_site_tx_bytes": 4096,
        "remote_user_enabled": False,
        "remote_user_num_active": 1,
        "remote_user_num_inactive": 0,
        "remote_user_rx_bytes": 2048,
        "remote_user_tx_bytes": 0,
    }
    mgr = MagicMock()
    mgr._connection.site = "default"
    mgr.get_network_health = AsyncMock(return_value=[vpn, {"subsystem": "wan", "status": "ok"}])
    monkeypatch.setattr(system, "system_manager", mgr)

    result = await system.get_network_health()

    assert result["success"] is True
    assert result["site"] == "default"
    for key, value in vpn.items():
        assert result["health_summary"][0][key] == value
    assert result["health_summary"][1] == {"subsystem": "wan", "status": "ok"}
    mgr.get_network_health.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_network_health_reports_device_counts_and_wan_details(monkeypatch):
    from unifi_network_mcp.tools import system

    wan = {
        "subsystem": "wan",
        "status": "ok",
        "num_gw": 1,
        "num_adopted": 1,
        "num_disconnected": 0,
        "num_pending": 0,
        "wan_ip": "203.0.113.10",
        "gateways": ["203.0.113.1"],
        "isp_name": "Example ISP",
        "rx_bytes-r": 1200.5,
    }
    www = {"subsystem": "www", "status": "ok", "latency": 14, "uptime": 86400, "drops": 2, "xput_up": 41.2}
    lan = {"subsystem": "lan", "status": "error", "num_sw": 4, "num_adopted": 4, "num_disconnected": 1}
    wlan = {"subsystem": "wlan", "status": "ok", "num_ap": 6, "num_pending": 1, "num_user": 40}
    # A limited admin role gets the vpn entry without its detail keys.
    vpn = {"subsystem": "vpn", "status": "error"}
    mgr = MagicMock()
    mgr._connection.site = "default"
    mgr.get_network_health = AsyncMock(return_value=[wan, www, lan, wlan, vpn])
    monkeypatch.setattr(system, "system_manager", mgr)

    result = await system.get_network_health()

    by_name = {entry["subsystem"]: entry for entry in result["health_summary"]}
    assert by_name["wan"] == {
        "subsystem": "wan",
        "status": "ok",
        "num_gw": 1,
        "num_adopted": 1,
        "num_disconnected": 0,
        "num_pending": 0,
        "wan_ip": "203.0.113.10",
        "gateways": ["203.0.113.1"],
        "isp_name": "Example ISP",
        "rx_bytes_per_sec": 1200.5,
    }
    assert by_name["www"] == {**www, "xput_up": 41.2}
    assert (by_name["lan"]["num_sw"], by_name["lan"]["num_disconnected"]) == (4, 1)
    assert (by_name["wlan"]["num_ap"], by_name["wlan"]["num_pending"]) == (6, 1)
    assert by_name["vpn"] == {"subsystem": "vpn", "status": "error"}


@pytest.mark.asyncio
async def test_network_health_reports_wan_monitor_stats(monkeypatch):
    from unifi_network_mcp.tools import system

    monitor = {"id": "eth8-3", "target": "1.1.1.1", "type": "icmp", "availability": 96.5, "latency_average": 18}
    wan = {
        "subsystem": "wan",
        "status": "ok",
        "uptime_stats": {"WAN": {"availability": 96.5, "latency_average": 18, "monitors": [monitor]}},
    }
    mgr = MagicMock()
    mgr._connection.site = "default"
    mgr.get_network_health = AsyncMock(return_value=[wan])
    monkeypatch.setattr(system, "system_manager", mgr)

    result = await system.get_network_health()

    assert result["health_summary"] == [wan]
