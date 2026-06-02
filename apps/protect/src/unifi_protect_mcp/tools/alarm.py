"""Alarm Manager tools for UniFi Protect MCP server.

Provides tools to:
* arm/disarm the UniFi Protect Alarm Manager and list configured arm profiles
* CRUD alarm rules (automations) — list, get, update, create, delete

Requires UniFi Protect 6.1+ with Alarm Manager configured in the Protect
web UI. The rule CRUD endpoints are private REST under
``/proxy/protect/api/automations`` and not exposed by upstream uiprotect.
"""

import logging
from typing import Annotated, Any, Dict, Optional

from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from unifi_core.confirmation import preview_response, update_preview
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.merge import deep_merge
from unifi_core.protect.models._actions import (
    AlarmArmInput,
    AlarmCreateRuleInput,
    AlarmDeleteRuleInput,
    AlarmDisarmInput,
    AlarmGetRuleInput,
)
from unifi_core.protect.models.alarms import (
    profile_from_controller,
    profile_list_from_controller,
    rule_to_controller,
    status_from_controller,
)
from unifi_protect_mcp.runtime import alarm_facade, alarm_manager, server

logger = logging.getLogger(__name__)

# Standard MCP _meta key (reverse-DNS, project-owned) signalling that the active
# alarm backend is the limited one — AI-powered alarms are not visible without a
# SuperAdmin credential. Anchored in the MCP _meta convention (see tasks.py).
_ALARM_COVERAGE_META = "com.github.sirkirby.unifi-mcp/alarm-coverage"
_ALARM_COVERAGE_NOTICE = "AI-powered alarms are not included; viewing them requires a SuperAdmin credential."


