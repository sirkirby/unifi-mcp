"""Tool-layer tests for the Alarm Manager v2 read tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.managers.alarm_v2_manager import AlarmV2PermissionError

_RULE = {
    "id": "rule-1",
    "title": "Dog Alarm",
    "triggers": [{"category_id": "protect:ai", "trigger_id": "protect:ai.nls", "data": {"nlsSentence": "x"}}],
    "actions": [{"category_id": "protect:notify", "action_id": "protect:notify"}],
}


@pytest.fixture
def mock_mgr():
    mgr = MagicMock()
    with patch("unifi_protect_mcp.tools.alarm_v2.alarm_v2_manager", mgr):
        yield mgr


@pytest.mark.asyncio
async def test_list_rules_success(mock_mgr):
    from unifi_protect_mcp.tools.alarm_v2 import protect_alarm_v2_list_rules

    mock_mgr.list_rules = AsyncMock(return_value=[_RULE])
    result = await protect_alarm_v2_list_rules()

    assert result["success"] is True
    assert result["data"]["count"] == 1
    assert result["data"]["rules"][0]["id"] == "rule-1"


@pytest.mark.asyncio
async def test_list_rules_permission_error_is_actionable(mock_mgr):
    from unifi_protect_mcp.tools.alarm_v2 import protect_alarm_v2_list_rules

    mock_mgr.list_rules = AsyncMock(side_effect=AlarmV2PermissionError("requires a SuperAdmin credential"))
    result = await protect_alarm_v2_list_rules()

    assert result["success"] is False
    assert "SuperAdmin" in result["error"]


@pytest.mark.asyncio
async def test_get_rule_success(mock_mgr):
    from unifi_protect_mcp.tools.alarm_v2 import protect_alarm_v2_get_rule

    mock_mgr.get_rule = AsyncMock(return_value=_RULE)
    result = await protect_alarm_v2_get_rule(rule_id="rule-1")

    assert result["success"] is True
    assert result["data"]["id"] == "rule-1"
    mock_mgr.get_rule.assert_awaited_once_with("rule-1")


@pytest.mark.asyncio
async def test_get_rule_not_found(mock_mgr):
    from unifi_protect_mcp.tools.alarm_v2 import protect_alarm_v2_get_rule

    mock_mgr.get_rule = AsyncMock(side_effect=UniFiNotFoundError("alarm rule (v2)", "nope"))
    result = await protect_alarm_v2_get_rule(rule_id="nope")

    assert result["success"] is False
    assert "nope" in result["error"]


@pytest.mark.asyncio
async def test_list_profiles_success(mock_mgr):
    from unifi_protect_mcp.tools.alarm_v2 import protect_alarm_v2_list_profiles

    mock_mgr.list_profiles = AsyncMock(return_value=[])
    result = await protect_alarm_v2_list_profiles()

    assert result["success"] is True
    assert result["data"]["profiles"] == []
    assert result["data"]["count"] == 0
