"""
Firewall policy tools for Unifi Network MCP server.
"""

import json
import logging
from collections import Counter
from typing import Annotated, Any, Dict, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.confirmation import create_preview, delete_preview, toggle_preview, update_preview
from unifi_core.network.models.firewall import (
    firewall_group_from_controller,
    firewall_zone_from_controller,
    legacy_firewall_rule_from_controller,
    legacy_policy_error,
    normalize_policy_enums,
    normalize_policy_update,
)
from unifi_core.network.read_views import LEGACY_ENGINE_HINT, shape_firewall_policy_list
from unifi_core.redaction import redact_sensitive_fields
from unifi_network_mcp.runtime import firewall_manager, server, should_redact_sensitive_fields

logger = logging.getLogger(__name__)


@server.tool(
    name="unifi_list_firewall_policies",
    description=(
        "List firewall policies configured on the Unifi Network controller. "
        "Returns V2 zone-based targeting (zone_id, matching_target, matching_target_type, "
        "IPs, network IDs).\n\n"
        "Filters: search (name substring), action (ALLOW/BLOCK/REJECT), enabled_only, "
        "limit (default 50), include_predefined. By default (summary=true) returns a curated "
        "entry per policy (id, name, enabled, action, rule_index, description + source/destination "
        "targeting). Set summary=false for the full fw_from_controller().model_dump() shape "
        "including protocol, schedule, logging, ip_version, index, etc."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_firewall_policies(
    search: Annotated[
        Optional[str],
        Field(description="Filter by policy name (case-insensitive substring match)"),
    ] = None,
    action: Annotated[
        Optional[str],
        Field(description="Filter by action: ALLOW, BLOCK, or REJECT (V2 firmware). Case-insensitive."),
    ] = None,
    enabled_only: Annotated[
        bool,
        Field(description="If true, only return enabled policies. Default false."),
    ] = False,
    limit: Annotated[int, Field(description="Maximum number of policies to return (default 50)")] = 50,
    summary: Annotated[
        bool,
        Field(
            description=(
                "Controls per-policy shape. When true (default), returns a curated 6-key entry "
                "plus narrowed source/destination targeting. When false, returns the full "
                "fw_from_controller().model_dump() shape (protocol, schedule, logging, ip_version, "
                "index, full source/destination dicts)."
            )
        ),
    ] = True,
    include_predefined: Annotated[
        bool,
        Field(
            description="When true, includes predefined system policies in results. Default false (user-defined only)"
        ),
    ] = False,
) -> Dict[str, Any]:
    """Lists firewall policies for the current UniFi site.

    Returns V2 zone-based policy fields (zone_id, matching_target, matching_target_type)
    in source/destination. Legacy V1 ruleset support was removed in #210.
    """
    try:
        policies = await firewall_manager.get_firewall_policies(include_predefined=include_predefined)
        return shape_firewall_policy_list(
            policies,
            site=firewall_manager._connection.site,
            search=search,
            action=action,
            enabled_only=enabled_only,
            limit=limit,
            summary=summary,
        )
    except Exception as e:
        logger.error("Error listing firewall policies: %s", e, exc_info=True)
        return {"success": False, "error": "Failed to list firewall policies: %s" % e}


@server.tool(
    name="unifi_get_firewall_policy_details",
    description="Get detailed configuration for a specific firewall policy by ID.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_firewall_policy_details(
    policy_id: Annotated[
        str,
        Field(description="Unique identifier (_id) of the firewall policy (from unifi_list_firewall_policies)"),
    ],
) -> Dict[str, Any]:
    """
    Gets the detailed configuration of a specific firewall policy by its ID.

    Args:
        policy_id (str): The unique identifier (_id) of the firewall policy.

    Returns:
        A dictionary containing:
        - success (bool): Indicates if the operation was successful.
        - policy_id (str): The ID of the policy requested.
        - details (Dict[str, Any]): A dictionary containing the raw configuration details
          of the firewall policy as returned by the UniFi controller.
        - error (str, optional): An error message if the operation failed (e.g., policy not found).

    Example response (success):
    {
        "success": True,
        "policy_id": "60b8a7f1e4b0f4a7f7d6e8c0",
        "details": {
            "_id": "60b8a7f1e4b0f4a7f7d6e8c0",
            "name": "Allow Established/Related",
            "enabled": True,
            "action": "accept",
            "rule_index": 2000,
            "ruleset": "WAN_IN",
            "description": "Allow established and related sessions",
            "protocol_match_excepted": False,
            "logging": False,
            "state_established": True,
            "state_invalid": False,
            "state_new": False,
            "state_related": True,
            "site_id": "...",
            # ... other fields
        }
    }
    """
    redact_sensitive = should_redact_sensitive_fields()
    try:
        if not policy_id:
            return {"success": False, "error": "policy_id is required"}
        policies = await firewall_manager.get_firewall_policies(include_predefined=True)
        policies_raw = [p.raw if hasattr(p, "raw") else p for p in policies]
        policy = next((p for p in policies_raw if p.get("_id") == policy_id), None)
        if not policy:
            return {
                "success": False,
                "error": f"Firewall policy with ID '{policy_id}' not found.",
            }
        return redact_sensitive_fields(
            {
                "success": True,
                "policy_id": policy_id,
                "details": json.loads(json.dumps(policy, default=str)),
            },
            redact_sensitive=redact_sensitive,
        )
    except Exception as e:
        logger.error("Error getting firewall policy details for %s: %s", policy_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get firewall policy details for {policy_id}: {e}"}


@server.tool(
    name="unifi_toggle_firewall_policy",
    description="Enable or disable a specific firewall policy by ID.",
    permission_category="firewall_policies",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def toggle_firewall_policy(
    policy_id: Annotated[
        str,
        Field(
            description="Unique identifier (_id) of the firewall policy to toggle (from unifi_list_firewall_policies)"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, executes the toggle. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """
    Enables or disables a specific firewall policy. Requires confirmation.

    Args:
        policy_id (str): The unique identifier (_id) of the firewall policy to toggle.
        confirm (bool): Must be explicitly set to `True` to execute the toggle operation. Defaults to `False`.

    Returns:
        A dictionary containing:
        - success (bool): Indicates if the operation was successful.
        - policy_id (str): The ID of the policy toggled.
        - enabled (bool): The new state of the policy (True if enabled, False if disabled).
        - message (str): A confirmation message indicating the action taken.
        - error (str, optional): An error message if the operation failed.

    Example response (success):
    {
        "success": True,
        "policy_id": "60b8a7f1e4b0f4a7f7d6e8c0",
        "enabled": false,
        "message": "Firewall policy 'Allow Established/Related' (60b8a7f1e4b0f4a7f7d6e8c0) toggled to disabled."
    }
    """
    try:
        policies = await firewall_manager.get_firewall_policies(include_predefined=True)
        policy_obj = next((p for p in policies if p.id == policy_id), None)
        if not policy_obj or not policy_obj.raw:
            return {
                "success": False,
                "error": f"Firewall policy with ID '{policy_id}' not found.",
            }
        policy = policy_obj.raw

        current_state = policy.get("enabled", False)
        policy_name = policy.get("name", policy_id)
        new_state = not current_state

        if not confirm:
            return toggle_preview(
                resource_type="firewall_policy",
                resource_id=policy_id,
                resource_name=policy_name,
                current_enabled=current_state,
                additional_info={
                    "action": policy.get("action"),
                    "index": policy.get("index"),
                },
            )

        logger.info("Attempting to toggle firewall policy '%s' (%s) to %s", policy_name, policy_id, new_state)

        success = await firewall_manager.toggle_firewall_policy(policy_id)

        if success:
            toggled_policy_obj = next(
                (p for p in await firewall_manager.get_firewall_policies(include_predefined=True) if p.id == policy_id),
                None,
            )
            final_state = toggled_policy_obj.enabled if toggled_policy_obj else new_state

            logger.info("Successfully toggled firewall policy '%s' (%s) to %s", policy_name, policy_id, final_state)
            return {
                "success": True,
                "policy_id": policy_id,
                "enabled": final_state,
                "message": f"Firewall policy '{policy_name}' ({policy_id}) toggled successfully to {'enabled' if final_state else 'disabled'}.",
            }
        else:
            logger.error("Failed to toggle firewall policy '%s' (%s). Manager returned false.", policy_name, policy_id)
            policy_after_toggle_obj = next(
                (p for p in await firewall_manager.get_firewall_policies(include_predefined=True) if p.id == policy_id),
                None,
            )
            state_after = policy_after_toggle_obj.enabled if policy_after_toggle_obj else "unknown"
            return {
                "success": False,
                "policy_id": policy_id,
                "state_after_attempt": state_after,
                "error": f"Failed to toggle firewall policy '{policy_name}' ({policy_id}). Check server logs.",
            }
    except Exception as e:
        logger.error("Error toggling firewall policy %s: %s", policy_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to toggle firewall policy {policy_id}: {e}"}


def _validate_zone_targeting(validated_data: Dict[str, Any]) -> str | None:
    """Validate matching_target_type requirements for zone-based policies.

    Returns an error message string if validation fails, or None if valid.
    """
    for direction in ("source", "destination"):
        ep = validated_data.get(direction, {})
        if not isinstance(ep, dict):
            continue
        target = ep.get("matching_target")
        if target in ("IP", "NETWORK") and not ep.get("matching_target_type"):
            expected = "'SPECIFIC' or 'OBJECT'" if target == "IP" else "'OBJECT'"
            return "%s.matching_target_type is required when matching_target is '%s'. Use %s." % (
                direction,
                target,
                expected,
            )
        if target == "IP":
            target_type = ep.get("matching_target_type")
            if target_type == "OBJECT" and not ep.get("ip_group_id"):
                return (
                    "%s.ip_group_id is required when matching_target is 'IP' with matching_target_type 'OBJECT'."
                    % direction
                )
            if target_type != "OBJECT" and not ep.get("ips"):
                return "%s.ips array is required when matching_target is 'IP'." % direction
        if target == "NETWORK" and not ep.get("network_ids"):
            return "%s.network_ids array is required when matching_target is 'NETWORK'." % direction
    return None


@server.tool(
    name="unifi_create_firewall_policy",
    description=(
        "Create a V2 zone-based firewall policy with schema validation. "
        "Required: name, action (ALLOW/BLOCK/REJECT), source (zone_id + "
        "matching_target), destination (same structure). For specific IP "
        "targeting: matching_target='IP', matching_target_type='SPECIFIC', "
        "ips=[...]. For network targeting: matching_target='NETWORK', "
        "matching_target_type='OBJECT', network_ids=[...]. For any in zone: "
        "matching_target='ANY'. Use unifi_list_firewall_zones to discover "
        "zone_ids; unifi_list_networks for network_ids."
    ),
    permission_category="firewall_policies",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_firewall_policy(
    policy_data: Annotated[
        Dict[str, Any],
        Field(
            description=(
                "V2 zone-based firewall policy dict. Required: name, action "
                "(ALLOW/BLOCK/REJECT), source (object with zone_id, matching_target), "
                "destination (same structure). For IP targeting: matching_target='IP', "
                "matching_target_type='SPECIFIC', ips=[...]. For network targeting: "
                "matching_target='NETWORK', matching_target_type='OBJECT', "
                "network_ids=[...]. For any in zone: matching_target='ANY'. Optional: "
                "enabled, description, protocol, connection_state_type, connection_states, "
                "ip_version, schedule, logging."
            )
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, creates the policy. When false (default), validates and returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Create a V2 zone-based firewall policy."""
    redact_sensitive = should_redact_sensitive_fields()
    if not isinstance(policy_data, dict) or not policy_data:
        return {
            "success": False,
            "error": "policy_data must be a non-empty dictionary.",
        }

    # Reject legacy V1 fields up front with an actionable migration error (#210).
    legacy_error = legacy_policy_error(policy_data)
    if legacy_error:
        return {"success": False, "error": legacy_error}

    # Controller's V2 enums are strictly upper-case. Normalize common
    # mixed-case input before validation so users can pass natural forms
    # like "IPv4" or lowercase state names.
    try:
        policy_data = normalize_policy_enums(policy_data)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    # Validate required fields and apply schema defaults directly.
    _required = ("name", "action", "source", "destination")
    _missing = [f for f in _required if f not in policy_data]
    if _missing:
        err = "Missing required fields: %s" % ", ".join(_missing)
        logger.warning("Invalid firewall policy data: %s", err)
        return {"success": False, "error": "Validation Error: %s" % err}

    # Reject unknown top-level keys (mirrors additionalProperties: False in the schema).
    _allowed_keys = frozenset(
        {
            "name",
            "action",
            "enabled",
            "index",
            "protocol",
            "ip_version",
            "logging",
            "connection_state_type",
            "connection_states",
            "create_allow_respond",
            "match_ip_sec",
            "match_opposite_protocol",
            "icmp_typename",
            "icmp_v6_typename",
            "schedule",
            "source",
            "destination",
            "description",
        }
    )
    _unknown = sorted(set(policy_data.keys()) - _allowed_keys)
    if _unknown:
        err = "Additional properties not allowed: %s" % ", ".join(_unknown)
        logger.warning("Invalid firewall policy data: %s", err)
        return {"success": False, "error": "Validation Error: %s" % err}

    # Apply controller-required V2 defaults for create only. Do not move these
    # into shared update validation; omitted update fields must remain untouched.
    validated_data: Dict[str, Any] = {
        "enabled": True,
        "protocol": "all",
        "ip_version": "BOTH",
        "logging": False,
        "connection_state_type": "ALL",
        "schedule": {"mode": "ALWAYS"},
        **policy_data,
    }
    if validated_data.get("schedule") is None:
        validated_data["schedule"] = {"mode": "ALWAYS"}

    # Validate zone targeting requirements (matching_target_type, ips, network_ids)
    targeting_error = _validate_zone_targeting(validated_data)
    if targeting_error:
        return {"success": False, "error": targeting_error}
    # Normalize action to uppercase and require V2 enum
    action = validated_data.get("action", "")
    if not isinstance(action, str) or action.upper() not in ("ALLOW", "BLOCK", "REJECT"):
        return {"success": False, "error": "Invalid action '%s'. Must be ALLOW, BLOCK, or REJECT." % action}
    validated_data["action"] = action.upper()
    if validated_data["action"] in ("BLOCK", "REJECT"):
        if validated_data.get("create_allow_respond") is True:
            return {
                "success": False,
                "error": "create_allow_respond must be false for BLOCK/REJECT firewall policies.",
            }
        validated_data.setdefault("create_allow_respond", False)

    policy_name = validated_data.get("name", "Unnamed Policy")

    if not confirm:
        return redact_sensitive_fields(
            create_preview(
                resource_type="firewall_policy",
                resource_data=validated_data,
                resource_name=policy_name,
            ),
            redact_sensitive=redact_sensitive,
        )

    logger.info("Creating firewall policy '%s'", policy_name)

    try:
        created_policy_obj = await firewall_manager.create_firewall_policy(validated_data)

        if created_policy_obj and hasattr(created_policy_obj, "raw"):
            created_policy_details = created_policy_obj.raw
            new_policy_id = created_policy_details.get("_id", "unknown")
            logger.info("Created firewall policy '%s' with ID %s", policy_name, new_policy_id)
            return redact_sensitive_fields(
                {
                    "success": True,
                    "message": "Firewall policy '%s' created successfully." % policy_name,
                    "policy_id": new_policy_id,
                    "details": json.loads(json.dumps(created_policy_details, default=str)),
                },
                redact_sensitive=redact_sensitive,
            )
        else:
            logger.error("Failed to create firewall policy '%s'. Manager returned None.", policy_name)
            return {
                "success": False,
                "error": "Failed to create firewall policy '%s'. Check server logs." % policy_name,
            }

    except Exception as e:
        logger.error("Error creating firewall policy '%s': %s", policy_name, e, exc_info=True)
        return {"success": False, "error": "Failed to create firewall policy '%s': %s" % (policy_name, e)}


@server.tool(
    name="unifi_update_firewall_policy",
    description=(
        "Update specific fields of an existing V2 zone-based firewall policy by ID. "
        "Accepts: name, action (ALLOW/BLOCK/REJECT), enabled, source, destination, "
        "protocol, ip_version, index, logging, connection_state_type, connection_states, "
        "schedule."
    ),
    permission_category="firewall_policies",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_firewall_policy(
    policy_id: Annotated[
        str,
        Field(
            description="Unique identifier (_id) of the firewall policy to update (from unifi_list_firewall_policies)"
        ),
    ],
    update_data: Annotated[
        Dict[str, Any],
        Field(
            description=(
                "Dictionary of V2 zone-based fields to update: name, action "
                "(ALLOW/BLOCK/REJECT), enabled, source, destination, protocol, ip_version, "
                "index, logging, connection_state_type, connection_states, schedule."
            )
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the update. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Update specific fields of an existing V2 zone-based firewall policy. Requires confirmation."""
    redact_sensitive = should_redact_sensitive_fields()
    if not policy_id:
        return {"success": False, "error": "policy_id is required"}
    if not update_data:
        return {"success": False, "error": "update_data cannot be empty"}

    try:
        validated_data = normalize_policy_update(update_data)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    updated_fields_list = list(validated_data.keys())

    try:
        policies = await firewall_manager.get_firewall_policies(include_predefined=True)
        current_policy_obj = next((p for p in policies if p.id == policy_id), None)
        if not current_policy_obj or not current_policy_obj.raw:
            return {
                "success": False,
                "error": "Firewall policy with ID '%s' not found." % policy_id,
            }
        current = current_policy_obj.raw

        if not confirm:
            return redact_sensitive_fields(
                update_preview(
                    resource_type="firewall_policy",
                    resource_id=policy_id,
                    resource_name=current.get("name"),
                    current_state=current,
                    updates=validated_data,
                ),
                redact_sensitive=redact_sensitive,
            )

        logger.info("Updating firewall policy '%s' fields: %s", policy_id, ", ".join(updated_fields_list))

        success = await firewall_manager.update_firewall_policy(policy_id, validated_data)

        if success:
            updated_policy_obj = next(
                (p for p in await firewall_manager.get_firewall_policies(include_predefined=True) if p.id == policy_id),
                None,
            )
            updated_details = updated_policy_obj.raw if updated_policy_obj else {}

            # Verify the controller actually applied the requested changes.
            # For nested dicts (source, destination, schedule), check that each
            # requested key-value is present in the response (subset check),
            # since deep_merge preserves unmentioned sibling keys.
            mismatched = []
            for field, expected in validated_data.items():
                actual = updated_details.get(field)
                if isinstance(expected, dict) and isinstance(actual, dict):
                    for k, v in expected.items():
                        if actual.get(k) != v:
                            mismatched.append(field)
                            logger.warning(
                                "Firewall policy %s field '%s.%s' not applied: expected %s, got %s",
                                policy_id,
                                field,
                                k,
                                v,
                                actual.get(k),
                            )
                            break
                elif actual != expected:
                    mismatched.append(field)
                    logger.warning(
                        "Firewall policy %s field '%s' not applied: expected %s, got %s",
                        policy_id,
                        field,
                        expected,
                        actual,
                    )
            if mismatched:
                return redact_sensitive_fields(
                    {
                        "success": False,
                        "policy_id": policy_id,
                        "error": "Controller accepted the request but did not apply changes to: %s"
                        % ", ".join(mismatched),
                        "details": json.loads(json.dumps(updated_details, default=str)),
                    },
                    redact_sensitive=redact_sensitive,
                )

            logger.info("Updated firewall policy (%s)", policy_id)
            return redact_sensitive_fields(
                {
                    "success": True,
                    "policy_id": policy_id,
                    "updated_fields": updated_fields_list,
                    "details": json.loads(json.dumps(updated_details, default=str)),
                },
                redact_sensitive=redact_sensitive,
            )
        else:
            logger.error("Failed to update firewall policy (%s). Manager returned false.", policy_id)
            return {
                "success": False,
                "policy_id": policy_id,
                "error": "Failed to update firewall policy (%s). Check server logs." % policy_id,
            }

    except Exception as e:
        logger.error("Error updating firewall policy %s: %s", policy_id, e, exc_info=True)
        return {"success": False, "error": "Failed to update firewall policy %s: %s" % (policy_id, e)}


@server.tool(
    name="unifi_get_firewall_policy_ordering",
    description=(
        "Get user-defined firewall policy ordering for a source/destination firewall zone pair. "
        "Returns policy IDs from the UniFi public integration API (UUIDs); these IDs are scoped "
        "to the ordering tool family — pass them ONLY to unifi_reorder_firewall_policies. They "
        "do NOT correspond to the policy IDs returned by unifi_list_firewall_policies or any "
        "other controller-API firewall tool. Requires a UniFi API key (UNIFI_API_KEY)."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_firewall_policy_ordering(
    source_firewall_zone_id: Annotated[
        str,
        Field(description="Source firewall zone ID from unifi_list_firewall_zones"),
    ],
    destination_firewall_zone_id: Annotated[
        str,
        Field(description="Destination firewall zone ID from unifi_list_firewall_zones"),
    ],
) -> Dict[str, Any]:
    """Get user-defined firewall policy ordering for a zone pair."""
    try:
        if not source_firewall_zone_id or not destination_firewall_zone_id:
            return {"success": False, "error": "source_firewall_zone_id and destination_firewall_zone_id are required"}

        ordering = await firewall_manager.get_firewall_policy_ordering(
            source_firewall_zone_id,
            destination_firewall_zone_id,
        )
        return {
            "success": True,
            "source_firewall_zone_id": source_firewall_zone_id,
            "destination_firewall_zone_id": destination_firewall_zone_id,
            "ordering": ordering.get("orderedFirewallPolicyIds", ordering),
        }
    except Exception as e:
        logger.error("Error getting firewall policy ordering: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get firewall policy ordering: {e}"}


@server.tool(
    name="unifi_reorder_firewall_policies",
    description=(
        "Reorder user-defined firewall policies for a source/destination firewall zone pair. "
        "Pass the complete orderedFirewallPolicyIds object obtained from "
        "unifi_get_firewall_policy_ordering (beforeSystemDefined + afterSystemDefined arrays). "
        "These IDs are integration-API UUIDs scoped to the ordering tool family — they are NOT "
        "the policy IDs returned by unifi_list_firewall_policies. Requires confirmation and a "
        "UniFi API key (UNIFI_API_KEY)."
    ),
    permission_category="firewall_policies",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def reorder_firewall_policies(
    source_firewall_zone_id: Annotated[
        str,
        Field(description="Source firewall zone ID from unifi_list_firewall_zones"),
    ],
    destination_firewall_zone_id: Annotated[
        str,
        Field(description="Destination firewall zone ID from unifi_list_firewall_zones"),
    ],
    ordered_firewall_policy_ids: Annotated[
        Dict[str, list[str]],
        Field(
            description=(
                "Complete ordering object: {'beforeSystemDefined': [...], 'afterSystemDefined': [...]}. "
                "Preserve all existing policy IDs unless intentionally moving them."
            )
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the reorder. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Reorder user-defined firewall policies for a zone pair."""
    try:
        if not source_firewall_zone_id or not destination_firewall_zone_id:
            return {"success": False, "error": "source_firewall_zone_id and destination_firewall_zone_id are required"}

        if not isinstance(ordered_firewall_policy_ids, dict):
            return {"success": False, "error": "ordered_firewall_policy_ids must be an object"}

        before = ordered_firewall_policy_ids.get("beforeSystemDefined")
        after = ordered_firewall_policy_ids.get("afterSystemDefined")
        if not isinstance(before, list) or not isinstance(after, list):
            return {
                "success": False,
                "error": "ordered_firewall_policy_ids must include beforeSystemDefined and afterSystemDefined arrays",
            }
        requested_order = before + after
        if not all(isinstance(policy_id, str) and policy_id for policy_id in requested_order):
            return {
                "success": False,
                "error": "ordered_firewall_policy_ids arrays must contain only non-empty policy ID strings",
            }
        duplicate_ids = sorted(policy_id for policy_id, count in Counter(requested_order).items() if count > 1)
        if duplicate_ids:
            return {
                "success": False,
                "error": "Reorder payload contains duplicate policy IDs: %s" % ", ".join(duplicate_ids),
            }

        current = await firewall_manager.get_firewall_policy_ordering(
            source_firewall_zone_id,
            destination_firewall_zone_id,
        )
        current_ordering = current.get("orderedFirewallPolicyIds", current)
        if not isinstance(current_ordering, dict):
            return {
                "success": False,
                "error": "Current firewall policy ordering response did not include an ordering object",
            }
        current_order = current_ordering.get("beforeSystemDefined", []) + current_ordering.get("afterSystemDefined", [])
        requested_counts = Counter(requested_order)
        current_counts = Counter(current_order)
        if requested_counts != current_counts:
            missing_ids = sorted((current_counts - requested_counts).elements())
            unexpected_ids = sorted((requested_counts - current_counts).elements())
            return {
                "success": False,
                "error": (
                    "Reorder payload must preserve the exact current policy ID set. "
                    "Missing: %s; unexpected: %s"
                    % (
                        ", ".join(missing_ids) or "none",
                        ", ".join(unexpected_ids) or "none",
                    )
                ),
                "current_ordering": current_ordering,
            }

        if not confirm:
            return update_preview(
                resource_type="firewall_policy_ordering",
                resource_id=f"{source_firewall_zone_id}->{destination_firewall_zone_id}",
                resource_name="Firewall policy ordering",
                current_state={"orderedFirewallPolicyIds": current_ordering},
                updates={"orderedFirewallPolicyIds": ordered_firewall_policy_ids},
            )

        result = await firewall_manager.reorder_firewall_policies(
            source_firewall_zone_id,
            destination_firewall_zone_id,
            ordered_firewall_policy_ids,
        )
        return {
            "success": True,
            "source_firewall_zone_id": source_firewall_zone_id,
            "destination_firewall_zone_id": destination_firewall_zone_id,
            "ordering": result.get("orderedFirewallPolicyIds", result),
        }
    except Exception as e:
        logger.error("Error reordering firewall policies: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to reorder firewall policies: {e}"}


@server.tool(
    name="unifi_list_firewall_zones",
    description="List controller firewall zones (V2 API).",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_firewall_zones() -> Dict[str, Any]:
    try:
        zones = await firewall_manager.get_firewall_zones()
        formatted = [firewall_zone_from_controller(z).model_dump(exclude_none=True) for z in zones]
        result = {
            "success": True,
            "site": firewall_manager._connection.site,
            "count": len(formatted),
            "zones": formatted,
        }
        if not formatted:
            result["note"] = LEGACY_ENGINE_HINT
        return result
    except Exception as exc:
        logger.error("Error listing firewall zones: %s", exc, exc_info=True)
        return {"success": False, "error": f"Failed to list firewall zones: {exc}"}


# ---- Legacy Firewall Rules (v1 REST) ----


@server.tool(
    name="unifi_list_legacy_firewall_rules",
    description=(
        "List legacy pre-zone-based firewall rules from the UniFi controller. "
        "Use this on sites that still use the legacy firewall engine and return no "
        "V2 zone-based firewall policies. Returns ruleset, rule_index, action "
        "(lowercase accept/drop/reject), source and destination addresses, ports, "
        "networks and firewall groups, protocol, connection-state matching, "
        "logging, and enabled state."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_legacy_firewall_rules() -> Dict[str, Any]:
    """Lists legacy firewall rules for the current UniFi site."""
    redact_sensitive = should_redact_sensitive_fields()
    try:
        rules = await firewall_manager.get_legacy_firewall_rules()
        formatted = [legacy_firewall_rule_from_controller(r).model_dump(exclude_none=True) for r in rules]
        return redact_sensitive_fields(
            {
                "success": True,
                "engine": "legacy",
                "site": firewall_manager._connection.site,
                "count": len(formatted),
                "rules": formatted,
            },
            redact_sensitive=redact_sensitive,
        )
    except Exception as e:
        logger.error("Error listing legacy firewall rules: %s", e, exc_info=True)
        return {
            "success": False,
            "engine": "legacy",
            "error": f"Failed to list legacy firewall rules: {e}",
        }


# ---- Firewall Groups (address-group, port-group) ----


@server.tool(
    name="unifi_list_firewall_groups",
    description="List firewall groups (address and port groups) used as reusable objects in firewall policies. "
    "Address groups contain IP addresses/CIDRs, port groups contain port numbers/ranges. "
    "These are referenced by firewall policies via ip_group_id and port_group_id fields.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_firewall_groups() -> Dict[str, Any]:
    """Lists all firewall groups."""
    try:
        groups = await firewall_manager.get_firewall_groups()
        formatted = [firewall_group_from_controller(g).model_dump(exclude_none=True) for g in groups]
        return {
            "success": True,
            "site": firewall_manager._connection.site,
            "count": len(formatted),
            "groups": formatted,
        }
    except Exception as e:
        logger.error("Error listing firewall groups: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list firewall groups: {e}"}


@server.tool(
    name="unifi_get_firewall_group_details",
    description="Get detailed configuration for a specific firewall group by ID.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_firewall_group_details(
    group_id: Annotated[str, Field(description="The unique identifier (_id) of the firewall group")],
) -> Dict[str, Any]:
    """Gets a specific firewall group."""
    redact_sensitive = should_redact_sensitive_fields()
    try:
        if not group_id:
            return {"success": False, "error": "group_id is required"}

        group = await firewall_manager.get_firewall_group_by_id(group_id)
        if not group:
            return {"success": False, "error": f"Firewall group '{group_id}' not found."}

        return redact_sensitive_fields(
            {
                "success": True,
                "group_id": group_id,
                "details": json.loads(json.dumps(group, default=str)),
            },
            redact_sensitive=redact_sensitive,
        )
    except Exception as e:
        logger.error("Error getting firewall group %s: %s", group_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get firewall group {group_id}: {e}"}


@server.tool(
    name="unifi_create_firewall_group",
    description="Create a new firewall group (address or port group). "
    "group_type must be 'address-group' (for IPs/CIDRs), 'ipv6-address-group', or 'port-group' (for port numbers/ranges). "
    "IMPORTANT: group_type cannot be changed after creation. "
    "group_members format: addresses use ['10.0.0.1', '10.0.0.0/24'], ports use ['80', '443', '8080-8090']. "
    "Requires confirmation.",
    permission_category="firewall",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_firewall_group(
    name: Annotated[str, Field(description="Name of the firewall group")],
    group_type: Annotated[
        str,
        Field(description="Type: 'address-group' (IPv4), 'ipv6-address-group' (IPv6), or 'port-group'"),
    ],
    group_members: Annotated[
        list[str],
        Field(description="List of IPs/CIDRs (for address groups) or port numbers/ranges (for port groups)"),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, creates the group. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Creates a new firewall group."""
    redact_sensitive = should_redact_sensitive_fields()
    group_data = {
        "name": name,
        "group_type": group_type,
        "group_members": group_members,
    }

    if not confirm:
        return redact_sensitive_fields(
            create_preview(
                resource_type="firewall_group",
                resource_data=group_data,
                resource_name=name,
            ),
            redact_sensitive=redact_sensitive,
        )

    try:
        result = await firewall_manager.create_firewall_group(group_data)
        if result:
            return redact_sensitive_fields(
                {
                    "success": True,
                    "message": f"Firewall group '{name}' created successfully.",
                    "group": json.loads(json.dumps(result, default=str)),
                },
                redact_sensitive=redact_sensitive,
            )
        return {"success": False, "error": f"Failed to create firewall group '{name}'."}
    except Exception as e:
        logger.error("Error creating firewall group: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to create firewall group: {e}"}


@server.tool(
    name="unifi_update_firewall_group",
    description="Update an existing firewall group. Requires the full group object "
    "(PUT replaces entire resource). group_type cannot be changed. Requires confirmation.",
    permission_category="firewall",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_firewall_group(
    group_id: Annotated[str, Field(description="The ID of the group to update")],
    group_data: Annotated[
        dict,
        Field(description="The complete updated group object with all fields"),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, updates the group. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Updates an existing firewall group."""
    redact_sensitive = should_redact_sensitive_fields()
    if not confirm:
        return redact_sensitive_fields(
            create_preview(
                resource_type="firewall_group",
                resource_data=group_data,
                resource_name=group_id,
            ),
            redact_sensitive=redact_sensitive,
        )

    try:
        success = await firewall_manager.update_firewall_group(group_id, group_data)
        if success:
            return {"success": True, "message": f"Firewall group '{group_id}' updated successfully."}
        return {"success": False, "error": f"Failed to update firewall group '{group_id}'."}
    except Exception as e:
        logger.error("Error updating firewall group %s: %s", group_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update firewall group '{group_id}': {e}"}


@server.tool(
    name="unifi_delete_firewall_group",
    description="Delete a firewall group. Requires confirmation. "
    "WARNING: Firewall policies referencing this group via ip_group_id or port_group_id may break.",
    permission_category="firewall",
    permission_action="delete",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def delete_firewall_group(
    group_id: Annotated[str, Field(description="The ID of the group to delete")],
    confirm: Annotated[
        bool,
        Field(description="When true, deletes the group. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Deletes a firewall group."""
    if not confirm:
        return delete_preview(
            resource_type="firewall_group",
            resource_id=group_id,
            resource_data={"group_id": group_id},
            resource_name=group_id,
            warnings=["Firewall policies referencing this group via ip_group_id or port_group_id may break."],
        )

    try:
        success = await firewall_manager.delete_firewall_group(group_id)
        if success:
            return {"success": True, "message": f"Firewall group '{group_id}' deleted successfully."}
        return {"success": False, "error": f"Failed to delete firewall group '{group_id}'."}
    except Exception as e:
        logger.error("Error deleting firewall group %s: %s", group_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to delete firewall group '{group_id}': {e}"}


@server.tool(
    name="unifi_delete_firewall_policy",
    description=(
        "Delete a firewall policy by ID. Requires confirmation. "
        "WARNING: Removing an ALLOW rule may block traffic. Removing a BLOCK rule may open access."
    ),
    permission_category="firewall_policies",
    permission_action="delete",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def delete_firewall_policy(
    policy_id: Annotated[
        str,
        Field(
            description="Unique identifier (_id) of the firewall policy to delete (from unifi_list_firewall_policies)"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(
            description="When true, deletes the policy. When false (default), returns a preview. "
            "WARNING: Removing an ALLOW rule may block traffic"
        ),
    ] = False,
) -> Dict[str, Any]:
    """Delete a firewall policy by ID."""
    if not confirm:
        return delete_preview(
            resource_type="firewall_policy",
            resource_id=policy_id,
            resource_data={"policy_id": policy_id},
            resource_name=policy_id,
            warnings=["Removing an ALLOW rule may block traffic. Removing a BLOCK rule may open access."],
        )

    try:
        success = await firewall_manager.delete_firewall_policy(policy_id)
        if success:
            return {"success": True, "message": "Firewall policy '%s' deleted successfully." % policy_id}
        return {"success": False, "error": "Failed to delete firewall policy '%s'." % policy_id}
    except Exception as e:
        logger.error("Error deleting firewall policy %s: %s", policy_id, e, exc_info=True)
        return {"success": False, "error": "Failed to delete firewall policy %s: %s" % (policy_id, e)}
