"""Typed mDNS tool contract."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from unifi_core.network.models.mdns import mdns_from_controller
from unifi_core.write_verification import noop_write

RECORD = {
    "_id": "mdns-id",
    "mode": "all",
    "predefined_services": [],
    "custom_services": [],
    "enabled_for": "some",
    "enabled_for_network_ids": ["n1"],
}


@pytest.fixture
def manager(monkeypatch):
    from unifi_network_mcp.tools import system

    manager = MagicMock()
    manager._connection.site = "default"
    manager.get_mdns_settings = AsyncMock(return_value=mdns_from_controller(RECORD))
    manager.update_mdns_settings = AsyncMock(return_value=noop_write(resource=RECORD))
    monkeypatch.setattr(system, "system_manager", manager)
    return manager


def test_tool_module_map_discovers_mdns_tools():
    from unifi_network_mcp.categories import TOOL_MODULE_MAP

    assert TOOL_MODULE_MAP["unifi_get_mdns_settings"] == "unifi_network_mcp.tools.system"
    assert TOOL_MODULE_MAP["unifi_update_mdns_settings"] == "unifi_network_mcp.tools.system"


@pytest.mark.asyncio
async def test_get_and_real_preview_do_not_write(manager):
    from unifi_network_mcp.tools.system import get_mdns_settings, update_mdns_settings

    read = await get_mdns_settings()
    assert read["mdns_settings"]["enabled_for"] == "some"
    preview = await update_mdns_settings({"mode": "auto"})
    assert preview["requires_confirmation"] is True
    assert preview["preview"]["current"]["mode"] == "all"
    assert preview["preview"]["proposed"]["mode"] == "auto"
    manager.update_mdns_settings.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_update_is_rejected_before_manager(manager):
    from unifi_network_mcp.tools.system import update_mdns_settings

    result = await update_mdns_settings({"enabled_for": "all"}, confirm=True)
    assert not result["success"]
    manager.update_mdns_settings.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_rejects_service_list_under_all_mode(manager):
    from unifi_network_mcp.tools.system import update_mdns_settings

    services = [{"name": "Web", "address": "_http._tcp"}]
    rejected = await update_mdns_settings({"custom_services": services})
    assert rejected["success"] is False
    assert "mode 'all' requires" in rejected["error"]
    accepted = await update_mdns_settings({"mode": "custom", "custom_services": services})
    assert accepted["success"] is True
    assert accepted["requires_confirmation"] is True
    manager.update_mdns_settings.assert_not_awaited()


@pytest.mark.asyncio
async def test_safe_error_response(manager):
    from unifi_network_mcp.tools.system import get_mdns_settings, update_mdns_settings

    manager.get_mdns_settings.side_effect = RuntimeError("synthetic-secret")
    read = await get_mdns_settings()
    preview = await update_mdns_settings({"mode": "auto"})
    assert "synthetic-secret" not in repr(read)
    assert "synthetic-secret" not in repr(preview)
