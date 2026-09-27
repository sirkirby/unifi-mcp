"""Network tool tests for fixed client access-point association."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_fixed_ap_preview_has_before_after_and_does_not_write():
    with patch("unifi_network_mcp.tools.clients.client_manager") as manager:
        manager.get_client_details = AsyncMock(
            return_value=SimpleNamespace(raw={"name": "client", "fixed_ap_enabled": False})
        )
        manager.set_client_fixed_ap = AsyncMock()
        from unifi_network_mcp.tools.clients import set_client_fixed_ap

        result = await set_client_fixed_ap("aa:bb:cc:dd:ee:ff", True, "11:22:33:44:55:66")

    assert result["success"] is True
    assert result["requires_confirmation"] is True
    assert result["preview"]["current"]["fixed_ap_enabled"] is False
    manager.set_client_fixed_ap.assert_not_awaited()


@pytest.mark.asyncio
async def test_fixed_ap_tool_validates_enable_requirements_before_manager():
    from unifi_network_mcp.tools.clients import set_client_fixed_ap

    result = await set_client_fixed_ap("aa:bb:cc:dd:ee:ff", True)
    assert result["success"] is False
    assert "fixed_ap_mac is required" in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("ap_mac", [None, "", "11:22:33:44:55:66"])
async def test_fixed_ap_confirm_delegates_to_manager_without_reconnect(ap_mac):
    with patch("unifi_network_mcp.tools.clients.client_manager") as manager:
        manager.get_client_details = AsyncMock(return_value=SimpleNamespace(raw={"name": "client"}))
        manager.set_client_fixed_ap = AsyncMock(
            return_value={"success": True, "fixed_ap_enabled": False, "fixed_ap_mac": None}
        )
        from unifi_network_mcp.tools.clients import set_client_fixed_ap

        result = await set_client_fixed_ap("aa:bb:cc:dd:ee:ff", False, ap_mac, confirm=True)

    assert result == {
        "success": True,
        "message": "Client fixed AP settings updated.",
        "settings": {"success": True, "fixed_ap_enabled": False, "fixed_ap_mac": None},
    }
    manager.set_client_fixed_ap.assert_awaited_once_with(
        client_mac="aa:bb:cc:dd:ee:ff", fixed_ap_enabled=False, fixed_ap_mac=None
    )


@pytest.mark.asyncio
async def test_fixed_ap_tool_returns_private_error_text():
    with patch("unifi_network_mcp.tools.clients.client_manager") as manager:
        manager.get_client_details = AsyncMock(side_effect=RuntimeError("private controller detail aa:bb:cc:dd:ee:ff"))
        from unifi_network_mcp.tools.clients import set_client_fixed_ap

        result = await set_client_fixed_ap("aa:bb:cc:dd:ee:ff", False)

    assert result == {"success": False, "error": "Failed to set client fixed AP settings"}
