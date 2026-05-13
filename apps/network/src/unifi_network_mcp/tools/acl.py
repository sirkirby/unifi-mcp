"""
MAC ACL rule tools for UniFi Network MCP server.

MAC ACL rules (Policy Engine) control Layer 2 access within a VLAN
by whitelisting specific MAC address pairs. Requires UniFi Network
Application with Policy Engine support.

Tool I/O is derived from the shared AclRule model in
unifi_core.network.models.acl. That model is the single source of
truth for field names, types, and read-only vs mutable metadata.
"""

import json
import logging
from typing import Annotated, Any, Dict, List, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.confirmation import create_preview, update_preview
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.models.acl import (
    MUTABLE_FIELDS,
    AclRule,
    from_controller,
    to_controller_create,
    to_controller_update,
    validate_update_fields,
)
from unifi_network_mcp.runtime import acl_manager, server

logger = logging.getLogger(__name__)


@server.tool(
    name="unifi_list_acl_rules",
    description="List MAC ACL rules (Policy Engine) for Layer 2 access control. "
    "These rules control which devices can communicate at Layer 2 within a VLAN.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_acl_rules(
    network_id: Annotated[
        Optional[str],
        Field(description="Filter rules by network/VLAN ID (from unifi_list_networks). Omit to list all ACL rules"),
    ] = None,
) -> Dict[str, Any]:
    """
    Lists MAC ACL rules configured in the Policy Engine.

    Args:
        network_id (str, optional): Filter by network/VLAN ID.

    Returns:
        A dictionary containing:
        - success (bool): Indicates if the operation was successful.
        - count (int): Number of ACL rules found.
        - rules (List[Dict]): List of ACL rules with summary info.
    """
    try:
        rules = await acl_manager.get_acl_rules(network_id=network_id)
        formatted = [from_controller(r).model_dump() for r in rules]
        return {
            "success": True,
            "site": acl_manager._connection.site,
            "count": len(formatted),
            "rules": formatted,
        }
    except Exception as e:
        logger.error("Error listing ACL rules: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list ACL rules: {e}"}


@server.tool(
    name="unifi_get_acl_rule_details",
    description="Get detailed configuration for a specific MAC ACL rule by ID. "
    "Returns the same field names as unifi_list_acl_rules.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_acl_rule_details(
    rule_id: Annotated[str, Field(description="The id field from unifi_list_acl_rules output")],
) -> Dict[str, Any]:
    """
    Gets the detailed configuration of a specific MAC ACL rule.

    Args:
        rule_id (str): The unique identifier of the ACL rule.

    Returns:
        A dictionary containing the rule in the canonical AclRule shape.
    """
    if not rule_id:
        return {"success": False, "error": "rule_id is required"}
    try:
        rule = await acl_manager.get_acl_rule_by_id(rule_id)
        return {
            "success": True,
            "rule_id": rule_id,
            "details": from_controller(rule).model_dump(),
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting ACL rule %s: %s", rule_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get ACL rule {rule_id}: {e}"}


