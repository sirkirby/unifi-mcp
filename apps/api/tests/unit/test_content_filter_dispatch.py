"""Content filter action translation and typed read symmetry."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_api.graphql.types.network.content_filter import ContentFilter
from unifi_api.serializers.network.content_filter import ContentFilterMutationAckSerializer
from unifi_api.services.actions import MutationPreview, dispatch_action
from unifi_api.services.dispatch_overrides import DISPATCH_ARG_TRANSLATORS
from unifi_api.services.manifest import ManifestRegistry, ToolEntry
from unifi_core.network.managers.content_filter_manager import ContentFilterManager


def test_create_action_uses_core_scope_validation() -> None:
    translator = DISPATCH_ARG_TRANSLATORS["unifi_create_content_filter"]
    data = {"name": "Kids", "network_ids": ["net"], "blocked_categories": ["FAMILY"], "schedule_days": ["mon"]}
    assert translator({"filter_data": data}) == (
        (),
        {"filter_data": {**data, "enabled": False, "schedule_mode": "ALWAYS", "schedule_time_all_day": True}},
    )
    with pytest.raises(ValueError, match="Exactly one"):
        translator({"filter_data": {"name": "Kids", "blocked_categories": ["FAMILY"]}})
    with pytest.raises(ValueError, match="Exactly one"):
        translator({"filter_data": {**data, "client_macs": ["aa:bb:cc:dd:ee:ff"]}})
    with pytest.raises(ValueError, match="blocked_categories"):
        translator({"filter_data": {"name": "Kids", "network_ids": ["net"]}})


@pytest.mark.asyncio
async def test_api_create_preview_shows_disabled_default() -> None:
    entry = ToolEntry(
        name="unifi_create_content_filter",
        product="network",
        category="content_filter",
        manager="content_filter_manager",
        method="create_content_filter",
        permission_action="create",
        read_only_hint=False,
        input_schema={"type": "object", "properties": {"filter_data": {"type": "object"}}},
    )
    factory = MagicMock()
    result = await dispatch_action(
        registry=ManifestRegistry({entry.name: entry}),
        factory=factory,
        session=MagicMock(),
        tool_name=entry.name,
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={"filter_data": {"name": "Kids", "network_ids": ["net"], "blocked_categories": ["FAMILY"]}},
        confirm=False,
    )
    assert isinstance(result, MutationPreview)
    assert result.payload["preview"]["will_create"]["filter_data"]["enabled"] is False
    assert result.payload["preview"]["will_create"]["filter_data"]["schedule_mode"] == "ALWAYS"
    assert result.payload["preview"]["will_create"]["filter_data"]["schedule_days"] == []
    assert result.payload["preview"]["will_create"]["filter_data"]["schedule_time_all_day"] is True
    factory.get_domain_manager.assert_not_called()


def test_api_create_preserves_explicit_schedule_choice() -> None:
    data = {
        "name": "Kids",
        "network_ids": ["net"],
        "blocked_categories": ["FAMILY"],
        "schedule_mode": "EVERY_WEEK",
        "schedule_days": ["mon"],
        "schedule_time_all_day": False,
    }
    _, kwargs = DISPATCH_ARG_TRANSLATORS["unifi_create_content_filter"]({"filter_data": data})
    assert kwargs["filter_data"]["schedule_mode"] == "EVERY_WEEK"
    assert kwargs["filter_data"]["schedule_days"] == ["mon"]
    assert kwargs["filter_data"]["schedule_time_all_day"] is False


@pytest.mark.asyncio
async def test_create_action_serializes_list_response_as_structured_profile() -> None:
    connection = MagicMock()
    connection.ensure_connected = AsyncMock(return_value=True)
    connection.request = AsyncMock(
        return_value=[
            {
                "_id": "cf-new",
                "name": "Kids",
                "enabled": False,
                "categories": ["FAMILY"],
                "network_ids": ["net"],
                "schedule": {"mode": "EVERY_WEEK", "repeat_on_days": ["mon"]},
            }
        ]
    )
    manager = ContentFilterManager(connection)
    _, kwargs = DISPATCH_ARG_TRANSLATORS["unifi_create_content_filter"](
        {"filter_data": {"name": "Kids", "network_ids": ["net"], "categories": ["FAMILY"]}}
    )
    created = await manager.create_content_filter(**kwargs)
    result = ContentFilterMutationAckSerializer().serialize_action(created, tool_name="unifi_create_content_filter")
    assert result["success"] is True
    assert result["data"]["id"] == "cf-new"
    assert result["data"]["blocked_categories"] == ["FAMILY"]
    assert result["data"]["schedule_mode"] == "EVERY_WEEK"
    assert result["data"]["schedule_days"] == ["mon"]
    assert "_id" not in result["data"]
    assert "categories" not in result["data"]
    assert "schedule" not in result["data"]


def test_create_action_uncertain_result_is_failure() -> None:
    uncertain = {"success": False, "uncertain": True, "error": "List profiles before retrying."}
    result = ContentFilterMutationAckSerializer().serialize_action(uncertain, tool_name="unifi_create_content_filter")
    assert result == uncertain


def test_update_action_validates_and_translates_schedule() -> None:
    translator = DISPATCH_ARG_TRANSLATORS["unifi_update_content_filter"]
    args = {"filter_id": "cf", "filter_data": {"schedule_mode": "EVERY_WEEK", "schedule_days": ["mon"]}}
    assert translator(args) == (
        (),
        {"filter_id": "cf", "update_data": {"schedule": {"mode": "EVERY_WEEK", "repeat_on_days": ["mon"]}}},
    )
    with pytest.raises(ValueError, match="schedule_days"):
        translator({"filter_id": "cf", "filter_data": {"schedule_days": ["MONDAY"]}})
    with pytest.raises(ValueError, match="Unknown"):
        translator({"filter_id": "cf", "filter_data": {"schedule": {"time_from": "09:00"}}})
    assert translator({"filter_id": "cf", "filter_data": {"categories": ["FAMILY"]}}) == (
        (),
        {"filter_id": "cf", "update_data": {"categories": ["FAMILY"]}},
    )
    for update in ({"name": " "}, {"blocked_categories": []}, {"categories": []}):
        with pytest.raises(ValueError):
            translator({"filter_id": "cf", "filter_data": update})


def test_graphql_read_exposes_flattened_schedule() -> None:
    schedule = {"mode": "ONE_TIME_ONLY", "date_start": "2026-08-01", "date_end": "2026-08-02"}
    result = ContentFilter.from_manager_output({"_id": "cf", "schedule": schedule}).to_dict()
    assert result["schedule_mode"] == "ONE_TIME_ONLY"
    assert result["schedule_date_start"] == "2026-08-01"
    assert result["schedule_date_end"] == "2026-08-02"
