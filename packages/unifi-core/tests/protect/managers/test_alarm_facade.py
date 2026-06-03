"""Tests for AlarmRulesFacade — backend selection + canonical normalization."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.protect.managers.alarm_facade import AlarmRulesFacade
from unifi_core.protect.managers.alarm_manager_service import AlarmManagerPermissionError

_CANONICAL = {"id": "uuid-1", "title": "Dog Poop", "triggers": [{"trigger_id": "protect:ai.nls"}]}
_RAW_LEGACY = {
    "id": "66a5c92a0022f903e4000400",
    "name": "Motion",
    "enable": True,
    "conditions": [{"type": "motion"}],
    "actions": [{"type": "webhook"}],
}


def _facade(*, service_list=None, service_err=False, legacy_list=None, service_get=None, legacy_get=None):
    service = MagicMock()
    legacy = MagicMock()
    service.list_rules = AsyncMock(
        side_effect=AlarmManagerPermissionError("x") if service_err else None, return_value=service_list
    )
    service.get_rule = AsyncMock(
        side_effect=AlarmManagerPermissionError("x") if service_err else None, return_value=service_get
    )
    legacy.list_rules = AsyncMock(return_value=legacy_list)
    legacy.get_rule = AsyncMock(return_value=legacy_get)
    return AlarmRulesFacade(service, legacy)


@pytest.mark.asyncio
async def test_list_rules_prefers_alarm_manager_and_reports_complete():
    rules, complete = await _facade(service_list=[_CANONICAL]).list_rules()
    assert complete is True
    assert rules[0]["id"] == "uuid-1"


@pytest.mark.asyncio
async def test_list_rules_falls_back_to_legacy_normalized_and_incomplete():
    rules, complete = await _facade(service_err=True, legacy_list=[_RAW_LEGACY]).list_rules()
    assert complete is False
    assert rules[0]["id"] == "66a5c92a0022f903e4000400"
    assert rules[0]["title"] == "Motion"  # normalized to canonical (name -> title)
    assert rules[0]["triggers"][0]["trigger_id"] == "motion"


@pytest.mark.asyncio
async def test_get_rule_prefers_alarm_manager():
    rule, complete = await _facade(service_get=_CANONICAL).get_rule("uuid-1")
    assert complete is True
    assert rule["id"] == "uuid-1"


@pytest.mark.asyncio
async def test_get_rule_falls_back_to_legacy_normalized():
    rule, complete = await _facade(service_err=True, legacy_get=_RAW_LEGACY).get_rule("66a5c92a0022f903e4000400")
    assert complete is False
    assert rule["title"] == "Motion"
