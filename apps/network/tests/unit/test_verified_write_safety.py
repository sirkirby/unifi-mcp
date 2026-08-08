"""Regression coverage for verified writes and missing mutation lifecycle tools."""

import os
from unittest.mock import AsyncMock, patch

import pytest

from unifi_core.write_verification import verify_write

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")


@pytest.mark.asyncio
async def test_create_guest_network_is_rejected_before_controller_call() -> None:
    with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
        mock_mgr.create_network = AsyncMock()
        from unifi_network_mcp.tools.network import create_network

        result = await create_network(
            {
                "name": "Guest",
                "purpose": "guest",
                "ip_subnet": "192.0.2.1/24",
                "dhcpd_enabled": False,
            },
            confirm=True,
        )

    assert result["success"] is False
    assert "Internal firewall zone" in result["error"]
    mock_mgr.create_network.assert_not_called()


@pytest.mark.asyncio
async def test_update_guest_purpose_is_rejected_before_controller_call() -> None:
    with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
        mock_mgr.update_network = AsyncMock()
        from unifi_network_mcp.tools.network import update_network

        result = await update_network("net001", {"purpose": "guest"}, confirm=False)

    assert result["success"] is False
    assert "Hotspot zone" in result["error"]
    mock_mgr.update_network.assert_not_called()


@pytest.mark.asyncio
async def test_partial_wlan_write_lists_persisted_and_dropped_fields() -> None:
    current = {"_id": "w1", "name": "SSID", "networkconf_id": "old", "guest_policy": False}
    after = {**current, "networkconf_id": "new"}
    write_result = verify_write(
        operation="update",
        requested={"networkconf_id": "new", "guest_policy": True},
        before=current,
        after=after,
        metadata={"wlan_id": "w1"},
    )
    with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
        mock_mgr.get_wlan_details = AsyncMock(return_value=current)
        mock_mgr.update_wlan = AsyncMock(return_value=write_result)
        mock_mgr._connection.site = "default"
        from unifi_network_mcp.tools.network import update_wlan

        result = await update_wlan(
            "w1",
            {"networkconf_id": "new", "guest_policy": True},
            confirm=True,
        )

    assert result["success"] is False
    assert result["mutation_applied"] is True
    assert result["partial_success"] is True
    assert result["persisted_fields"] == ["networkconf_id"]
    assert result["dropped_fields"] == ["guest_policy"]
    assert result["details_after_attempt"]["networkconf_id"] == "new"


@pytest.mark.asyncio
async def test_delete_network_preview_and_confirm_use_live_resource() -> None:
    current = {"_id": "net001", "name": "Disposable", "purpose": "corporate"}
    with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
        mock_mgr.get_network_details = AsyncMock(return_value=current)
        mock_mgr.delete_network = AsyncMock(return_value=True)
        from unifi_network_mcp.tools.network import delete_network

        preview = await delete_network("net001", confirm=False)
        confirmed = await delete_network("net001", confirm=True)

    assert preview["requires_confirmation"] is True
    assert preview["preview"]["will_delete"] == current
    assert confirmed["success"] is True
    mock_mgr.delete_network.assert_awaited_once_with("net001")
