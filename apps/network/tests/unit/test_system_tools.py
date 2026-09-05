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
