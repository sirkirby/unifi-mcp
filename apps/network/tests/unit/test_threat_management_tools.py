"""Unit tests for unifi_get_threat_management_settings MCP tool."""

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from unifi_core.network.models.threat_management import (
    threat_management_from_controller,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
_SCRIPT = REPO_ROOT / "scripts" / "generate_api_action_catalog.py"
_spec = importlib.util.spec_from_file_location("generate_api_action_catalog", _SCRIPT)
_gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gen)
_source_bindings = _gen._source_bindings

SECRET_TOKEN = "synthetic-utm-token-secret-999"


@pytest.fixture
def mock_system_manager(monkeypatch):
    from unifi_network_mcp.tools import system

    manager = MagicMock()
    manager._connection.site = "default"
    raw_ips = {
        "ips_mode": "ips",
        "enabled_categories": ["p2p", "tor"],
        "enabled_networks": ["lan"],
        "utm_token": SECRET_TOKEN,
    }
    raw_dpi = {
        "enabled": True,
        "fingerprintingEnabled": True,
    }
    model = threat_management_from_controller(raw_ips, raw_dpi)
    manager.get_threat_management_settings = AsyncMock(return_value=model)
    monkeypatch.setattr(system, "system_manager", manager)
    return manager


@pytest.mark.asyncio
async def test_get_threat_management_settings_tool_success(mock_system_manager):
    from unifi_network_mcp.tools.system import get_threat_management_settings

    result = await get_threat_management_settings()
    assert result["success"] is True
    assert result["site"] == "default"
    settings = result["threat_management_settings"]
    assert settings["ips_mode"] == "ips"
    assert settings["enabled"] is True
    assert settings["enabled_categories"] == ["p2p", "tor"]
    assert settings["enabled_networks"] == ["lan"]
    assert settings["traffic_identification_enabled"] is True
    assert settings["device_fingerprinting_enabled"] is True
    assert SECRET_TOKEN not in repr(result)
    mock_system_manager.get_threat_management_settings.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_threat_management_settings_tool_error_handling(mock_system_manager, caplog):
    from unifi_network_mcp.tools.system import get_threat_management_settings

    mock_system_manager.get_threat_management_settings.side_effect = RuntimeError(
        f"Controller exploded with secret {SECRET_TOKEN}"
    )

    result = await get_threat_management_settings()
    assert result["success"] is False
    assert result["error"] == "Failed to get threat management settings"
    assert SECRET_TOKEN not in repr(result)
    assert SECRET_TOKEN not in caplog.text


def test_tool_annotations():
    from unifi_network_mcp.runtime import server

    tools = server._tool_manager._tools
    assert "unifi_get_threat_management_settings" in tools
    tool = tools["unifi_get_threat_management_settings"]
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.open_world_hint is False


def test_catalog_generator_infers_mapping():
    tools_file = REPO_ROOT / "apps/network/src/unifi_network_mcp/tools/system.py"
    bindings = _source_bindings(tools_file, "unifi_network_mcp")
    assert "unifi_get_threat_management_settings" in bindings
    manager_attr, method_name = bindings["unifi_get_threat_management_settings"]
    assert manager_attr == "system_manager"
    assert method_name == "get_threat_management_settings"