@server.tool(
    name="protect_alarm_list_profiles",
    description=(
        "Lists all configured UniFi Protect Alarm Manager profiles with their id, "
        "name, activation delay, schedule count, and automation count. Use this "
        "to discover the arm profile id needed by protect_alarm_arm. Requires Protect "
        "6.1+ with Alarm Manager configured in the web UI."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_alarm_list_profiles() -> Dict[str, Any]:
    """List all arm profiles."""
    logger.info("protect_alarm_list_profiles tool called")
    try:
        profiles = await alarm_manager.list_arm_profiles()
        raw = {"profiles": profiles, "count": len(profiles)}
        shaped_list = profile_list_from_controller(raw)
        shaped_profiles = [
            profile_from_controller(p).model_dump(exclude_none=True) for p in (shaped_list.profiles or [])
        ]
        return {
            "success": True,
            "data": {**shaped_list.model_dump(exclude_none=True), "profiles": shaped_profiles},
        }
    except Exception as e:
        logger.error("Error listing arm profiles: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list arm profiles: {e}"}


@server.tool(
    name="protect_alarm_get_status",
    description=(
        "Returns the current armed/disarmed state of the UniFi Protect Alarm "
        "Manager, including the active profile, raw status string, armed-at "
        "timestamp, and any breach info. Use this to check whether the security "
        "system is currently active."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_alarm_get_status() -> Dict[str, Any]:
    """Get the current arm status."""
    logger.info("protect_alarm_get_status tool called")
    try:
        state = await alarm_manager.get_arm_state()
        raw = {**state, "profile_count": len(state.get("profiles") or [])}
        shaped = status_from_controller(raw)
        return {
            "success": True,
            "data": shaped.model_dump(exclude_none=True),
        }
    except Exception as e:
        logger.error("Error getting arm status: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get arm status: {e}"}


@server.tool(
    name="protect_alarm_arm",
    description=(
        "Arms the UniFi Protect Alarm Manager. When profile_id is provided, "
        "the system first selects that profile (PATCH arm) and then activates "
        "it (POST arm/enable). When omitted, the currently selected profile is "
        "used. Requires confirm=True to apply — otherwise returns a preview."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    permission_category="alarm",
    permission_action="update",
)
async def protect_alarm_arm(
    profile_id: Annotated[
        Optional[str],
        Field(
            description=(
                "Arm profile UUID from protect_alarm_list_profiles. Omit to use the currently selected profile."
            )
        ),
    ] = None,
    confirm: Annotated[
        bool,
        Field(description="When true, arms the system. When false (default), returns a preview."),
    ] = False,
) -> Dict[str, Any]:
    """Arm the Protect Alarm Manager."""
    logger.info("protect_alarm_arm tool called (profile_id=%s, confirm=%s)", profile_id, confirm)
    try:
        try:
            AlarmArmInput(profile_id=profile_id)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}
        if not confirm:
            preview_data = await alarm_manager.preview_arm(profile_id)
            return preview_response(
                action="update",
                resource_type="alarm_system",
                resource_id=preview_data["target_profile_id"],
                current_state=preview_data["current_state"],
                proposed_changes=preview_data["proposed_changes"],
                resource_name=preview_data["target_profile_name"] or preview_data["target_profile_id"],
            )

        result = await alarm_manager.arm(profile_id)
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error arming alarm: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to arm alarm: {e}"}


@server.tool(
    name="protect_alarm_disarm",
    description=(
        "Disarms the UniFi Protect Alarm Manager system-wide via POST "
        "arm/disable. No profile id is required (or accepted) by the disarm "
        "endpoint. Requires confirm=True to apply — otherwise returns a preview."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    permission_category="alarm",
    permission_action="update",
)
async def protect_alarm_disarm(
    confirm: Annotated[
        bool,
        Field(description="When true, disarms the system. When false (default), returns a preview."),
    ] = False,
) -> Dict[str, Any]:
    """Disarm the Protect Alarm Manager."""
    logger.info("protect_alarm_disarm tool called (confirm=%s)", confirm)
    try:
        AlarmDisarmInput()
        if not confirm:
            preview_data = await alarm_manager.preview_disarm()
            return preview_response(
                action="update",
                resource_type="alarm_system",
                resource_id=preview_data["active_profile_id"] or "system",
                current_state=preview_data["current_state"],
                proposed_changes=preview_data["proposed_changes"],
                resource_name=preview_data["active_profile_name"] or "alarm system",
            )

        result = await alarm_manager.disarm()
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error disarming alarm: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to disarm alarm: {e}"}


@server.tool(
    name="protect_alarm_list_rules",
    description=(
        "Lists every UniFi Protect alarm rule, including AI-powered alarms "
        "(e.g. AI Natural Language). Each rule is normalized to id, title, "
        "enabled, triggers, actions, scope, and stats. Use protect_alarm_get_rule "
        "for a single rule."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_alarm_list_rules() -> Dict[str, Any]:
    """List all alarm rules (version-agnostic; AI alarms included when accessible)."""
    logger.info("protect_alarm_list_rules tool called")
    try:
        rules, complete = await alarm_facade.list_rules()
        result: Dict[str, Any] = {"success": True, "data": {"rules": rules, "count": len(rules)}}
        if not complete:
            result["_meta"] = {_ALARM_COVERAGE_META: {"complete": False, "reason": _ALARM_COVERAGE_NOTICE}}
        return result
    except Exception as e:
        logger.error("Error listing alarm rules: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list alarm rules: {e}"}


@server.tool(
    name="protect_alarm_get_rule",
    description=(
        "Fetches a single UniFi Protect alarm rule by id (normalized: id, title, "
        "enabled, triggers, actions, scope, stats), including AI-powered alarms."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_alarm_get_rule(
    rule_id: Annotated[
        str,
        Field(description="Alarm rule id from protect_alarm_list_rules"),
    ],
) -> Dict[str, Any]:
    """Get a single alarm rule (version-agnostic)."""
    logger.info("protect_alarm_get_rule tool called (rule_id=%s)", rule_id)
    try:
        try:
            AlarmGetRuleInput(rule_id=rule_id)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}
        rule, complete = await alarm_facade.get_rule(rule_id)
        result: Dict[str, Any] = {"success": True, "data": rule}
        if not complete:
            result["_meta"] = {_ALARM_COVERAGE_META: {"complete": False, "reason": _ALARM_COVERAGE_NOTICE}}
        return result
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting alarm rule %s: %s", rule_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get alarm rule: {e}"}


@server.tool(
    name="protect_alarm_update_rule",
    description=(
        "Updates an alarm rule. Pass only the fields you want to change; the tool "
        "fetches the current rule, deep-merges your changes, and PATCHes the full "
        "body (Protect rejects partial bodies — fetch-merge-put is handled for you). "
        "Field keys may be snake_case or camelCase. Requires confirm=True to apply — "
        "otherwise returns a preview of the proposed changes."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    permission_category="alarm",
    permission_action="update",
)
async def protect_alarm_update_rule(
    rule_id: Annotated[str, Field(description="Alarm rule id to update")],
    fields: Annotated[
        Dict[str, Any],
        Field(
            description="Partial set of rule fields to change (e.g. name, enable, actions). Merged into the current rule."
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the update. When false (default), returns a preview."),
    ] = False,
) -> Dict[str, Any]:
    """Update an alarm rule via fetch-merge-put."""
    logger.info("protect_alarm_update_rule tool called (rule_id=%s, confirm=%s)", rule_id, confirm)
    try:
        field_data = fields.model_dump(exclude_unset=True) if hasattr(fields, "model_dump") else dict(fields)
        if not field_data:
            return {"success": False, "error": "No fields provided. Specify at least one field to update."}

        current = await alarm_manager.get_rule(rule_id)
        changes = rule_to_controller(field_data)
        if not confirm:
            return update_preview(
                resource_type="alarm_rule",
                resource_id=rule_id,
                resource_name=current.get("name") or rule_id,
                current_state={key: current.get(key) for key in changes},
                updates=changes,
            )

        merged = deep_merge(current, changes)
        result = await alarm_manager.update_rule(rule_id, merged)
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError, TypeError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating alarm rule %s: %s", rule_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update alarm rule: {e}"}


@server.tool(
    name="protect_alarm_create_rule",
    description=(
        "Creates a new alarm rule via POST. Body must be a full rule payload "
        "matching the Protect automations schema: name, enable, sources "
        "(scope), conditions (triggers), actions (webhook/etc), cooldown. "
        "The server assigns the rule id and returns the created rule. "
        "Body keys may be snake_case (as returned by protect_alarm_get_rule) "
        "or camelCase (controller-native); the tool normalizes to camelCase "
        "before POSTing, so the natural read-modify-write clone flow works. "
        "``actions`` must be a non-empty list — the controller will accept "
        "an empty actions list but the resulting rule cannot be opened in "
        "the Protect UI. "
        "Requires confirm=True to apply — otherwise returns a preview."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    permission_category="alarm",
    permission_action="create",
)
async def protect_alarm_create_rule(
    body: Annotated[
        Dict[str, Any],
        Field(description="Full alarm rule payload (see Protect automations schema)"),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, creates the rule. When false (default), returns a preview."),
    ] = False,
) -> Dict[str, Any]:
    """Create a new alarm rule."""
    logger.info("protect_alarm_create_rule tool called (confirm=%s)", confirm)
    try:
        try:
            AlarmCreateRuleInput(body=body)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}
        # Translate ONCE so the preview's "proposed" exactly matches the
        # body that would be POSTed on confirm (no snake/camel drift).
        translated = rule_to_controller(body)
        if not confirm:
            return preview_response(
                action="create",
                resource_type="alarm_rule",
                resource_id=translated.get("id") or "<server-assigned>",
                current_state={},
                proposed_changes=translated,
                resource_name=translated.get("name") or "new alarm rule",
            )

        result = await alarm_manager.create_rule(translated)
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError, TypeError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error creating alarm rule: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to create alarm rule: {e}"}


@server.tool(
    name="protect_alarm_delete_rule",
    description=(
        "Deletes an alarm rule (automation) by id. Requires confirm=True to "
        "apply — otherwise returns a preview showing the rule that would be "
        "deleted. Destructive — the rule and its configured webhook actions "
        "cannot be recovered through the API."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="alarm",
    permission_action="delete",
)
async def protect_alarm_delete_rule(
    rule_id: Annotated[str, Field(description="Alarm rule (automation) UUID to delete")],
    confirm: Annotated[
        bool,
        Field(description="When true, deletes the rule. When false (default), returns a preview."),
    ] = False,
) -> Dict[str, Any]:
    """Delete an alarm rule."""
    logger.info("protect_alarm_delete_rule tool called (rule_id=%s, confirm=%s)", rule_id, confirm)
    try:
        try:
            AlarmDeleteRuleInput(rule_id=rule_id)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}
        if not confirm:
            preview_data = await alarm_manager.preview_delete_rule(rule_id)
            return preview_response(
                action="delete",
                resource_type="alarm_rule",
                resource_id=rule_id,
                current_state={"name": preview_data["current_name"]},
                proposed_changes=preview_data["proposed_changes"],
                resource_name=preview_data["current_name"] or rule_id,
            )

        result = await alarm_manager.delete_rule(rule_id)
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error deleting alarm rule %s: %s", rule_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to delete alarm rule: {e}"}


logger.info(
    "Alarm tools registered: "
    "protect_alarm_list_profiles, protect_alarm_get_status, protect_alarm_arm, protect_alarm_disarm, "
    "protect_alarm_list_rules, protect_alarm_get_rule, protect_alarm_update_rule, "
    "protect_alarm_create_rule, protect_alarm_delete_rule"
)
