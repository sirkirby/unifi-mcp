"""
OON (Object-Oriented Network) policy tools for UniFi Network MCP server.

OON policies provide high-level network access control including internet
scheduling, application blocking, QoS, and policy-based routing. Policies
can target specific client MACs or client groups.
"""

import json
import logging
from typing import Annotated, Any, Dict, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.confirmation import create_preview, update_preview
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.models.oon import (
    from_controller as oon_from_controller,
)
from unifi_core.network.models.oon import (
    to_controller_update as oon_to_update,
)
from unifi_network_mcp.runtime import oon_manager, server

logger = logging.getLogger(__name__)


@server.tool(
    name="unifi_list_oon_policies",
    description="List OON (Object-Oriented Network) policies. "
    "These policies control internet access schedules (bedtime blackouts), "
    "application blocking (social media, streaming), QoS, and policy-based routing.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_oon_policies() -> Dict[str, Any]:
    """
    Lists all OON policies configured on the controller.

    Returns:
        A dictionary containing:
        - success (bool): Indicates if the operation was successful.
        - count (int): Number of policies found.
        - policies (List[Dict]): List of policies with summary info.
    """
    try:
        policies = await oon_manager.get_oon_policies()
        formatted = [oon_from_controller(p).model_dump(exclude_none=True) for p in policies]
        return {
            "success": True,
            "site": oon_manager._connection.site,
            "count": len(formatted),
            "policies": formatted,
        }
    except Exception as e:
        logger.error("Error listing OON policies: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list OON policies: {e}"}


@server.tool(
    name="unifi_get_oon_policy_details",
    description="Get detailed configuration for a specific OON policy by ID. "
    "Returns the full policy object including secure, qos, route sections and targets.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_oon_policy_details(
    policy_id: Annotated[str, Field(description="The unique identifier of the OON policy")],
) -> Dict[str, Any]:
    """
    Gets the detailed configuration of a specific OON policy.

    Args:
        policy_id (str): The unique identifier of the OON policy.

    Returns:
        A dictionary containing the full policy configuration.
    """
    if not policy_id:
        return {"success": False, "error": "policy_id is required"}
    try:
        policy = await oon_manager.get_oon_policy_by_id(policy_id)
        return {
            "success": True,
            "policy_id": policy_id,
            "details": json.loads(json.dumps(policy, default=str)),
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting OON policy %s: %s", policy_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get OON policy {policy_id}: {e}"}


@server.tool(
    name="unifi_create_oon_policy",
    description="Create a new OON (Object-Oriented Network) policy for internet access scheduling, "
    "app blocking, bandwidth limiting, or VPN routing. "
    "IMPORTANT: qos and route must be full nested dicts (not the flattened qos_enabled/route_enabled booleans from list output). "
    "Use unifi_get_oon_policy_details on an existing policy as a template for the nested structure. "
    "Requires confirmation.",
    permission_category="oon_policy",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_oon_policy(
    name: Annotated[str, Field(description="Policy name")],
    target_type: Annotated[
        str, Field(description="Target type: 'CLIENTS' (target by MAC) or 'GROUPS' (target by group ID)")
    ],
    targets: Annotated[list, Field(description="List of target MAC addresses (if CLIENTS) or group IDs (if GROUPS)")],
    enabled: Annotated[bool, Field(description="Whether the policy is active")] = True,
    secure: Annotated[
        Optional[dict],
        Field(
            description="Internet access and app blocking config. Keys: internet_access_enabled (bool), "
            "apps (list of blocked app objects), schedule (access schedule)"
        ),
    ] = None,
    qos: Annotated[
        Optional[dict],
        Field(
            description="Bandwidth limiting config. Must include mode ('OFF' or 'LIMIT') and related fields "
            "even if disabled"
        ),
    ] = None,
    route: Annotated[
        Optional[dict],
        Field(
            description="VPN routing config. Must include mode ('OFF' or a VPN interface) and related fields "
            "even if disabled"
        ),
    ] = None,
    confirm: Annotated[
        bool,
        Field(description="When true, creates the policy. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Creates a new OON policy with individual parameters."""
    # Validate target_type
    target_type_upper = target_type.upper()
    if target_type_upper not in ("CLIENTS", "GROUPS"):
        return {"success": False, "error": f"target_type must be 'CLIENTS' or 'GROUPS', got '{target_type}'"}
    if not targets:
        return {"success": False, "error": "targets must be a non-empty list"}
    if secure is None and qos is None and route is None:
        return {
            "success": False,
            "error": "At least one of secure, qos, or route must be provided",
        }

    policy_data = {
        "name": name,
        "enabled": enabled,
        "target_type": target_type_upper,
        "targets": targets,
    }
    if secure is not None:
        policy_data["secure"] = secure
    if qos is not None:
        policy_data["qos"] = qos
    if route is not None:
        policy_data["route"] = route

    if not confirm:
        return create_preview(
            resource_type="oon_policy",
            resource_data=policy_data,
            resource_name=name,
        )

    try:
        result = await oon_manager.create_oon_policy(policy_data)
        if result:
            return {
                "success": True,
                "message": f"OON policy '{name}' created successfully.",
                "policy": json.loads(json.dumps(result, default=str)),
            }
        return {"success": False, "error": f"Failed to create OON policy '{name}'."}
    except Exception as e:
        logger.error("Error creating OON policy: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to create OON policy: {e}"}


@server.tool(
    name="unifi_update_oon_policy",
    description="Update an existing OON policy. Pass only the fields you want to change — "
    "current values are automatically preserved. Requires confirmation.",
    permission_category="oon_policy",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_oon_policy(
    policy_id: Annotated[str, Field(description="The ID of the policy to update")],
    policy_data: Annotated[
        dict,
        Field(
            description="Dictionary of fields to update. Pass only the fields you want to change — "
            "current values are automatically preserved. "
            "Allowed keys: name (str), enabled (bool), target_type ('CLIENTS'/'GROUPS'), "
            "targets (list of MACs or group IDs), secure (dict), qos (dict), route (dict)"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, updates the policy. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Updates an existing OON policy with partial data."""
    if not policy_id:
        return {"success": False, "error": "policy_id is required"}
    if not policy_data:
        return {"success": False, "error": "policy_data cannot be empty"}

    validated_data = oon_to_update(policy_data)
    if not validated_data:
        return {"success": False, "error": "No valid mutable fields provided for update."}

    if not confirm:
        return update_preview(
            resource_type="oon_policy",
            resource_id=policy_id,
            resource_name=policy_id,
            current_state={},
            updates=validated_data,
        )

    try:
        merged = await oon_manager.update_oon_policy(policy_id, validated_data)
        return {
            "success": True,
            "message": f"OON policy '{merged.get('name', policy_id)}' updated successfully.",
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating OON policy %s: %s", policy_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update OON policy '{policy_id}': {e}"}


@server.tool(
    name="unifi_toggle_oon_policy",
    description="Toggle an OON policy on or off. Fetches the current state, "
    "flips the enabled flag, and sends the update. Requires confirmation.",
    permission_category="oon_policy",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def toggle_oon_policy(
    policy_id: Annotated[str, Field(description="The ID of the policy to toggle")],
    confirm: Annotated[
        bool,
        Field(description="When true, toggles the policy. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """
    Toggles an OON policy's enabled state.

    Args:
        policy_id (str): The ID of the policy to toggle.
        confirm (bool): Must be True to execute.

    Returns:
        Preview or the new enabled state.
    """
    if not confirm:
        # Fetch current state for preview
        try:
            policy = await oon_manager.get_oon_policy_by_id(policy_id)
            if policy:
                current = policy.get("enabled", False)
                return {
                    "success": True,
                    "requires_confirmation": True,
                    "action": "toggle",
                    "resource_type": "oon_policy",
                    "current_state": {"enabled": current},
                    "proposed_changes": {"enabled": not current},
                    "message": f"Will {'disable' if current else 'enable'} OON policy '{policy.get('name', policy_id)}'. Set confirm=true to execute.",
                }
        except Exception as e:
            logger.debug("Could not fetch policy %s for toggle preview: %s", policy_id, e)
        return create_preview(
            resource_type="oon_policy",
            resource_data={"policy_id": policy_id, "action": "toggle"},
            resource_name=policy_id,
        )

    try:
        # Fetch current state to determine new state
        policy = await oon_manager.get_oon_policy_by_id(policy_id)
        current = bool(policy.get("enabled", False)) if policy else False
        new_state = not current
        update_payload = oon_to_update({"enabled": new_state})
        merged = await oon_manager.update_oon_policy(policy_id, update_payload)
        if merged is not None:
            state_str = "enabled" if new_state else "disabled"
            return {
                "success": True,
                "message": f"OON policy '{policy_id}' is now {state_str}.",
                "enabled": new_state,
            }
        return {"success": False, "error": f"Failed to toggle OON policy '{policy_id}'."}
    except Exception as e:
        logger.error("Error toggling OON policy %s: %s", policy_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to toggle OON policy '{policy_id}': {e}"}


@server.tool(
    name="unifi_delete_oon_policy",
    description="Delete an OON policy. Requires confirmation. "
    "WARNING: This will remove the policy and all associated firewall rules "
    "that were auto-generated from it.",
    permission_category="oon_policy",
    permission_action="delete",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def delete_oon_policy(
    policy_id: Annotated[str, Field(description="The ID of the policy to delete")],
    confirm: Annotated[
        bool,
        Field(description="When true, deletes the policy. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """
    Deletes an OON policy.

    Args:
        policy_id (str): The ID of the policy to delete.
        confirm (bool): Must be True to execute.

    Returns:
        Preview or success/failure status.
    """
    if not confirm:
        return create_preview(
            resource_type="oon_policy",
            resource_data={"policy_id": policy_id},
            resource_name=policy_id,
            warnings=["Deleting an OON policy removes all auto-generated firewall rules associated with it."],
        )

    try:
        success = await oon_manager.delete_oon_policy(policy_id)
        if success:
            return {"success": True, "message": f"OON policy '{policy_id}' deleted successfully."}
        return {"success": False, "error": f"Failed to delete OON policy '{policy_id}'."}
    except Exception as e:
        logger.error("Error deleting OON policy %s: %s", policy_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to delete OON policy '{policy_id}': {e}"}
