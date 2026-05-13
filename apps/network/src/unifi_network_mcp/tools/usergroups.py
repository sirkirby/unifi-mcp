"""
UniFi Network MCP user group tools.

This module provides MCP tools to manage user groups (bandwidth profiles) on a UniFi Network Controller.
"""

import logging
from typing import Annotated, Any, Dict, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.confirmation import create_preview, update_preview
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.models.client_group import usergroup_from_controller
from unifi_network_mcp.runtime import server, usergroup_manager

logger = logging.getLogger(__name__)


@server.tool(
    name="unifi_list_usergroups",
    description="""List all user groups (bandwidth profiles) for the current site.

User groups define bandwidth limits that can be applied to clients.
Each group specifies upload/download speed caps in Kbps.""",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_usergroups() -> Dict[str, Any]:
    """List all user groups."""
    try:
        groups = await usergroup_manager.get_usergroups()
        formatted_groups = [usergroup_from_controller(g).model_dump(exclude_none=True) for g in groups]

        return {
            "success": True,
            "site": usergroup_manager._connection.site,
            "count": len(formatted_groups),
            "usergroups": formatted_groups,
        }
    except Exception as e:
        logger.error("Error listing user groups: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list user groups: {e}"}


@server.tool(
    name="unifi_get_usergroup_details",
    description="Get detailed information about a specific user group by its ID",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_usergroup_details(
    group_id: Annotated[
        str, Field(description="Unique identifier (_id) of the user group (from unifi_list_usergroups)")
    ],
) -> Dict[str, Any]:
    """Get details for a specific user group."""
    try:
        group = await usergroup_manager.get_usergroup_details(group_id)
        return {
            "success": True,
            "site": usergroup_manager._connection.site,
            "usergroup": group,
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting user group details for %s: %s", group_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get user group details for {group_id}: {e}"}


@server.tool(
    name="unifi_create_usergroup",
    description="""Create a new user group (bandwidth profile) with optional speed limits.

Bandwidth limits are specified in Kbps. Use -1 for unlimited.
User groups can be assigned to clients to enforce bandwidth policies.""",
    permission_category="usergroups",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_usergroup(
    name: Annotated[str, Field(description="Name for the user group / bandwidth profile")],
    down_limit_kbps: Annotated[
        Optional[int],
        Field(
            description="Download speed limit in Kbps (e.g., 10000 for 10 Mbps). Use -1 for unlimited. Omit to leave uncapped"
        ),
    ] = None,
    up_limit_kbps: Annotated[
        Optional[int],
        Field(
            description="Upload speed limit in Kbps (e.g., 5000 for 5 Mbps). Use -1 for unlimited. Omit to leave uncapped"
        ),
    ] = None,
    confirm: Annotated[
        bool,
        Field(description="When true, creates the user group. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Create a new user group."""
    if not name or not name.strip():
        return {"success": False, "error": "Name is required."}

    if not confirm:
        resource_data = {
            "name": name,
        }
        if up_limit_kbps is not None:
            resource_data["up_limit_kbps"] = up_limit_kbps
        if down_limit_kbps is not None:
            resource_data["down_limit_kbps"] = down_limit_kbps

        return create_preview(
            resource_type="usergroup",
            resource_data=resource_data,
            resource_name=name,
        )

    try:
        group = await usergroup_manager.create_usergroup(
            name=name.strip(),
            down_limit_kbps=down_limit_kbps,
            up_limit_kbps=up_limit_kbps,
        )

        if group:
            return {
                "success": True,
                "message": f"User group '{name}' created successfully.",
                "site": usergroup_manager._connection.site,
                "usergroup": group,
            }
        return {"success": False, "error": "Failed to create user group."}
    except Exception as e:
        logger.error("Error creating user group: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to create user group: {e}"}


@server.tool(
    name="unifi_update_usergroup",
    description="""Update an existing user group's name or bandwidth limits.

Use -1 for unlimited bandwidth. Changes affect all clients assigned to this group.""",
    permission_category="usergroups",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_usergroup(
    group_id: Annotated[
        str, Field(description="Unique identifier (_id) of the user group to update (from unifi_list_usergroups)")
    ],
    name: Annotated[Optional[str], Field(description="New name for the user group")] = None,
    down_limit_kbps: Annotated[
        Optional[int],
        Field(description="New download speed limit in Kbps. Use -1 for unlimited"),
    ] = None,
    up_limit_kbps: Annotated[
        Optional[int],
        Field(description="New upload speed limit in Kbps. Use -1 for unlimited"),
    ] = None,
    confirm: Annotated[
        bool,
        Field(description="When true, applies the update. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Update an existing user group."""
    # Validate that at least one update is provided
    if all(v is None for v in [name, down_limit_kbps, up_limit_kbps]):
        return {
            "success": False,
            "error": "At least one field must be provided (name, down_limit_kbps, or up_limit_kbps).",
        }

    updates = {}
    if name is not None:
        updates["name"] = name
    if up_limit_kbps is not None:
        updates["up_limit_kbps"] = up_limit_kbps
    if down_limit_kbps is not None:
        updates["down_limit_kbps"] = down_limit_kbps

    if not confirm:
        return update_preview(
            resource_type="usergroup",
            resource_id=group_id,
            resource_name=group_id,
            current_state={},
            updates=updates,
        )

    try:
        success = await usergroup_manager.update_usergroup(
            group_id=group_id,
            name=name.strip() if name else None,
            down_limit_kbps=down_limit_kbps,
            up_limit_kbps=up_limit_kbps,
        )

        if success:
            return {
                "success": True,
                "message": f"User group {group_id} updated successfully.",
                "updates": updates,
            }
        return {"success": False, "error": f"Failed to update user group {group_id}."}
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating user group %s: %s", group_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update user group {group_id}: {e}"}
