"""Guest creation previews use the same live zone guard as confirmed writes."""

from unittest.mock import AsyncMock, patch

import pytest

from unifi_core.write_verification import verify_write

GUEST = {
    "name": "Guest",
    "purpose": "guest",
    "firewall_zone_id": "hotspot-zone",
    "ip_subnet": "192.0.2.1/24",
    "dhcpd_enabled": False,
    "enabled": False,
}


@pytest.mark.asyncio
async def test_guest_preview_validates_zone_without_creating():
    with patch("unifi_network_mcp.tools.network.network_manager") as manager:
        manager.validate_firewall_zone_assignment = AsyncMock()
        manager.create_network = AsyncMock()
        from unifi_network_mcp.tools.network import create_network

        result = await create_network(dict(GUEST), confirm=False)

    assert result["success"] and result["requires_confirmation"]
    manager.validate_firewall_zone_assignment.assert_awaited_once_with({}, GUEST)
    manager.create_network.assert_not_awaited()
    assert result["preview"]["will_create"]["purpose"] == "guest"
    assert result["preview"]["will_create"]["firewall_zone_id"] == "hotspot-zone"


@pytest.mark.asyncio
async def test_guest_preview_rejects_wrong_zone_before_create():
    with patch("unifi_network_mcp.tools.network.network_manager") as manager:
        manager.validate_firewall_zone_assignment = AsyncMock(
            side_effect=ValueError("A verified Hotspot zone is required")
        )
        manager.create_network = AsyncMock()
        from unifi_network_mcp.tools.network import create_network

        result = await create_network(dict(GUEST), confirm=False)

    assert result["success"] is False
    assert "Hotspot" in result["error"]
    assert "preview" not in result
    manager.validate_firewall_zone_assignment.assert_awaited_once_with({}, GUEST)
    manager.create_network.assert_not_awaited()


@pytest.mark.asyncio
async def test_guest_preview_runtime_failure_is_private(caplog):
    with patch("unifi_network_mcp.tools.network.network_manager") as manager:
        manager.validate_firewall_zone_assignment = AsyncMock(side_effect=RuntimeError("controller-secret-canary"))
        manager.create_network = AsyncMock()
        from unifi_network_mcp.tools.network import create_network

        result = await create_network(dict(GUEST), confirm=False)

    assert result == {"success": False, "error": "Failed to preview guest network: check the controller connection"}
    assert "controller-secret-canary" not in caplog.text
    manager.create_network.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmed_guest_create_delegates_public_purpose_and_preserves_failed_verification():
    after = {**GUEST, "_id": "created-id", "purpose": "corporate"}
    with patch("unifi_network_mcp.tools.network.network_manager") as manager:
        manager._connection.site = "default"
        manager.create_network = AsyncMock(
            return_value=verify_write(
                operation="create", requested=GUEST, after=after, metadata={"network_id": "created-id"}
            )
        )
        from unifi_network_mcp.tools.network import create_network

        result = await create_network(dict(GUEST), confirm=True)

    manager.create_network.assert_awaited_once_with(GUEST)
    assert result["success"] is False
    assert result["mutation_applied"] is True
    assert result["network_id"] == "created-id"
    assert result["coerced_fields"] == ["purpose"]
