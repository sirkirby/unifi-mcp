"""Alarm Manager tools for UniFi Protect MCP server.

Provides tools to arm/disarm the UniFi Protect Alarm Manager and list
configured arm profiles. Requires UniFi Protect 6.1+ with Alarm Manager
profiles configured in the Protect web UI.
"""

import logging
from typing import Annotated, Any, Dict, Optional

from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from unifi_core.confirmation import preview_response
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.models._actions import AlarmArmInput, AlarmDisarmInput
from unifi_core.protect.models.alarms import (
    profile_from_controller,
    profile_list_from_controller,
    status_from_controller,
)
from unifi_protect_mcp.runtime import alarm_manager, server

logger = logging.getLogger(__name__)


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
            profile_from_controller(p).model_dump(exclude_none=True)
            for p in (shaped_list.profiles or [])
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
            params = AlarmArmInput(profile_id=profile_id)
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
        params = AlarmDisarmInput()
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


logger.info(
    "Alarm tools registered: protect_alarm_list_profiles, protect_alarm_get_status, protect_alarm_arm, protect_alarm_disarm"
)
