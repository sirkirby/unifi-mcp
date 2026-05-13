"""Door tools for UniFi Access MCP server.

Provides tools for listing, inspecting, locking, and unlocking doors.
"""

import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from unifi_access_mcp.runtime import door_manager, server
from unifi_core.access.models._actions import LockDoorInput, UnlockDoorInput
from unifi_core.access.models.doors import (
    door_from_controller,
    door_group_from_controller,
    door_status_from_controller,
)
from unifi_core.confirmation import preview_response
from unifi_core.exceptions import UniFiNotFoundError

logger = logging.getLogger(__name__)


@server.tool(
    name="access_list_doors",
    description=(
        "Lists all doors managed by the Access controller with their name, "
        "lock state, and connection status. Use to get an overview of all doors."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="door",
    permission_action="read",
    auth="either",
)
async def access_list_doors(
    compact: Annotated[
        bool,
        Field(
            description=(
                "When true, strips thumbnail, extras, and simplifies nested device details "
                "(~70% smaller). Recommended for overviews and summaries."
            )
        ),
    ] = False,
) -> Dict[str, Any]:
    """List all doors."""
    logger.info("access_list_doors tool called (compact=%s)", compact)
    try:
        raw_doors = await door_manager.list_doors(compact=compact)
        doors = [door_from_controller(d).model_dump(exclude_none=True) for d in raw_doors]
        return {"success": True, "data": {"doors": doors, "count": len(doors)}}
    except Exception as e:
        logger.error("Error listing doors: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list doors: {e}"}


@server.tool(
    name="access_get_door",
    description=(
        "Returns detailed information for a single door including lock state, configuration, and connected devices."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="door",
    permission_action="read",
    auth="either",
)
async def access_get_door(
    door_id: Annotated[str, Field(description="Door UUID (from access_list_doors)")],
) -> Dict[str, Any]:
    """Get detailed door information by ID."""
    logger.info("access_get_door tool called for %s", door_id)
    try:
        raw = await door_manager.get_door(door_id)
        detail = door_from_controller(raw).model_dump(exclude_none=True)
        return {"success": True, "data": detail}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting door %s: %s", door_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get door: {e}"}


@server.tool(
    name="access_unlock_door",
    description=(
        "Unlock a door for a specified duration. This is a physical real-world action. "
        "Requires confirm=true to execute. Default duration is 2 seconds."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False),
    permission_category="door",
    permission_action="update",
    auth="either",
)
async def access_unlock_door(
    door_id: Annotated[str, Field(description="Door UUID (from access_list_doors)")],
    duration: Annotated[int, Field(description="Unlock duration in seconds (default 2)")] = 2,
    confirm: Annotated[
        bool,
        Field(description="When true, executes the unlock. When false (default), returns a preview."),
    ] = False,
) -> Dict[str, Any]:
    """Unlock a door with preview/confirm."""
    logger.info("access_unlock_door tool called for %s (duration=%s, confirm=%s)", door_id, duration, confirm)
    try:
        try:
            params = UnlockDoorInput(door_id=door_id, duration=duration)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}
        door_id = params.door_id
        duration = params.duration

        if confirm:
            result = await door_manager.apply_unlock_door(door_id, duration=duration)
            return {"success": True, "data": result}

        preview_data = await door_manager.unlock_door(door_id, duration=duration)
        return preview_response(
            action="unlock",
            resource_type="door",
            resource_id=door_id,
            current_state=preview_data["current_state"],
            proposed_changes=preview_data["proposed_changes"],
            resource_name=preview_data.get("door_name"),
            warnings=["This will physically unlock a door. Ensure this is intentional."],
        )
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error unlocking door %s: %s", door_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to unlock door: {e}"}


@server.tool(
    name="access_lock_door",
    description=(
        "Lock a door immediately. This is a physical real-world action. "
        "Requires confirm=true to execute. Uses the Access API client when available, with local proxy fallback."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False),
    permission_category="door",
    permission_action="update",
    auth="local_only",
)
async def access_lock_door(
    door_id: Annotated[str, Field(description="Door UUID (from access_list_doors)")],
    confirm: Annotated[
        bool,
        Field(description="When true, executes the lock. When false (default), returns a preview."),
    ] = False,
) -> Dict[str, Any]:
    """Lock a door with preview/confirm."""
    logger.info("access_lock_door tool called for %s (confirm=%s)", door_id, confirm)
    try:
        try:
            params = LockDoorInput(door_id=door_id)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}
        door_id = params.door_id

        if confirm:
            result = await door_manager.apply_lock_door(door_id)
            return {"success": True, "data": result}

        preview_data = await door_manager.lock_door(door_id)
        return preview_response(
            action="lock",
            resource_type="door",
            resource_id=door_id,
            current_state=preview_data["current_state"],
            proposed_changes=preview_data["proposed_changes"],
            resource_name=preview_data.get("door_name"),
        )
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error locking door %s: %s", door_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to lock door: {e}"}


@server.tool(
    name="access_get_door_status",
    description=(
        "Returns the current lock and position status for a single door. "
        "Lightweight alternative to access_get_door when you only need state info."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="door",
    permission_action="read",
    auth="either",
)
async def access_get_door_status(
    door_id: Annotated[str, Field(description="Door UUID (from access_list_doors)")],
) -> Dict[str, Any]:
    """Get current door lock/position status."""
    logger.info("access_get_door_status tool called for %s", door_id)
    try:
        raw = await door_manager.get_door_status(door_id)
        status = door_status_from_controller(raw).model_dump(exclude_none=True)
        return {"success": True, "data": status}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting door status %s: %s", door_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get door status: {e}"}


@server.tool(
    name="access_list_door_groups",
    description=(
        "Lists all door groups configured on the Access controller. "
        "Door groups organize doors for policy assignment. Only available via local proxy session."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="door",
    permission_action="read",
    auth="local_only",
)
async def access_list_door_groups() -> Dict[str, Any]:
    """List all door groups."""
    logger.info("access_list_door_groups tool called")
    try:
        raw_groups = await door_manager.list_door_groups()
        groups = [door_group_from_controller(g).model_dump(exclude_none=True) for g in raw_groups]
        return {"success": True, "data": {"door_groups": groups, "count": len(groups)}}
    except Exception as e:
        logger.error("Error listing door groups: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list door groups: {e}"}


logger.info(
    "Door tools registered: access_list_doors, access_get_door, access_unlock_door, "
    "access_lock_door, access_get_door_status, access_list_door_groups"
)
