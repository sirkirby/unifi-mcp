"""Tests for Protect alarm MCP tool wrappers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_update_rule_confirm_delegates_to_alarm_facade():
    from unifi_protect_mcp.tools import alarm

    facade = MagicMock()
    facade.update_rule = AsyncMock(return_value=({"id": "uuid-1", "title": "Updated"}, True))
    legacy = MagicMock()
    legacy.update_rule = AsyncMock()

    with (
        patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade),
        patch("unifi_protect_mcp.tools.alarm.alarm_manager", legacy),
    ):
        result = await alarm.protect_alarm_update_rule("uuid-1", {"title": "Updated"}, confirm=True)

    assert result == {"success": True, "data": {"id": "uuid-1", "title": "Updated"}}
    facade.update_rule.assert_awaited_once_with("uuid-1", {"title": "Updated"})
    legacy.update_rule.assert_not_called()


@pytest.mark.asyncio
async def test_create_rule_confirm_surfaces_coverage_meta_when_legacy_serves():
    from unifi_protect_mcp.tools import alarm

    facade = MagicMock()
    facade.create_rule = AsyncMock(return_value=({"id": "legacy-id", "title": "Created"}, False))

    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await alarm.protect_alarm_create_rule(
            {
                "title": "Created",
                "actions": [{"action_id": "protect:notify", "data": {"receivers": ["ALL_ITEMS"]}}],
            },
            confirm=True,
        )

    assert result["success"] is True
    assert result["data"]["id"] == "legacy-id"
    assert result["_meta"][alarm._ALARM_COVERAGE_META]["complete"] is False


@pytest.mark.asyncio
async def test_delete_rule_preview_uses_facade_get_rule():
    from unifi_protect_mcp.tools import alarm

    facade = MagicMock()
    facade.get_rule = AsyncMock(return_value=({"id": "uuid-1", "title": "Rule"}, True))

    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await alarm.protect_alarm_delete_rule("uuid-1", confirm=False)

    assert result["success"] is True
    assert result["requires_confirmation"] is True
    facade.get_rule.assert_awaited_once_with("uuid-1")


@pytest.mark.asyncio
async def test_update_rule_preview_rejects_empty_actions():
    from unifi_protect_mcp.tools import alarm

    result = await alarm.protect_alarm_update_rule("uuid-1", {"actions": []}, confirm=False)

    assert result["success"] is False
    assert "actions must be a non-empty list" in result["error"]
