"""Registration and Core delegation for the Network threat posture read tool."""

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from unifi_core.network.managers.system_manager import SystemManager
from unifi_core.network.models.threat_posture import threat_posture_from_controller


def test_tool_registered_with_read_only_session_metadata():
    from unifi_network_mcp.runtime import server
    from unifi_network_mcp.tools import system  # noqa: F401 - decorator registration

    tool = server._tool_manager._tools["unifi_get_threat_posture"]
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.open_world_hint is False


def test_catalog_source_binding_uses_existing_system_category():
    from unifi_network_mcp.categories import NETWORK_CATEGORY_MAP

    root = Path(__file__).resolve().parents[4]
    generator = root / "scripts" / "generate_api_action_catalog.py"
    spec = importlib.util.spec_from_file_location("generate_api_action_catalog", generator)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bindings = module._source_bindings(root / "apps/network/src/unifi_network_mcp/tools/system.py", "unifi_network_mcp")
    assert bindings["unifi_get_threat_posture"] == ("system_manager", "get_threat_posture")
    assert NETWORK_CATEGORY_MAP["system"] == "system"


@pytest.mark.asyncio
async def test_tool_returns_only_projected_fields(monkeypatch):
    from unifi_network_mcp.tools import system

    manager = MagicMock()
    manager._connection.site = "default"
    manager.get_threat_posture = AsyncMock(return_value=threat_posture_from_controller("DAY", {"threats": 2}, []))
    monkeypatch.setattr(system, "system_manager", manager)
    result = await system.get_threat_posture()
    assert result["success"] is True
    assert result["site"] == "default"
    assert result["threat_posture"]["period"] == "DAY"
    assert result["threat_posture"]["threats"] == 2
    manager.get_threat_posture.assert_awaited_once_with(period="DAY")


@pytest.mark.asyncio
async def test_invalid_period_uses_core_validation_before_io(monkeypatch):
    from unifi_network_mcp.tools import system

    connection = MagicMock()
    connection.ensure_session_connected = AsyncMock()
    connection.request = AsyncMock()
    monkeypatch.setattr(system, "system_manager", SystemManager(connection))
    result = await system.get_threat_posture("YEAR")
    assert result == {"success": False, "error": "Failed to get threat posture"}
    connection.ensure_session_connected.assert_not_awaited()
    connection.request.assert_not_awaited()
