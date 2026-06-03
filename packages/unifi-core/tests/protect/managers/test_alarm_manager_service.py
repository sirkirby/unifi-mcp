"""Tests for AlarmManagerService (read surface over /api/v2/alarms/)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from uiprotect.exceptions import NotAuthorized
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.managers.alarm_manager_service import (
    AlarmManagerPermissionError,
    AlarmManagerService,
)

_RAW_RULE = {
    "id": "rule-1",
    "title": "Dog Alarm",
    "trigger_categories": [
        {
            "id": "protect:ai",
            "title": "AI",
            "triggers": [
                {
                    "id": "protect:ai.nls",
                    "title": "AI Natural Language",
                    "data": {"nlsSentence": "x", "nlsThreshold": 50},
                }
            ],
        }
    ],
    "action_categories": [],
    "scope": {"mode": "all", "data": {}},
    "stats": {"executions_24h": 0},
}


def _conn(*, return_value=None, side_effect=None):
    conn = MagicMock()
    conn.client.api_request = AsyncMock(return_value=return_value, side_effect=side_effect)
    return conn


@pytest.mark.asyncio
async def test_list_rules_normalizes_via_api_path():
    conn = _conn(return_value=[_RAW_RULE])
    rules = await AlarmManagerService(conn).list_rules()

    assert len(rules) == 1
    assert rules[0]["id"] == "rule-1"
    assert rules[0]["title"] == "Dog Alarm"
    assert rules[0]["triggers"][0]["trigger_id"] == "protect:ai.nls"
    # routed through the v2 console path
    _, kwargs = conn.client.api_request.await_args
    assert kwargs["api_path"] == "/api/v2/alarms/"


@pytest.mark.asyncio
async def test_forbidden_maps_to_actionable_permission_error():
    exc = NotAuthorized("Request failed: https://h/api/v2/alarms/protect - Status: 403 - Reason: Forbidden")
    conn = _conn(side_effect=exc)

    with pytest.raises(AlarmManagerPermissionError, match="SuperAdmin"):
        await AlarmManagerService(conn).list_rules()


@pytest.mark.asyncio
async def test_get_rule_not_found_raises():
    conn = _conn(return_value=[_RAW_RULE])
    with pytest.raises(UniFiNotFoundError):
        await AlarmManagerService(conn).get_rule("does-not-exist")


@pytest.mark.asyncio
async def test_get_rule_returns_match():
    conn = _conn(return_value=[_RAW_RULE])
    rule = await AlarmManagerService(conn).get_rule("rule-1")
    assert rule["id"] == "rule-1"
