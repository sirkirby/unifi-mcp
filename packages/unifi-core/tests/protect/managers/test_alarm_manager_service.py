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
    conn.client.api_request_raw = AsyncMock()
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


@pytest.mark.asyncio
async def test_create_rule_posts_v2_body_via_api_path():
    body = {"title": "New", "triggers_data": [], "actions_data": [], "scope": {}}
    conn = _conn(return_value={"id": "uuid-1", **body})

    result = await AlarmManagerService(conn).create_rule(body)

    assert result["id"] == "uuid-1"
    conn.client.api_request.assert_awaited_once_with(
        "protect",
        method="post",
        api_path="/api/v2/alarms/",
        json=body,
    )


@pytest.mark.asyncio
async def test_update_rule_patches_v2_body_via_api_path():
    body = {"title": "Updated", "triggers_data": [], "actions_data": [], "scope": {}}
    conn = _conn(return_value={"id": "uuid-1", **body})

    result = await AlarmManagerService(conn).update_rule("uuid-1", body)

    assert result["title"] == "Updated"
    conn.client.api_request.assert_awaited_once_with(
        "protect/uuid-1",
        method="patch",
        api_path="/api/v2/alarms/",
        json=body,
    )


@pytest.mark.asyncio
async def test_delete_rule_uses_raw_delete_and_returns_deleted_ack():
    conn = _conn(return_value={})

    result = await AlarmManagerService(conn).delete_rule("uuid-1")

    assert result == {"deleted": True, "rule_id": "uuid-1"}
    conn.client.api_request_raw.assert_awaited_once_with(
        "protect/uuid-1",
        method="delete",
        api_path="/api/v2/alarms/",
    )
