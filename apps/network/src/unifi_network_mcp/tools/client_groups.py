"""
Client group tools for UniFi Network MCP server.

Client groups (network member groups) organize devices by MAC address
for use in OON policies, firewall rules, and other configurations.
"""

import json
import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.confirmation import create_preview, update_preview
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.models.client_group import (
    from_controller as cg_from_controller,
)
from unifi_core.network.models.client_group import (
    to_controller_update as cg_to_update,
)
from unifi_network_mcp.runtime import client_group_manager, server

logger = logging.getLogger(__name__)


@server.tool(
    name="unifi_list_client_groups",
    description="List client groups (network member groups). "
    "Groups organize devices by MAC address for use in OON policies and firewall rules.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_client_groups() -> Dict[str, Any]:
    """
    Lists all client groups configured on the controller.

    Returns:
        A dictionary containing:
        - success (bool): Indicates if the operation was successful.
        - count (int): Number of groups found.
        - groups (List[Dict]): List of groups with id, name, type, and members.
    """
    try:
        groups = await client_group_manager.get_client_groups()
        formatted = [cg_from_controller(g).model_dump(exclude_none=True) for g in groups]
        return {
            "success": True,
            "site": client_group_manager._connection.site,
            "count": len(formatted),
            "groups": formatted,
        }
    except Exception as e:
        logger.error("Error listing client groups: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list client groups: {e}"}


@server.tool(
    name="unifi_get_client_group_details",
    description="Get detailed configuration for a specific client group by ID.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_client_group_details(
    group_id: Annotated[str, Field(description="The unique identifier of the client group")],
) -> Dict[str, Any]:
    """
    Gets the detailed configuration of a specific client group.

    Args:
        group_id (str): The unique identifier of the client group.

    Returns:
        A dictionary containing the full group configuration.
    """
    if not group_id:
        return {"success": False, "error": "group_id is required"}
    try:
        group = await client_group_manager.get_client_group_by_id(group_id)
        return {
            "success": True,
            "group_id": group_id,
            "details": json.loads(json.dumps(group, default=str)),
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting client group %s: %s", group_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get client group {group_id}: {e}"}


@server.tool(
    name="unifi_create_client_group",
    description="Create a new client group (network member group). "
    "Groups organize devices by MAC address for use in OON policies and firewall rules. "
    "Requires confirmation.",
    permission_category="client_group",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_client_group(
    name: Annotated[str, Field(description="Descriptive name for the group (e.g., 'Kids All', 'Work Laptops')")],
    members: Annotated[
        list[str],
        Field(
            description="List of MAC addresses to include in the group (e.g., ['aa:bb:cc:dd:ee:ff', '11:22:33:44:55:66'])"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, creates the group. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """
    Creates a new client group.

    Args:
        name (str): Name of the group.
        members (list): List of MAC addresses.
        confirm (bool): Must be True to execute. False returns a preview.

    Returns:
        Preview of changes or the created group.
    """
    group_data = {
        "name": name,
        "members": members,
        "type": "CLIENTS",
    }

    if not confirm:
        return create_preview(
            resource_type="client_group",
            resource_data=group_data,
            resource_name=name,
        )

    try:
        result = await client_group_manager.create_client_group(group_data)
        if result:
            return {
                "success": True,
                "message": f"Client group '{name}' created successfully.",
                "group": json.loads(json.dumps(result, default=str)),
            }
        return {"success": False, "error": f"Failed to create client group '{name}'."}
    except Exception as e:
        logger.error("Error creating client group: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to create client group '{name}': {e}"}


@server.tool(
    name="unifi_update_client_group",
    description="Update an existing client group. Pass only the fields you want to change — "
    "current values are automatically preserved. Requires confirmation.",
    permission_category="client_group",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_client_group(
    group_id: Annotated[str, Field(description="The ID of the group to update")],
    group_data: Annotated[
        dict,
        Field(
            description="Dictionary of fields to update. Pass only the fields you want to change — "
            "current values are automatically preserved. "
            "Allowed keys: name (str), members (list of MAC addresses)"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, updates the group. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Updates an existing client group with partial data."""
    if not group_id:
        return {"success": False, "error": "group_id is required"}
    if not group_data:
        return {"success": False, "error": "group_data cannot be empty"}

    validated_data = cg_to_update(group_data)
    if not validated_data:
        return {"success": False, "error": "Update data is effectively empty or invalid."}

    if not confirm:
        return update_preview(
            resource_type="client_group",
            resource_id=group_id,
            resource_name=group_id,
            current_state={},
            updates=validated_data,
        )

    try:
        merged = await client_group_manager.update_client_group(group_id, validated_data)
        return {
            "success": True,
            "message": f"Client group '{merged.get('name', group_id)}' updated successfully.",
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating client group %s: %s", group_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update client group '{group_id}': {e}"}


@server.tool(
    name="unifi_delete_client_group",
    description="Delete a client group. Requires confirmation. "
    "WARNING: Deleting a group may affect OON policies and firewall rules that reference it.",
    permission_category="client_group",
    permission_action="delete",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def delete_client_group(
    group_id: Annotated[str, Field(description="The ID of the group to delete")],
    confirm: Annotated[
        bool,
        Field(description="When true, deletes the group. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """
    Deletes a client group.

    Args:
        group_id (str): The ID of the group to delete.
        confirm (bool): Must be True to execute.

    Returns:
        Preview or success/failure status.
    """
    if not confirm:
        return create_preview(
            resource_type="client_group",
            resource_data={"group_id": group_id},
            resource_name=group_id,
            warnings=["Deleting a group may affect OON policies and firewall rules that reference it."],
        )

    try:
        success = await client_group_manager.delete_client_group(group_id)
        if success:
            return {"success": True, "message": f"Client group '{group_id}' deleted successfully."}
        return {"success": False, "error": f"Failed to delete client group '{group_id}'."}
    except Exception as e:
        logger.error("Error deleting client group %s: %s", group_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to delete client group '{group_id}': {e}"}
