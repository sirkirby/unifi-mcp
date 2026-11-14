"""Teleport tool contract: thin wrappers over the VPN manager."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from unifi_core.network.models.teleport import teleport_from_controller
from unifi_core.write_verification import failed_write, noop_write, verify_write

RECORD = {
    "_id": "teleport-id",
    "key": "teleport",
    "site_id": "site-id",
    "enabled": True,
    "subnet_cidr": "192.168.2.1/24",
}
CURRENT = teleport_from_controller(RECORD)


@pytest.fixture
def manager(monkeypatch):
    from unifi_network_mcp.tools import vpn

    manager = MagicMock()
    manager._connection.site = "default"
    manager.get_teleport_settings = AsyncMock(return_value=CURRENT)
    manager.prepare_teleport_settings_update = AsyncMock(
        return_value=(CURRENT.model_dump(), {"subnet_cidr": "10.201.0.1/24"}, [])
    )
    manager.update_teleport_settings = AsyncMock(return_value=noop_write(resource=CURRENT.model_dump()))
    monkeypatch.setattr(vpn, "vpn_manager", manager)
    return manager


def test_tool_module_map_discovers_teleport_tools():
    from unifi_network_mcp.categories import TOOL_MODULE_MAP

    assert TOOL_MODULE_MAP["unifi_get_teleport_settings"] == "unifi_network_mcp.tools.vpn"
    assert TOOL_MODULE_MAP["unifi_update_teleport_settings"] == "unifi_network_mcp.tools.vpn"


@pytest.mark.asyncio
async def test_get_returns_projected_settings(manager):
    from unifi_network_mcp.tools.vpn import get_teleport_settings

    result = await get_teleport_settings()
    assert result == {
        "success": True,
        "site": "default",
        "teleport_settings": {
            "enabled": True,
            "subnet_cidr": "192.168.2.1/24",
            "id": "teleport-id",
            "site_id": "site-id",
        },
    }


@pytest.mark.asyncio
async def test_preview_does_not_write(manager):
    from unifi_network_mcp.tools.vpn import update_teleport_settings

    preview = await update_teleport_settings("10.201.0.1/24")
    assert preview["requires_confirmation"] is True
    assert preview["preview"]["current"] == {"subnet_cidr": "192.168.2.1/24"}
    assert preview["preview"]["proposed"] == {"subnet_cidr": "10.201.0.1/24"}
    assert any("re-invit" in warning.lower() for warning in preview["warnings"])
    manager.update_teleport_settings.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_refuses_overlap(manager):
    from unifi_network_mcp.tools.vpn import update_teleport_settings

    manager.prepare_teleport_settings_update.return_value = (
        CURRENT.model_dump(),
        {"subnet_cidr": "10.100.9.1/24"},
        ["Default"],
    )
    result = await update_teleport_settings("10.100.9.1/24")
    assert result == {"success": False, "error": "Teleport range overlaps configured network(s): Default"}
    manager.update_teleport_settings.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmed_change_reports_verification_and_warning(manager):
    from unifi_network_mcp.tools.vpn import update_teleport_settings

    after = {**RECORD, "subnet_cidr": "10.201.0.1/24"}
    manager.update_teleport_settings.return_value = verify_write(
        operation="update_teleport_settings",
        requested={"subnet_cidr": "10.201.0.1/24", "enabled": True},
        before=RECORD,
        after=after,
    )
    result = await update_teleport_settings("10.201.0.1/24", confirm=True)
    assert result["success"] is True
    assert result["persisted_fields"] == ["subnet_cidr"]
    assert result["message"] == "Teleport range updated and verified."
    assert len(result["warnings"]) == 1
    manager.update_teleport_settings.assert_awaited_once_with({"subnet_cidr": "10.201.0.1/24"})


@pytest.mark.asyncio
async def test_noop_change_has_no_warning(manager):
    from unifi_network_mcp.tools.vpn import update_teleport_settings

    result = await update_teleport_settings("192.168.2.1/24", confirm=True)
    assert result["success"] is True
    assert result["mutation_applied"] is False
    assert "warnings" not in result


@pytest.mark.asyncio
async def test_failed_write_is_passed_through(manager):
    from unifi_network_mcp.tools.vpn import update_teleport_settings

    manager.update_teleport_settings.return_value = failed_write(
        "Teleport range overlaps configured network(s): Guests", operation="update_teleport_settings"
    )
    result = await update_teleport_settings("10.110.0.1/24", confirm=True)
    assert result["success"] is False
    assert result["error"] == "Teleport range overlaps configured network(s): Guests"
    assert "warnings" not in result


@pytest.mark.asyncio
async def test_validation_error_names_rule_only(manager):
    from unifi_network_mcp.tools.vpn import update_teleport_settings

    manager.prepare_teleport_settings_update.side_effect = ValueError(
        "subnet_cidr must lie inside a private (RFC 1918) range"
    )
    result = await update_teleport_settings("8.8.8.1/24")
    assert result == {
        "success": False,
        "error": "Failed to update Teleport settings: subnet_cidr must lie inside a private (RFC 1918) range",
    }


@pytest.mark.asyncio
async def test_unexpected_errors_are_safe(manager):
    from unifi_network_mcp.tools.vpn import get_teleport_settings, update_teleport_settings

    manager.get_teleport_settings.side_effect = RuntimeError("synthetic-secret")
    manager.update_teleport_settings.side_effect = RuntimeError("synthetic-secret")
    read = await get_teleport_settings()
    write = await update_teleport_settings("10.201.0.1/24", confirm=True)
    assert read == {"success": False, "error": "Failed to get Teleport settings"}
    assert write["success"] is False
    assert "synthetic-secret" not in repr(read) + repr(write)
