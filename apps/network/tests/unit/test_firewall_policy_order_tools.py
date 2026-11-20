"""Tools for the V2 firewall policy order of a zone pair."""

import copy
import os
from unittest.mock import AsyncMock, patch

import pytest

from unifi_core.exceptions import UniFiNotFoundError, UniFiOperationError

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")

ORDER = {"before_predefined_ids": ["allow-1", "allow-2"], "after_predefined_ids": ["block-1"]}
REQUESTED = {"before_predefined_ids": ["allow-2"], "after_predefined_ids": ["block-1", "allow-1"]}
MANAGER = "unifi_network_mcp.tools.firewall.firewall_manager"


@pytest.mark.asyncio
async def test_get_returns_the_order_of_the_pair():
    with patch(MANAGER) as manager:
        manager.get_firewall_policy_order_v2 = AsyncMock(return_value=copy.deepcopy(ORDER))
        from unifi_network_mcp.tools.firewall import get_firewall_policy_order

        result = await get_firewall_policy_order("zone-src", "zone-dst")

    assert result == {
        "success": True,
        "source_zone_id": "zone-src",
        "destination_zone_id": "zone-dst",
        "order": ORDER,
    }
    manager.get_firewall_policy_order_v2.assert_awaited_once_with("zone-src", "zone-dst")


@pytest.mark.asyncio
async def test_get_reports_an_unknown_zone():
    with patch(MANAGER) as manager:
        manager.get_firewall_policy_order_v2 = AsyncMock(side_effect=UniFiNotFoundError("firewall_zone", "zone-x"))
        from unifi_network_mcp.tools.firewall import get_firewall_policy_order

        result = await get_firewall_policy_order("zone-x", "zone-dst")

    assert result["success"] is False
    assert "zone-x" in result["error"]


@pytest.mark.asyncio
async def test_set_previews_without_writing():
    with patch(MANAGER) as manager:
        manager.preview_reorder_firewall_policies_v2 = AsyncMock(
            return_value={"current": copy.deepcopy(ORDER), "requested": copy.deepcopy(REQUESTED)}
        )
        manager.reorder_firewall_policies_v2 = AsyncMock()
        from unifi_network_mcp.tools.firewall import set_firewall_policy_order

        result = await set_firewall_policy_order(
            "zone-src", "zone-dst", ["allow-2"], ["block-1", "allow-1"], confirm=False
        )

    assert result["success"] is True
    assert result["requires_confirmation"] is True
    assert result["resource_id"] == "zone-src->zone-dst"
    assert result["preview"]["current"] == ORDER
    assert result["preview"]["proposed"] == REQUESTED
    manager.preview_reorder_firewall_policies_v2.assert_awaited_once_with(
        "zone-src", "zone-dst", ["allow-2"], ["block-1", "allow-1"]
    )
    manager.reorder_firewall_policies_v2.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_refuses_a_different_policy_set_in_the_preview():
    with patch(MANAGER) as manager:
        manager.preview_reorder_firewall_policies_v2 = AsyncMock(
            side_effect=ValueError(
                "Reorder payload must preserve the exact current policy ID set. Missing: block-1; unexpected: none"
            )
        )
        manager.reorder_firewall_policies_v2 = AsyncMock()
        from unifi_network_mcp.tools.firewall import set_firewall_policy_order

        result = await set_firewall_policy_order("zone-src", "zone-dst", ["allow-1", "allow-2"], [], confirm=False)

    assert result["success"] is False
    assert "Missing: block-1" in result["error"]
    manager.reorder_firewall_policies_v2.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_confirmed_returns_the_read_back_order():
    with patch(MANAGER) as manager:
        manager.preview_reorder_firewall_policies_v2 = AsyncMock()
        manager.reorder_firewall_policies_v2 = AsyncMock(return_value=copy.deepcopy(REQUESTED))
        from unifi_network_mcp.tools.firewall import set_firewall_policy_order

        result = await set_firewall_policy_order(
            "zone-src", "zone-dst", ["allow-2"], ["block-1", "allow-1"], confirm=True
        )

    assert result == {
        "success": True,
        "source_zone_id": "zone-src",
        "destination_zone_id": "zone-dst",
        "order": REQUESTED,
    }
    manager.reorder_firewall_policies_v2.assert_awaited_once_with(
        "zone-src", "zone-dst", ["allow-2"], ["block-1", "allow-1"]
    )
    manager.preview_reorder_firewall_policies_v2.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_confirmed_reports_a_read_back_that_differs():
    with patch(MANAGER) as manager:
        manager.reorder_firewall_policies_v2 = AsyncMock(
            side_effect=UniFiOperationError("The controller accepted the reorder but reports a different order")
        )
        from unifi_network_mcp.tools.firewall import set_firewall_policy_order

        result = await set_firewall_policy_order(
            "zone-src", "zone-dst", ["allow-2"], ["block-1", "allow-1"], confirm=True
        )

    assert result["success"] is False
    assert "reports a different order" in result["error"]