@server.tool(
    name="unifi_create_acl_rule",
    description="Create a new MAC ACL rule for Layer 2 access control within a VLAN. "
    "Uses the same field names as unifi_list_acl_rules output — source_macs, destination_macs, "
    "network_id, action, etc. Empty MAC list = match any device. Requires confirmation.",
    permission_category="acl_rules",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_acl_rule(
    name: Annotated[str, Field(description="Descriptive name for the ACL rule")],
    acl_index: Annotated[int, Field(description="Position in the rule chain (lower numbers are evaluated first)")],
    action: Annotated[str, Field(description="Rule action: 'ALLOW' or 'BLOCK'")],
    network_id: Annotated[
        str,
        Field(description="Network/VLAN ID this rule applies to (from unifi_list_networks)"),
    ],
    enabled: Annotated[
        bool,
        Field(description="Whether the rule is active (default: true)"),
    ] = True,
    source_macs: Annotated[
        Optional[List[str]],
        Field(description="List of source MAC addresses to match (empty list = any source)"),
    ] = None,
    destination_macs: Annotated[
        Optional[List[str]],
        Field(description="List of destination MAC addresses to match (empty list = any destination)"),
    ] = None,
    confirm: Annotated[
        bool,
        Field(description="When true, creates the rule. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """
    Creates a new MAC ACL rule in the Policy Engine.

    Args:
        name (str): Name of the rule.
        acl_index (int): Position in the rule chain (lower = evaluated first).
        action (str): "ALLOW" or "BLOCK".
        network_id (str): Network/VLAN ID this rule applies to.
        enabled (bool): Whether the rule is active. Defaults to True.
        source_macs (list): List of source MAC addresses. Empty list or None = any.
        destination_macs (list): List of destination MAC addresses. Empty list or None = any.
        confirm (bool): Must be True to execute. False returns a preview.

    Returns:
        Preview of changes or the created rule.
    """
    logger.info("unifi_create_acl_rule called (name=%s, action=%s, confirm=%s)", name, action, confirm)

    rule = AclRule(
        name=name,
        acl_index=acl_index,
        action=action.upper(),
        enabled=enabled,
        network_id=network_id,
        source_macs=source_macs if source_macs is not None else [],
        destination_macs=destination_macs if destination_macs is not None else [],
    )
    controller_payload = to_controller_create(rule)

    if not confirm:
        return create_preview(
            resource_type="acl_rule",
            resource_data=controller_payload,
            resource_name=name,
        )

    try:
        result = await acl_manager.create_acl_rule(controller_payload)
        if result:
            return {
                "success": True,
                "message": f"ACL rule '{name}' created successfully.",
                "rule": from_controller(result).model_dump()
                if isinstance(result, dict) and "_id" in result
                else json.loads(json.dumps(result, default=str)),
            }
        return {"success": False, "error": "Failed to create ACL rule."}
    except Exception as e:
        logger.error("Error creating ACL rule: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to create ACL rule: {e}"}


@server.tool(
    name="unifi_update_acl_rule",
    description="Update an existing MAC ACL rule. Pass only the fields you want to change — "
    "current values are automatically preserved. "
    "Uses the same field names as unifi_list_acl_rules output: name, acl_index, action, enabled, "
    "network_id, source_macs, destination_macs. Requires confirmation.",
    permission_category="acl_rules",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_acl_rule(
    rule_id: Annotated[
        str, Field(description="Unique identifier (_id) of the ACL rule to update (from unifi_list_acl_rules)")
    ],
    rule_data: Annotated[
        dict,
        Field(
            description="Dictionary of fields to update. Pass only the fields you want to change — "
            "current values are automatically preserved. "
            "Allowed keys: name, acl_index, action ('ALLOW'/'BLOCK'), enabled (bool), "
            "network_id, source_macs (list of MACs), destination_macs (list of MACs)"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the update. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Updates an existing MAC ACL rule with partial data."""
    logger.info("unifi_update_acl_rule called (rule_id=%s, confirm=%s)", rule_id, confirm)
    if not rule_id:
        return {"success": False, "error": "rule_id is required"}
    if not rule_data:
        return {"success": False, "error": "rule_data cannot be empty"}

    # Validate field names against the model's mutable fields
    unknown_fields = set(rule_data.keys()) - MUTABLE_FIELDS
    if unknown_fields:
        return {
            "success": False,
            "error": f"Unknown or read-only fields: {sorted(unknown_fields)}. Allowed fields: {sorted(MUTABLE_FIELDS)}",
        }

    # Type-check field values against the model's annotations
    is_valid, type_error = validate_update_fields(rule_data)
    if not is_valid:
        return {"success": False, "error": type_error}

    # Translate model field names to controller API shape
    controller_update = to_controller_update(rule_data)

    if not confirm:
        return update_preview(
            resource_type="acl_rule",
            resource_id=rule_id,
            resource_name=rule_id,
            current_state={},
            updates=rule_data,
        )

    try:
        merged = await acl_manager.update_acl_rule(rule_id, controller_update)
        return {
            "success": True,
            "message": f"ACL rule '{merged.get('name', rule_id)}' updated successfully.",
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating ACL rule %s: %s", rule_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update ACL rule {rule_id}: {e}"}


@server.tool(
    name="unifi_delete_acl_rule",
    description="Delete a MAC ACL rule. Requires confirmation. WARNING: Removing an ALLOW rule "
    "may block device communication. Removing a BLOCK rule may open access.",
    permission_category="acl_rules",
    permission_action="delete",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def delete_acl_rule(
    rule_id: Annotated[
        str, Field(description="Unique identifier (_id) of the ACL rule to delete (from unifi_list_acl_rules)")
    ],
    confirm: Annotated[
        bool,
        Field(
            description="When true, deletes the rule. When false (default), returns a preview. WARNING: Removing an ALLOW rule may block device communication"
        ),
    ] = False,
) -> Dict[str, Any]:
    """
    Deletes a MAC ACL rule.

    Args:
        rule_id (str): The ID of the rule to delete.
        confirm (bool): Must be True to execute. False returns a preview.

    Returns:
        Success/error message.
    """
    logger.info("unifi_delete_acl_rule called (rule_id=%s, confirm=%s)", rule_id, confirm)
    if not rule_id:
        return {"success": False, "error": "rule_id is required"}

    if not confirm:
        return {
            "success": True,
            "requires_confirmation": True,
            "action": "delete",
            "resource_type": "acl_rule",
            "rule_id": rule_id,
            "message": f"Will delete ACL rule '{rule_id}'. Set confirm=true to execute. "
            "WARNING: Removing an ALLOW rule may block device communication.",
        }

    try:
        success = await acl_manager.delete_acl_rule(rule_id)
        if success:
            return {
                "success": True,
                "message": f"ACL rule '{rule_id}' deleted successfully.",
            }
        return {"success": False, "error": f"Failed to delete ACL rule '{rule_id}'."}
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error deleting ACL rule %s: %s", rule_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to delete ACL rule {rule_id}: {e}"}
