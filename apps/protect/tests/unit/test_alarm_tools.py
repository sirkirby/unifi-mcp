"""Tests for Protect alarm MCP tool wrappers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_list_profiles_delegates_to_alarm_facade():
    from unifi_protect_mcp.tools import alarm

    facade = MagicMock()
    profile = {
        "id": "uuid-1",
        "name": "Away",
        "state": "armed",
        "state_set_at": "2026-09-04T12:00:00Z",
        "automation_count": 2,
        "id_family": "alarm_manager_v2",
        "arm_compatible": False,
    }
    facade.list_profiles = AsyncMock(return_value=([profile], True))
    legacy = MagicMock()
    legacy.list_arm_profiles = AsyncMock()

    with (
        patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade),
    ):
        result = await alarm.protect_alarm_list_profiles()

    assert result == {
        "success": True,
        "data": {"profiles": [profile], "count": 1},
    }
    facade.list_profiles.assert_awaited_once_with()
    legacy.list_arm_profiles.assert_not_called()


@pytest.mark.asyncio
async def test_list_profiles_surfaces_coverage_meta_when_legacy_serves():
    from unifi_protect_mcp.tools import alarm

    facade = MagicMock()
    facade.list_profiles = AsyncMock(
        return_value=(
            [{"id": "legacy-id", "name": "Away", "id_family": "legacy", "arm_compatible": True}],
            False,
        )
    )

    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await alarm.protect_alarm_list_profiles()

    assert result["success"] is True
    assert result["data"]["profiles"][0]["id"] == "legacy-id"
    assert result["_meta"][alarm._ALARM_COVERAGE_META] == {
        "complete": False,
        "reason": alarm._ALARM_PROFILE_COVERAGE_NOTICE,
    }


@pytest.mark.asyncio
async def test_update_rule_confirm_delegates_to_alarm_facade():
    from unifi_protect_mcp.tools import alarm

    facade = MagicMock()
    facade.update_rule = AsyncMock(return_value=({"id": "uuid-1", "title": "Updated"}, True))
    legacy = MagicMock()
    legacy.update_rule = AsyncMock()

    with (
        patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade),
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
    assert result["action"] == "delete"
    assert result["resource_type"] == "alarm_rule"
    assert result["resource_id"] == "uuid-1"
    assert result["resource_name"] == "Rule"
    assert result["preview"]["will_delete"] == {"rule_id": "uuid-1", "title": "Rule"}
    facade.get_rule.assert_awaited_once_with("uuid-1")


@pytest.mark.asyncio
async def test_update_rule_preview_rejects_empty_actions():
    from unifi_protect_mcp.tools import alarm

    result = await alarm.protect_alarm_update_rule("uuid-1", {"actions": []}, confirm=False)

    assert result["success"] is False
    assert "actions must be a non-empty list" in result["error"]


@pytest.mark.asyncio
async def test_get_status_delegates_to_global_facade():
    from unifi_protect_mcp.tools.alarm import protect_alarm_get_status

    facade = MagicMock()
    facade.get_arm_state = AsyncMock(return_value={"armed": True, "status": "breached", "profiles": [{}]})
    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await protect_alarm_get_status()
    assert result["success"] is True
    assert result["data"]["armed"] is True
    assert result["data"]["status"] == "breached"
    assert result["data"]["profile_count"] == 1


@pytest.mark.asyncio
async def test_arm_confirm_delegates_to_alarm_facade():
    from unifi_protect_mcp.tools.alarm import protect_alarm_arm

    facade = MagicMock()
    facade.arm = AsyncMock(return_value={"armed": True, "profile_id": "uuid-1", "state": "arming"})
    facade.preview_arm = AsyncMock()
    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await protect_alarm_arm(profile_id="uuid-1", confirm=True)

    facade.arm.assert_awaited_once_with("uuid-1")
    facade.preview_arm.assert_not_called()
    assert result == {"success": True, "data": {"armed": True, "profile_id": "uuid-1", "state": "arming"}}


@pytest.mark.asyncio
async def test_arm_preview_delegates_to_alarm_facade():
    from unifi_protect_mcp.tools.alarm import protect_alarm_arm

    facade = MagicMock()
    facade.arm = AsyncMock()
    facade.preview_arm = AsyncMock(
        return_value={
            "target_profile_id": "uuid-1",
            "target_profile_name": "Arm All",
            "current_state": {"armed": False, "active_profile_id": None, "status": "disarmed"},
            "proposed_changes": {"armed": True, "active_profile_id": "uuid-1"},
        }
    )
    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await protect_alarm_arm(profile_id="uuid-1")

    facade.preview_arm.assert_awaited_once_with("uuid-1")
    facade.arm.assert_not_called()
    assert result["success"] is True
    assert result["requires_confirmation"] is True


@pytest.mark.asyncio
async def test_arm_surfaces_verification_failure_as_error():
    from unifi_protect_mcp.tools.alarm import protect_alarm_arm

    facade = MagicMock()
    facade.arm = AsyncMock(side_effect=ValueError("still 'disarmed'"))
    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await protect_alarm_arm(profile_id="uuid-1", confirm=True)

    assert result == {"success": False, "error": "still 'disarmed'"}


@pytest.mark.asyncio
async def test_disarm_confirm_delegates_to_alarm_facade_with_profile():
    from unifi_protect_mcp.tools.alarm import protect_alarm_disarm

    facade = MagicMock()
    facade.disarm = AsyncMock(return_value={"armed": False, "profiles": []})
    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await protect_alarm_disarm(profile_id="uuid-1", confirm=True)

    facade.disarm.assert_awaited_once_with("uuid-1")
    assert result == {"success": True, "data": {"armed": False, "profiles": []}}


@pytest.mark.asyncio
async def test_disarm_preview_delegates_to_alarm_facade():
    from unifi_protect_mcp.tools.alarm import protect_alarm_disarm

    facade = MagicMock()
    facade.disarm = AsyncMock()
    facade.preview_disarm = AsyncMock(
        return_value={
            "active_profile_id": "uuid-1",
            "active_profile_name": "Arm Night",
            "current_state": {"armed": True, "status": "armed", "profiles": []},
            "proposed_changes": {"armed": False},
        }
    )
    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await protect_alarm_disarm()

    facade.preview_disarm.assert_awaited_once_with(None)
    facade.disarm.assert_not_called()
    assert result["success"] is True
    assert result["requires_confirmation"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", ["", "   ", "\t"])
@pytest.mark.parametrize("confirm", [True, False])
async def test_arm_rejects_blank_profile_id(blank, confirm):
    from unifi_protect_mcp.tools.alarm import protect_alarm_arm

    facade = MagicMock()
    facade.arm = AsyncMock()
    facade.preview_arm = AsyncMock()
    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await protect_alarm_arm(profile_id=blank, confirm=confirm)

    assert result["success"] is False
    assert "must not be blank" in result["error"]
    facade.arm.assert_not_called()
    facade.preview_arm.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", ["", "   ", "\t"])
@pytest.mark.parametrize("confirm", [True, False])
async def test_disarm_rejects_blank_profile_id_instead_of_disarming_everything(blank, confirm):
    from unifi_protect_mcp.tools.alarm import protect_alarm_disarm

    facade = MagicMock()
    facade.disarm = AsyncMock()
    facade.preview_disarm = AsyncMock()
    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await protect_alarm_disarm(profile_id=blank, confirm=confirm)

    assert result["success"] is False
    assert "must not be blank" in result["error"]
    facade.disarm.assert_not_called()
    facade.preview_disarm.assert_not_called()


@pytest.mark.asyncio
async def test_disarm_without_profile_id_still_targets_every_active_profile():
    from unifi_protect_mcp.tools.alarm import protect_alarm_disarm

    facade = MagicMock()
    facade.disarm = AsyncMock(return_value={"armed": False, "profiles": []})
    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await protect_alarm_disarm(confirm=True)

    facade.disarm.assert_awaited_once_with(None)
    assert result["success"] is True


@pytest.mark.asyncio
async def test_get_catalog_returns_facade_catalog():
    from unifi_protect_mcp.tools import alarm

    catalog = {
        "triggers": [{"trigger_id": "protect:incoming.webhook", "title": "Webhook"}],
        "actions": [{"action_id": "protect:notify", "title": "Notify"}],
        "scope": {"mode": "include"},
    }
    facade = MagicMock()
    facade.list_catalog = AsyncMock(return_value=catalog)

    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await alarm.protect_alarm_get_catalog(search="webhook", include_schemas=True)

    assert result == {"success": True, "data": catalog}
    facade.list_catalog.assert_awaited_once_with(search="webhook", include_schemas=True)


@pytest.mark.asyncio
async def test_get_catalog_defaults_to_no_filter_and_no_schemas():
    from unifi_protect_mcp.tools import alarm

    facade = MagicMock()
    facade.list_catalog = AsyncMock(return_value={"triggers": [], "actions": [], "scope": {}})

    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        await alarm.protect_alarm_get_catalog()

    facade.list_catalog.assert_awaited_once_with(search=None, include_schemas=False)


@pytest.mark.asyncio
async def test_get_catalog_reports_failure():
    from unifi_protect_mcp.tools import alarm

    facade = MagicMock()
    facade.list_catalog = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await alarm.protect_alarm_get_catalog()

    assert result == {"success": False, "error": "Failed to get alarm catalog: boom"}


@pytest.mark.asyncio
async def test_fire_webhook_without_confirm_previews_and_does_not_fire():
    from unifi_protect_mcp.tools import alarm

    facade = MagicMock()
    facade.fire_webhook = AsyncMock()

    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await alarm.protect_alarm_fire_webhook(trigger_id="door-test")

    assert result["requires_confirmation"] is True
    assert result["resource_id"] == "door-test"
    assert result["preview"]["proposed"] == {"fire": True}
    facade.fire_webhook.assert_not_called()


@pytest.mark.asyncio
async def test_fire_webhook_confirm_fires_through_facade():
    from unifi_protect_mcp.tools import alarm

    facade = MagicMock()
    facade.fire_webhook = AsyncMock(return_value={"fired": True, "trigger_id": "door-test"})

    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await alarm.protect_alarm_fire_webhook(trigger_id="door-test", confirm=True)

    facade.fire_webhook.assert_awaited_once_with("door-test")
    assert result == {"success": True, "data": {"fired": True, "trigger_id": "door-test"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm", [False, True])
@pytest.mark.parametrize("trigger_id", ["", "  "])
async def test_fire_webhook_rejects_blank_trigger_id(trigger_id, confirm):
    from unifi_protect_mcp.tools import alarm

    facade = MagicMock()
    facade.fire_webhook = AsyncMock()

    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await alarm.protect_alarm_fire_webhook(trigger_id=trigger_id, confirm=confirm)

    assert result == {"success": False, "error": "Invalid input: Value error, trigger_id is required"}
    facade.fire_webhook.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm", [False, True])
@pytest.mark.parametrize("trigger_id", [".", "..", "hook7f3a/x", "hook7f3a?x", "hook7f3a%2F", "hook7f3a\nx"])
async def test_fire_webhook_refuses_an_id_that_is_not_one_path_segment(trigger_id, confirm):
    from unifi_protect_mcp.tools import alarm

    facade = MagicMock()
    facade.fire_webhook = AsyncMock()

    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await alarm.protect_alarm_fire_webhook(trigger_id=trigger_id, confirm=confirm)

    assert result["success"] is False
    assert "must not be" in result["error"]
    assert "hook7f3a" not in result["error"]
    facade.fire_webhook.assert_not_called()


@pytest.mark.asyncio
async def test_fire_webhook_surfaces_refusal():
    from unifi_protect_mcp.tools import alarm

    facade = MagicMock()
    facade.fire_webhook = AsyncMock(side_effect=ValueError("requires an API key"))

    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await alarm.protect_alarm_fire_webhook(trigger_id="door-test", confirm=True)

    assert result == {"success": False, "error": "requires an API key"}


@pytest.mark.asyncio
async def test_get_catalog_permission_error_is_returned_as_is():
    from unifi_core.protect.managers.alarm_manager_service import AlarmManagerPermissionError
    from unifi_protect_mcp.tools import alarm

    facade = MagicMock()
    facade.list_catalog = AsyncMock(side_effect=AlarmManagerPermissionError("requires SuperAdmin"))

    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await alarm.protect_alarm_get_catalog()

    assert result == {"success": False, "error": "requires SuperAdmin"}


@pytest.mark.asyncio
async def test_fire_webhook_unexpected_error_is_reported():
    from unifi_protect_mcp.tools import alarm

    facade = MagicMock()
    facade.fire_webhook = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await alarm.protect_alarm_fire_webhook(trigger_id="door-test", confirm=True)

    assert result == {"success": False, "error": "Failed to fire alarm webhook: boom"}


@pytest.mark.asyncio
async def test_fire_webhook_rejects_non_string_trigger_id():
    from unifi_protect_mcp.tools import alarm

    facade = MagicMock()
    facade.fire_webhook = AsyncMock()

    with patch("unifi_protect_mcp.tools.alarm.alarm_facade", facade):
        result = await alarm.protect_alarm_fire_webhook(trigger_id=None, confirm=True)

    assert result["success"] is False
    assert result["error"].startswith("Invalid input:")
    facade.fire_webhook.assert_not_called()


def test_create_rule_description_says_scope_needs_mode():
    import json
    from pathlib import Path

    import unifi_protect_mcp

    manifest = json.loads((Path(unifi_protect_mcp.__file__).parent / "tools_manifest.json").read_text())
    tool = next(t for t in manifest["tools"] if t["name"] == "protect_alarm_create_rule")
    assert "scope" in tool["description"] and "{mode, data}" in tool["description"]
    assert "protect_alarm_get_catalog" in tool["description"]


def test_get_catalog_description_says_schemas_are_opt_in():
    import json
    from pathlib import Path

    import unifi_protect_mcp

    manifest = json.loads((Path(unifi_protect_mcp.__file__).parent / "tools_manifest.json").read_text())
    tool = next(t for t in manifest["tools"] if t["name"] == "protect_alarm_get_catalog")
    assert "options_schema and scope are left out unless include_schemas" in tool["description"]


def test_fire_webhook_description_tells_its_id_from_a_catalog_trigger_id():
    import json
    from pathlib import Path

    import unifi_protect_mcp

    manifest = json.loads((Path(unifi_protect_mcp.__file__).parent / "tools_manifest.json").read_text())
    tool = next(t for t in manifest["tools"] if t["name"] == "protect_alarm_fire_webhook")
    field = tool["schema"]["input"]["properties"]["trigger_id"]["description"]
    assert "data.webhook" in field
    assert "protect_alarm_get_catalog" in field
    assert "not a catalog trigger_id" in tool["description"]
