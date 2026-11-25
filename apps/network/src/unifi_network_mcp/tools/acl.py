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
from collections import Counter
from typing import Annotated, Any, Dict, List, Optional

from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from unifi_core.confirmation import create_preview, delete_preview, update_preview
from unifi_core.exceptions import (
    UniFiAuthError,
    UniFiMalformedResponseError,
    UniFiNotFoundError,
    UniFiOperationError,
    UniFiPermissionError,
)
from unifi_core.network.models.acl import (
    MUTABLE_FIELDS,
    build_acl_rule,
    from_controller,
    to_controller_create,
    to_controller_update,
    validate_update_fields,
)
from unifi_core.network.models.acl_ordering import integration_acl_rule_from_controller
from unifi_core.redaction import redact_sensitive_fields
from unifi_network_mcp.runtime import acl_manager, server, should_redact_sensitive_fields

logger = logging.getLogger(__name__)


@server.tool(
    name="unifi_list_acl_rules",
    auth="either",
    description="List MAC ACL rules (Policy Engine) for Layer 2 access control. "
    "These rules control which devices can communicate at Layer 2 within a VLAN.",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
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
    auth="either",
    description="Get detailed configuration for a specific MAC ACL rule by ID. "
    "Returns the same field names as unifi_list_acl_rules.",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
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
    "network_id, action, etc. Empty MAC list = match any device. Optionally apply a netmask "
    "(source_netmask/destination_netmask) to match a leading-bit prefix instead of exact MACs. "
    "Requires confirmation.",
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
    source_netmask: Annotated[
        Optional[int],
        Field(
            description="Optional netmask for source_macs — number of leading bits that must match "
            "(e.g. 24 matches the vendor OUI, 48 matches the complete MAC). Omit for an exact match; "
            "do NOT pass 0 to mean 'no mask' — 0 matches ANY MAC."
        ),
    ] = None,
    destination_netmask: Annotated[
        Optional[int],
        Field(
            description="Optional netmask for destination_macs — number of leading bits that must match "
            "(e.g. 24 matches the vendor OUI, 48 matches the complete MAC). Omit for an exact match; "
            "do NOT pass 0 to mean 'no mask' — 0 matches ANY MAC."
        ),
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
        source_netmask (int): Optional leading-bit match count for source_macs (e.g. 24=OUI, 48=full MAC). None = exact.
        destination_netmask (int): Optional leading-bit match count for destination_macs. None = exact.
        confirm (bool): Must be True to execute. False returns a preview.

    Returns:
        Preview of changes or the created rule.
    """
    logger.info("unifi_create_acl_rule called (name=%s, action=%s, confirm=%s)", name, action, confirm)

    try:
        rule = build_acl_rule(
            {
                "name": name,
                "acl_index": acl_index,
                "action": action,
                "enabled": enabled,
                "network_id": network_id,
                "source_macs": source_macs,
                "destination_macs": destination_macs,
                "source_netmask": source_netmask,
                "destination_netmask": destination_netmask,
            }
        )
    except ValidationError as e:
        msg = e.errors()[0].get("msg", str(e)) if e.errors() else str(e)
        return {"success": False, "error": f"Invalid ACL rule: {msg}"}
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
    "network_id, source_macs, destination_macs, source_netmask, destination_netmask. "
    "To remove a netmask (widen a prefix rule back to an exact match), set clear_source_netmask / "
    "clear_destination_netmask = true (passing source_netmask=null is a no-op, not a clear). "
    "Requires confirmation.",
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
            "network_id, source_macs (list of MACs), destination_macs (list of MACs), "
            "source_netmask (int, e.g. 24=OUI/48=full MAC), destination_netmask (int)"
        ),
    ],
    clear_source_netmask: Annotated[
        bool,
        Field(
            description="When true, removes the source netmask (revert to exact-MAC match). Overrides source_netmask."
        ),
    ] = False,
    clear_destination_netmask: Annotated[
        bool,
        Field(description="When true, removes the destination netmask (revert to exact-MAC match)."),
    ] = False,
    confirm: Annotated[
        bool,
        Field(description="When true, applies the update. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Updates an existing MAC ACL rule with partial data."""
    logger.info("unifi_update_acl_rule called (rule_id=%s, confirm=%s)", rule_id, confirm)
    if not rule_id:
        return {"success": False, "error": "rule_id is required"}
    if not rule_data and not (clear_source_netmask or clear_destination_netmask):
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

    # Add the clear-netmask sentinels (handled by to_controller_update / the manager),
    # separate from rule_data so they bypass the MUTABLE_FIELDS check above.
    update_fields = dict(rule_data)
    if clear_source_netmask:
        update_fields["clear_source_netmask"] = True
    if clear_destination_netmask:
        update_fields["clear_destination_netmask"] = True

    # Translate model field names to controller API shape
    controller_update = to_controller_update(update_fields)

    if not confirm:
        return update_preview(
            resource_type="acl_rule",
            resource_id=rule_id,
            resource_name=rule_id,
            current_state={},
            updates=update_fields,
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
        return delete_preview(
            resource_type="acl_rule",
            resource_id=rule_id,
            resource_data={"rule_id": rule_id},
            resource_name=rule_id,
            warnings=["Removing an ALLOW rule may block device communication."],
        )

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


@server.tool(
    name="unifi_list_integration_acl_rules",
    auth="api_key_only",
    description=(
        "List the site's MAC ACL rules as the UniFi public Integration API sees them. This is the "
        "ID source for the ordering endpoints: the returned id values are Integration API UUIDs — "
        "the same family unifi_get_acl_rule_ordering returns and unifi_reorder_acl_rules accepts. "
        "They do NOT correspond to the IDs returned by unifi_list_acl_rules, which lists the "
        "private V2 MAC ACL rules (Mongo IDs). Requires UNIFI_NETWORK_API_KEY (or UNIFI_API_KEY on "
        "the UNIFI_HOST console). These IDs are scoped to the ACL-ordering tool family."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
)
async def list_integration_acl_rules(
    site_id: Annotated[
        Optional[str],
        Field(
            description=(
                "Optional Integration API site UUID; when omitted, the configured site is resolved automatically"
            )
        ),
    ] = None,
) -> Dict[str, Any]:
    """List the site's MAC ACL rules in Integration API ID space."""
    try:
        rules = await acl_manager.list_integration_acl_rules(site_id=site_id)
        return {
            "success": True,
            "site": acl_manager._connection.site,
            "count": len(rules),
            "rules": [
                redact_sensitive_fields(
                    integration_acl_rule_from_controller(rule).model_dump(),
                    redact_sensitive=should_redact_sensitive_fields(),
                )
                for rule in rules
            ],
        }
    except (UniFiAuthError, UniFiPermissionError, UniFiOperationError, UniFiMalformedResponseError) as e:
        # Fixed-text configuration/transport errors are safe to surface.
        logger.error("Error listing Integration ACL rules: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to list Integration ACL rules: {e}"}
    except Exception as e:
        logger.error("Error listing Integration ACL rules: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to list Integration ACL rules: {type(e).__name__}"}


@server.tool(
    name="unifi_get_acl_rule_ordering",
    auth="api_key_only",
    description=(
        "Read the ordering of user-defined ACL rules from the UniFi public Integration API. "
        "Returns Integration API ACL rule UUIDs; these IDs are scoped to the ACL-ordering tool "
        "family — pass them ONLY to unifi_reorder_acl_rules. Discover them with "
        "unifi_list_integration_acl_rules; they do NOT correspond to the IDs returned by "
        "unifi_list_acl_rules, which lists the private V2 MAC ACL rules (Mongo IDs). "
        "The controller does not document whether this list must be complete or whether "
        "controller-defined rules participate, so it is returned verbatim. "
        "Requires UNIFI_NETWORK_API_KEY (or UNIFI_API_KEY on the UNIFI_HOST console)."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
)
async def get_acl_rule_ordering(
    site_id: Annotated[
        Optional[str],
        Field(
            description=(
                "Optional Integration API site UUID; when omitted, the configured site is resolved automatically"
            )
        ),
    ] = None,
) -> Dict[str, Any]:
    """Read user-defined ACL rule ordering from the Integration API."""
    try:
        ordering = await acl_manager.get_acl_rule_ordering(site_id=site_id)
        return {"success": True, "ordered_acl_rule_ids": ordering}
    except (UniFiAuthError, UniFiPermissionError, UniFiOperationError, UniFiMalformedResponseError) as e:
        # Fixed-text configuration/transport errors are safe to surface.
        logger.error("Error getting ACL rule ordering: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to get ACL rule ordering: {e}"}
    except Exception as e:
        logger.error("Error getting ACL rule ordering: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to get ACL rule ordering: {type(e).__name__}"}


@server.tool(
    name="unifi_reorder_acl_rules",
    auth="api_key_only",
    description=(
        "Reorder user-defined ACL rules for the Integration API ACL rule family. Pass the complete "
        "ordered_acl_rule_ids list obtained from unifi_get_acl_rule_ordering, preserving every "
        "current ID. These Integration API UUIDs are scoped to the ACL-ordering tool family — do "
        "NOT pass IDs from unifi_list_acl_rules (V2 Mongo IDs). The manager re-reads the current "
        "ordering from the controller immediately before applying and refuses a payload that does "
        "not preserve the exact current ID set, so a stale preview or partial list cannot drop "
        "rules. Requires confirmation, UNIFI_NETWORK_API_KEY (or UNIFI_API_KEY on the UNIFI_HOST "
        "console)."
    ),
    permission_category="acl_rules",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def reorder_acl_rules(
    ordered_acl_rule_ids: Annotated[
        List[str],
        Field(
            description=(
                "Complete ordered list of Integration API ACL rule UUIDs from "
                "unifi_get_acl_rule_ordering, in the desired order"
            )
        ),
    ],
    site_id: Annotated[
        Optional[str],
        Field(
            description=(
                "Optional Integration API site UUID; when omitted, the configured site is resolved "
                "automatically — the same site unifi_get_acl_rule_ordering read unless told otherwise"
            )
        ),
    ] = None,
    confirm: Annotated[
        bool,
        Field(description="When true, applies the reorder. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Reorder user-defined ACL rules for a site through the Integration API."""
    try:
        if not isinstance(ordered_acl_rule_ids, list) or not ordered_acl_rule_ids:
            return {"success": False, "error": "ordered_acl_rule_ids must be a non-empty list"}
        if not all(isinstance(rule_id, str) and rule_id for rule_id in ordered_acl_rule_ids):
            return {
                "success": False,
                "error": "ordered_acl_rule_ids must contain only non-empty ACL rule ID strings",
            }
        duplicate_ids = sorted(rule_id for rule_id, count in Counter(ordered_acl_rule_ids).items() if count > 1)
        if duplicate_ids:
            return {
                "success": False,
                "error": "Reorder payload contains duplicate ACL rule IDs: %s" % ", ".join(duplicate_ids),
            }

        if not confirm:
            current_ordering = await acl_manager.get_acl_rule_ordering(site_id=site_id)
            return update_preview(
                resource_type="acl_rule_ordering",
                resource_id=acl_manager._connection.site,
                resource_name="ACL rule ordering",
                current_state={"orderedAclRuleIds": current_ordering},
                updates={"orderedAclRuleIds": ordered_acl_rule_ids},
            )

        ordering = await acl_manager.reorder_acl_rules(ordered_acl_rule_ids, site_id=site_id)
        return {"success": True, "ordered_acl_rule_ids": ordering}
    except (UniFiAuthError, UniFiPermissionError, UniFiOperationError, UniFiMalformedResponseError) as e:
        # Fixed-text configuration/transport errors are safe to surface.
        logger.error("Error reordering ACL rules: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to reorder ACL rules: {e}"}
    except ValueError as e:
        # The manager's stale-set and duplicate-payload refusals are caller-input errors.
        return {"success": False, "error": f"Failed to reorder ACL rules: {e}"}
    except Exception as e:
        logger.error("Error reordering ACL rules: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to reorder ACL rules: {type(e).__name__}"}
