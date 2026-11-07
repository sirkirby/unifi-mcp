"""Tests for the Alarm Manager trigger/action catalog and webhook firing."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from uiprotect.exceptions import BadRequest, NotAuthorized, NvrError
from unifi_core.protect.managers.alarm_manager_service import AlarmManagerPermissionError, AlarmManagerService

_OPTIONS = {"$schema": "x", "type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}
_MANIFEST = {
    "trigger_categories": [
        {
            "id": "protect:external",
            "title": "Outside systems",
            "triggers": [
                {
                    "id": "protect:incoming.webhook",
                    "title": "Remote call",
                    "options_schema": _OPTIONS,
                    "required_scope_types": None,
                }
            ],
        },
        {"id": "protect:empty", "title": "No triggers"},
    ],
    "action_categories": [
        {
            "id": "protect:notify",
            "title": "Notify",
            "actions": [{"id": "protect:notify", "title": "Notify", "target_ids": ["t-1"]}],
        }
    ],
    "scope": {"$schema": "x", "mode": "include", "properties": {"cameras": {}}},
}


def _service(response=None, error=None, api_key=True):
    cm = MagicMock()
    cm.client.api_request = AsyncMock(side_effect=error, return_value=response)
    cm.client.send_alarm_webhook_public = AsyncMock(side_effect=error)
    cm.host = "console.example"
    if not api_key:
        cm.require_public_api_key.side_effect = ValueError("requires an API key")
    return AlarmManagerService(cm), cm


@pytest.mark.asyncio
async def test_get_catalog_reads_manifest_and_flattens_categories():
    service, cm = _service(response=_MANIFEST)
    catalog = await service.get_catalog(include_schemas=True)

    cm.client.api_request.assert_awaited_once_with("protect/manifest", method="get", api_path="/api/v2/alarms/")
    assert catalog["triggers"] == [
        {
            "category_id": "protect:external",
            "category_title": "Outside systems",
            "trigger_id": "protect:incoming.webhook",
            "title": "Remote call",
            "data": {},
            "options_schema": _OPTIONS,
        }
    ]
    assert catalog["actions"] == [
        {
            "category_id": "protect:notify",
            "category_title": "Notify",
            "action_id": "protect:notify",
            "title": "Notify",
            "data": {},
            "target_ids": ["t-1"],
        }
    ]
    assert catalog["scope"] == _MANIFEST["scope"]


@pytest.mark.asyncio
async def test_get_catalog_non_dict_response_is_empty():
    service, _ = _service(response=[])
    assert await service.get_catalog() == {"triggers": [], "actions": []}
    assert await service.get_catalog(include_schemas=True) == {"triggers": [], "actions": [], "scope": {}}


@pytest.mark.asyncio
async def test_get_catalog_forbidden_maps_to_permission_error():
    service, _ = _service(error=NotAuthorized("forbidden"))
    with pytest.raises(AlarmManagerPermissionError):
        await service.get_catalog()


@pytest.mark.asyncio
async def test_fire_webhook_uses_public_api_with_trigger_id():
    service, cm = _service()
    result = await service.fire_webhook("door-test")

    cm.require_public_api_key.assert_called_once()
    cm.client.send_alarm_webhook_public.assert_awaited_once_with("door-test")
    assert result == {"fired": True, "trigger_id": "door-test"}


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger_id", ["", "   ", None])
async def test_fire_webhook_requires_trigger_id(trigger_id):
    service, cm = _service()
    with pytest.raises(ValueError, match="trigger_id is required"):
        await service.fire_webhook(trigger_id)
    cm.client.send_alarm_webhook_public.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "trigger_id", [".", "..", "hook7f3a/x", "hook7f3a\\x", "hook7f3a?x", "hook7f3a#x", "hook7f3a%2F", "hook7f3a\x00"]
)
async def test_fire_webhook_refuses_an_id_that_is_not_one_path_segment(trigger_id):
    service, cm = _service()
    with pytest.raises(ValueError, match="must not be") as exc:
        await service.fire_webhook(trigger_id)
    assert "hook7f3a" not in str(exc.value)
    cm.require_public_api_key.assert_not_called()
    cm.client.send_alarm_webhook_public.assert_not_called()


@pytest.mark.asyncio
async def test_fire_webhook_without_api_key_is_refused_before_any_request():
    service, cm = _service(api_key=False)
    with pytest.raises(ValueError, match="API key"):
        await service.fire_webhook("door-test")
    cm.client.send_alarm_webhook_public.assert_not_called()


@pytest.mark.asyncio
async def test_fire_webhook_refusal_keeps_reason_without_url():
    exc = BadRequest("Request failed: https://console.example/x - Status: 404 - Reason: Not Found")
    service, _ = _service(error=exc)
    with pytest.raises(ValueError, match=r"refused to fire alarm webhook door-test: Not Found$"):
        await service.fire_webhook("door-test")


@pytest.mark.asyncio
async def test_get_catalog_refusal_keeps_reason_without_url():
    exc = BadRequest("Request failed: https://console.example/x - Status: 404 - Reason: Not Found")
    service, _ = _service(error=exc)
    with pytest.raises(ValueError, match=r"refused the alarm catalog request: Not Found$"):
        await service.get_catalog()


@pytest.mark.asyncio
async def test_fire_webhook_server_error_reports_unknown_outcome_without_url():
    exc = NvrError("Request failed: https://console.example/x - Status: 500 - Reason: Internal Server Error")
    service, _ = _service(error=exc)
    with pytest.raises(ValueError, match=r"may still have fired: Internal Server Error$"):
        await service.fire_webhook("door-test")


@pytest.mark.asyncio
async def test_fire_webhook_rejected_key_says_so():
    exc = NotAuthorized("Request failed: https://console.example/x - Status: 401 - Reason: Unauthorized")
    service, _ = _service(error=exc)
    with pytest.raises(ValueError, match=r"^The controller rejected the Protect API key"):
        await service.fire_webhook("door-test")


@pytest.mark.asyncio
async def test_get_catalog_tolerates_null_fields():
    manifest = {
        "trigger_categories": [{"id": "c", "title": "C", "triggers": [{"id": "t", "title": "T", "data": None}]}],
        "action_categories": None,
        "scope": None,
    }
    service, _ = _service(response=manifest)
    assert await service.get_catalog(include_schemas=True) == {
        "triggers": [{"category_id": "c", "category_title": "C", "trigger_id": "t", "title": "T", "data": {}}],
        "actions": [],
        "scope": {},
    }


@pytest.mark.asyncio
async def test_get_catalog_omits_schemas_by_default():
    service, _ = _service(response=_MANIFEST)
    catalog = await service.get_catalog()
    assert len(catalog["triggers"]) == 1
    assert "options_schema" not in catalog["triggers"][0]
    assert catalog["triggers"][0]["trigger_id"] == "protect:incoming.webhook"
    assert len(catalog["actions"]) == 1
    assert "options_schema" not in catalog["actions"][0]
    assert "scope" not in catalog


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "search",
    ["WEBHOOK", "remote CALL", "external", "outside systems", "  webhook  "],
    ids=["id", "title", "category_id", "category_title", "padded"],
)
async def test_get_catalog_search_matches_id_title_or_category(search):
    service, _ = _service(response=_MANIFEST)
    catalog = await service.get_catalog(search=search, include_schemas=True)
    assert [t["trigger_id"] for t in catalog["triggers"]] == ["protect:incoming.webhook"]
    assert catalog["triggers"][0]["options_schema"] == _OPTIONS
    assert catalog["actions"] == []


@pytest.mark.asyncio
async def test_get_catalog_search_without_match_is_empty():
    service, _ = _service(response=_MANIFEST)
    catalog = await service.get_catalog(search="no-such-thing")
    assert catalog["triggers"] == [] and catalog["actions"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("search", ["", "   "])
async def test_get_catalog_blank_search_keeps_everything(search):
    service, _ = _service(response=_MANIFEST)
    catalog = await service.get_catalog(search=search)
    assert [t["trigger_id"] for t in catalog["triggers"]] == ["protect:incoming.webhook"]
    assert [a["action_id"] for a in catalog["actions"]] == ["protect:notify"]


@pytest.mark.asyncio
async def test_get_catalog_search_does_not_match_missing_fields():
    manifest = {"trigger_categories": [{"id": "c", "triggers": [{"id": "t"}]}], "action_categories": []}
    service, _ = _service(response=manifest)
    catalog = await service.get_catalog(search="none")
    assert catalog["triggers"] == []
