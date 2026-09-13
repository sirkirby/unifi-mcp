"""Tool contract tests for firewall-group create and update operations."""

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")


class TestGetFirewallGroup:
    @pytest.mark.asyncio
    async def test_details_use_public_model_fields(self) -> None:
        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as manager:
            manager.get_firewall_group_by_id = AsyncMock(
                return_value={
                    "_id": "g1",
                    "name": "Web",
                    "group_type": "port-group",
                    "group_members": ["443"],
                }
            )
            from unifi_network_mcp.tools.firewall import get_firewall_group_details

            result = await get_firewall_group_details("g1")

        assert result["details"] == {
            "id": "g1",
            "name": "Web",
            "group_type": "port-group",
            "members": ["443"],
        }


class TestCreateFirewallGroup:
    @pytest.mark.asyncio
    async def test_preview_uses_public_model_fields(self) -> None:
        from unifi_network_mcp.tools.firewall import create_firewall_group

        result = await create_firewall_group(
            group_data={"name": "Web", "group_type": "port-group", "members": ["80", "443"]},
            confirm=False,
        )

        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["preview"]["will_create"]["members"] == ["80", "443"]
        assert "group_members" not in result["preview"]["will_create"]

    @pytest.mark.asyncio
    async def test_confirm_translates_members_for_manager(self) -> None:
        created = {
            "_id": "g1",
            "name": "Web",
            "group_type": "port-group",
            "group_members": ["443"],
        }
        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as manager:
            manager.create_firewall_group = AsyncMock(return_value=created)
            from unifi_network_mcp.tools.firewall import create_firewall_group

            result = await create_firewall_group(
                group_data={"name": "Web", "group_type": "port-group", "members": ["443"]},
                confirm=True,
            )

        manager.create_firewall_group.assert_awaited_once_with(
            {"name": "Web", "group_type": "port-group", "group_members": ["443"]}
        )
        assert result["group"] == {
            "id": "g1",
            "name": "Web",
            "group_type": "port-group",
            "members": ["443"],
        }

    @pytest.mark.asyncio
    async def test_validation_errors_stay_inside_tool_contract(self) -> None:
        from unifi_network_mcp.tools.firewall import create_firewall_group

        result = await create_firewall_group(
            group_data={"name": "Web", "group_type": "invalid", "members": []},
            confirm=False,
        )

        assert result["success"] is False
        assert "group_type" in result["error"]


class TestUpdateFirewallGroup:
    @pytest.mark.parametrize("group_id", ["", "   "])
    @pytest.mark.asyncio
    async def test_rejects_blank_group_id_before_fetching(self, group_id: str) -> None:
        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as manager:
            manager.get_firewall_group_by_id = AsyncMock()
            from unifi_network_mcp.tools.firewall import update_firewall_group

            result = await update_firewall_group(group_id, {"name": "Renamed"}, confirm=False)

        assert result == {"success": False, "error": "group_id is required"}
        manager.get_firewall_group_by_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_preview_fetches_current_state(self) -> None:
        current = {
            "_id": "g1",
            "name": "Original",
            "group_type": "address-group",
            "group_members": ["10.0.0.1"],
        }
        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as manager:
            manager.get_firewall_group_by_id = AsyncMock(return_value=current)
            from unifi_network_mcp.tools.firewall import update_firewall_group

            result = await update_firewall_group("g1", {"name": "Renamed"}, confirm=False)

        assert result["success"] is True
        assert result["preview"]["current"] == {"name": "Original"}
        assert result["preview"]["proposed"] == {"name": "Renamed"}

    @pytest.mark.asyncio
    async def test_confirm_translates_partial_update(self) -> None:
        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as manager:
            manager.update_firewall_group = AsyncMock(return_value=True)
            from unifi_network_mcp.tools.firewall import update_firewall_group

            result = await update_firewall_group("g1", {"members": ["10.0.0.2"]}, confirm=True)

        assert result["success"] is True
        manager.update_firewall_group.assert_awaited_once_with("g1", {"group_members": ["10.0.0.2"]})

    @pytest.mark.asyncio
    async def test_rejects_group_type_change(self) -> None:
        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as manager:
            manager.update_firewall_group = AsyncMock()
            from unifi_network_mcp.tools.firewall import update_firewall_group

            result = await update_firewall_group("g1", {"group_type": "port-group"}, confirm=True)

        assert result["success"] is False
        assert "cannot be changed" in result["error"]
        manager.update_firewall_group.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_preview_returns_not_found(self) -> None:
        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as manager:
            manager.get_firewall_group_by_id = AsyncMock(return_value=None)
            from unifi_network_mcp.tools.firewall import update_firewall_group

            result = await update_firewall_group("missing", {"name": "Renamed"}, confirm=False)

        assert result == {"success": False, "error": "Firewall group 'missing' not found."}
