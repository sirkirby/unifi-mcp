"""Liveview tools for UniFi Protect MCP server.

Provides tools for listing, creating, and deleting liveview configurations.
Liveviews are multi-camera layout configurations for the Protect app and
UniFi Viewport devices.
"""

import logging
from typing import Annotated, Any, Dict, List

from mcp.types import ToolAnnotations
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.models._actions import DeleteLiveviewInput
from unifi_core.protect.models.liveviews import (
    Liveview,
    from_controller as liveview_from_controller,
    to_controller_create as liveview_to_controller_create,
)
from pydantic import Field, ValidationError

from unifi_protect_mcp.runtime import liveview_manager, server

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Read-only tools
# ---------------------------------------------------------------------------


@server.tool(
    name="protect_list_liveviews",
    description=(
        "Lists all liveview configurations from the Protect NVR. Each liveview "
        "defines a multi-camera layout with slots, camera assignments, and cycle "
        "settings. Shows name, layout grid size, slot count, camera count, and "
        "whether it is the default or global view."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_list_liveviews() -> Dict[str, Any]:
    """List all liveviews."""
    logger.info("protect_list_liveviews tool called")
    try:
        raw_liveviews = await liveview_manager.list_liveviews()
        liveviews = [liveview_from_controller(lv).model_dump(exclude_none=True) for lv in raw_liveviews]
        return {"success": True, "data": {"liveviews": liveviews, "count": len(liveviews)}}
    except Exception as e:
        logger.error("Error listing liveviews: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list liveviews: {e}"}


# ---------------------------------------------------------------------------
# Mutation tools
# ---------------------------------------------------------------------------


@server.tool(
    name="protect_create_liveview",
    description=(
        "Validates input for creating a new liveview with the given name and "
        "camera IDs. Note: liveview creation is not directly supported by the "
        "uiprotect Python API; this tool validates camera IDs and returns a "
        "preview. Use the Protect web UI to create liveviews."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False),
    permission_category="liveview",
    permission_action="create",
)
async def protect_create_liveview(
    name: Annotated[str, Field(description="Display name for the new liveview (e.g., 'Front Yard Cameras')")],
    camera_ids: Annotated[
        List[str],
        Field(
            description="List of camera UUIDs to include in the liveview (from protect_list_cameras). At least one required."
        ),
    ],
    confirm: Annotated[
        bool,
        Field(
            description="When true, attempts to create the liveview. When false (default), returns a validation preview. Note: creation is not supported via the API."
        ),
    ] = False,
) -> Dict[str, Any]:
    """Create a liveview (validation only -- API limitation)."""
    logger.info("protect_create_liveview called (name=%s, cameras=%d)", name, len(camera_ids))
    try:
        if not name:
            return {"success": False, "error": "Liveview name is required."}
        if not camera_ids:
            return {"success": False, "error": "At least one camera ID is required."}

        try:
            model = Liveview(name=name, cameras=camera_ids)
        except Exception as e:
            return {"success": False, "error": f"Invalid liveview input: {e}"}
        payload = liveview_to_controller_create(model)

        result = await liveview_manager.create_liveview(payload["name"], payload["camera_ids"])

        # Since creation is not supported via uiprotect, return info regardless of confirm
        return {"success": False, "error": result["message"], "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error creating liveview: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to create liveview: {e}"}


@server.tool(
    name="protect_delete_liveview",
    description=(
        "Validates a liveview for deletion by ID. Note: liveview deletion is not "
        "directly supported by the uiprotect Python API; this tool returns "
        "information about the liveview. Use the Protect web UI to delete liveviews."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False),
    permission_category="liveview",
    permission_action="delete",
)
async def protect_delete_liveview(
    liveview_id: Annotated[str, Field(description="Liveview UUID (from protect_list_liveviews)")],
    confirm: Annotated[
        bool,
        Field(
            description="When true, attempts the deletion. When false (default), returns liveview info. Note: deletion is not supported via the API."
        ),
    ] = False,
) -> Dict[str, Any]:
    """Delete a liveview (not supported via API)."""
    logger.info("protect_delete_liveview called for %s (confirm=%s)", liveview_id, confirm)
    try:
        try:
            params = DeleteLiveviewInput(liveview_id=liveview_id)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}
        result = await liveview_manager.delete_liveview(liveview_id)
        return {"success": False, "error": result["message"], "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error deleting liveview %s: %s", liveview_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to delete liveview: {e}"}


logger.info("Liveview tools registered: protect_list_liveviews, protect_create_liveview, protect_delete_liveview")
