"""Tests for AlarmRulesFacade — backend selection + canonical normalization."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from uiprotect.exceptions import BadRequest, NvrError
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.managers.alarm_facade import AlarmRulesFacade
from unifi_core.protect.managers.alarm_manager_service import AlarmManagerPermissionError

_CANONICAL = {"id": "uuid-1", "title": "Dog Poop", "triggers": [{"trigger_id": "protect:ai.nls"}]}
_RAW_V2 = {
    "id": "019e9f9d-59a1-7ee3-8921-27f84a0086ea",
    "title": "Dog Poop",
    "trigger_categories": [
        {
            "id": "protect:ai",
            "title": "AI",
            "triggers": [
                {
                    "id": "protect:ai.nls",
                    "title": "AI Natural Language",
                    "data": {"nlsSentence": "dog poops", "nlsThreshold": 50},
                }
            ],
        }
    ],
    "action_categories": [
        {
            "id": "protect:notify",
            "title": "Notify",
            "actions": [
                {
                    "id": "protect:notify",
                    "title": "Notify",
                    "data": {"default_channels": ["push"], "receivers": ["ALL_ITEMS"], "is_critical": False},
                }
            ],
        }
    ],
    "scope": {"mode": "include", "data": {"scope_all_cameras": ["camera-1"]}},
}
_RAW_LEGACY = {
    "id": "66a5c92a0022f903e4000400",
    "name": "Motion",
    "enable": True,
    "conditions": [{"type": "motion"}],
    "actions": [{"type": "webhook"}],
}


def _facade(
    *,
    service_list=None,
    service_err=False,
    legacy_list=None,
    service_get=None,
    legacy_get=None,
    list_exc=None,
    get_exc=None,
):
    service = MagicMock()
    legacy = MagicMock()
    # service_err is shorthand for a v2 403; list_exc/get_exc inject other v2 errors.
    # They are mutually exclusive — combining them would silently ignore service_err.
    assert not (service_err and (list_exc or get_exc)), "pass service_err OR list_exc/get_exc, not both"
    _perm = AlarmManagerPermissionError("x") if service_err else None
    service.list_rules = AsyncMock(side_effect=list_exc or _perm, return_value=service_list)
    service.get_rule = AsyncMock(side_effect=get_exc or _perm, return_value=service_get)
    service.list_rules_raw = AsyncMock(side_effect=list_exc or _perm, return_value=service_list)
    service.get_rule_raw = AsyncMock(side_effect=get_exc or _perm, return_value=service_get)
    service.create_rule = AsyncMock(return_value=_RAW_V2)
    service.update_rule = AsyncMock(return_value=_RAW_V2)
    service.delete_rule = AsyncMock(return_value={"deleted": True, "rule_id": "uuid-1"})
    legacy.list_rules = AsyncMock(return_value=legacy_list)
    legacy.get_rule = AsyncMock(return_value=legacy_get)
    legacy.create_rule = AsyncMock(return_value=_RAW_LEGACY)
    legacy.update_rule = AsyncMock(return_value=_RAW_LEGACY)
    legacy.delete_rule = AsyncMock(return_value={"deleted": True, "rule_id": "66a5c92a0022f903e4000400"})
    return AlarmRulesFacade(service, legacy)


@pytest.mark.asyncio
async def test_list_rules_prefers_alarm_manager_and_reports_complete():
    facade = _facade(service_list=[_CANONICAL])
    rules, complete = await facade.list_rules()
    assert complete is True
    assert rules[0]["id"] == "uuid-1"
    facade._legacy.list_rules.assert_not_called()  # v2 served -> legacy untouched


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


@pytest.mark.asyncio
async def test_list_rules_falls_back_to_legacy_when_v2_empty():
    # v2 endpoint exists but is unpopulated on this console (e.g. Protect not yet
    # migrated to /api/v2/alarms) -> [] must fall back to legacy, not report 0 rules.
    rules, complete = await _facade(service_list=[], legacy_list=[_RAW_LEGACY]).list_rules()
    assert complete is False
    assert rules[0]["id"] == "66a5c92a0022f903e4000400"
    assert rules[0]["title"] == "Motion"


@pytest.mark.asyncio
async def test_list_rules_falls_back_on_v2_client_error():
    # v2 4xx (e.g. 404 not found, 400 global-alarm-manager) -> BadRequest -> use legacy.
    rules, complete = await _facade(list_exc=BadRequest("404"), legacy_list=[_RAW_LEGACY]).list_rules()
    assert complete is False
    assert rules[0]["title"] == "Motion"


@pytest.mark.asyncio
async def test_list_rules_propagates_v2_server_error():
    # v2 5xx (NvrError) is a real/transient outage -> surface it; do NOT mask with legacy.
    with pytest.raises(NvrError):
        await _facade(list_exc=NvrError("500"), legacy_list=[_RAW_LEGACY]).list_rules()


@pytest.mark.asyncio
async def test_get_rule_falls_back_when_v2_not_found():
    # v2 unpopulated -> service.get_rule raises NotFound -> fall back to legacy.
    rule, complete = await _facade(
        get_exc=UniFiNotFoundError("alarm rule", "66a5c92a0022f903e4000400"), legacy_get=_RAW_LEGACY
    ).get_rule("66a5c92a0022f903e4000400")
    assert complete is False
    assert rule["title"] == "Motion"


@pytest.mark.asyncio
async def test_get_rule_propagates_v2_server_error():
    with pytest.raises(NvrError):
        await _facade(get_exc=NvrError("500"), legacy_get=_RAW_LEGACY).get_rule("x")


@pytest.mark.asyncio
async def test_update_rule_routes_uuid_to_v2_with_full_editable_body():
    facade = _facade(service_get=_RAW_V2)

    result, complete = await facade.update_rule(
        "019e9f9d-59a1-7ee3-8921-27f84a0086ea",
        {"title": "Updated"},
    )

    assert complete is True
    assert result["id"] == _RAW_V2["id"]
    facade._legacy.update_rule.assert_not_called()
    facade._service.update_rule.assert_awaited_once()
    rule_id, body = facade._service.update_rule.await_args.args
    assert rule_id == _RAW_V2["id"]
    assert body == {
        "triggers_data": [[{"id": "protect:ai.nls", "data": {"nlsSentence": "dog poops", "nlsThreshold": 50}}]],
        "actions_data": [
            [
                {
                    "id": "protect:notify",
                    "data": {"default_channels": ["push"], "receivers": ["ALL_ITEMS"], "is_critical": False},
                }
            ]
        ],
        "scope": {"mode": "include", "data": {"scope_all_cameras": ["camera-1"]}},
        "title": "Updated",
    }


@pytest.mark.asyncio
async def test_update_rule_routes_object_id_to_legacy_with_translated_body():
    facade = _facade(legacy_get=_RAW_LEGACY)

    result, complete = await facade.update_rule("66a5c92a0022f903e4000400", {"title": "Updated"})

    assert complete is False
    assert result["title"] == "Motion"
    facade._service.update_rule.assert_not_called()
    facade._legacy.update_rule.assert_awaited_once()
    rule_id, body = facade._legacy.update_rule.await_args.args
    assert rule_id == "66a5c92a0022f903e4000400"
    assert body["name"] == "Updated"
    assert body["enable"] is True
    assert body["conditions"] == [{"type": "motion"}]
    assert body["actions"] == [{"type": "webhook"}]


@pytest.mark.asyncio
async def test_delete_rule_routes_uuid_to_v2():
    facade = _facade()

    result, complete = await facade.delete_rule("019e9f9d-59a1-7ee3-8921-27f84a0086ea")

    assert complete is True
    assert result == {"deleted": True, "rule_id": "uuid-1"}
    facade._service.delete_rule.assert_awaited_once_with("019e9f9d-59a1-7ee3-8921-27f84a0086ea")
    facade._legacy.delete_rule.assert_not_called()


@pytest.mark.asyncio
async def test_create_rule_prefers_v2_when_v2_serves_rules():
    facade = _facade(service_list=[_RAW_V2])

    result, complete = await facade.create_rule(
        {
            "title": "New",
            "triggers": [{"trigger_id": "protect:ai.nls", "data": {"nlsSentence": "x", "nlsThreshold": 50}}],
            "actions": [{"action_id": "protect:notify", "data": {"receivers": ["ALL_ITEMS"]}}],
            "scope": {"mode": "include", "data": {"scope_all_cameras": ["camera-1"]}},
        }
    )

    assert complete is True
    assert result["id"] == _RAW_V2["id"]
    facade._service.create_rule.assert_awaited_once()
    facade._legacy.create_rule.assert_not_called()


@pytest.mark.asyncio
async def test_create_rule_prefers_v2_when_endpoint_available_but_empty():
    facade = _facade(service_list=[])

    result, complete = await facade.create_rule(
        {
            "title": "New",
            "actions": [{"action_id": "protect:notify", "data": {"receivers": ["ALL_ITEMS"]}}],
        }
    )

    assert complete is True
    assert result["id"] == _RAW_V2["id"]
    facade._service.create_rule.assert_awaited_once()
    facade._legacy.create_rule.assert_not_called()


@pytest.mark.asyncio
async def test_create_rule_falls_back_to_legacy_when_v2_write_unavailable():
    facade = _facade(service_err=True)

    result, complete = await facade.create_rule(
        {
            "title": "New",
            "actions": [{"action_id": "protect:notify", "data": {"receivers": ["ALL_ITEMS"]}}],
        }
    )

    assert complete is False
    assert result["id"] == _RAW_LEGACY["id"]
    facade._service.create_rule.assert_not_called()
    facade._legacy.create_rule.assert_awaited_once()
