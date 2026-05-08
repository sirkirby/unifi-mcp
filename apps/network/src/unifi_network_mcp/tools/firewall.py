"""
Firewall policy tools for Unifi Network MCP server.
"""

import json
import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.confirmation import create_preview, toggle_preview, update_preview
from unifi_network_mcp.runtime import firewall_manager, network_manager, server
from unifi_network_mcp.validator_registry import UniFiValidatorRegistry  # Added

logger = logging.getLogger(__name__)


@server.tool(
    name="unifi_list_firewall_policies",
    description=(
        "List firewall policies configured on the Unifi Network controller. "
        "Includes zone-based targeting details (zone_id, matching_target, matching_target_type, "
        "IPs, network IDs) when present on newer firmware."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_firewall_policies(
    include_predefined: Annotated[
        bool,
        Field(
            description="When true, includes predefined system policies in results. Default false (user-defined only)"
        ),
    ] = False,
) -> Dict[str, Any]:
    """Lists firewall policies for the current UniFi site.

    Returns both legacy (ruleset-based) and zone-based policy fields.
    Zone-based fields (zone_id, matching_target, matching_target_type) are
    included in source/destination when present in the API response.
    """
    try:
        policies = await firewall_manager.get_firewall_policies(include_predefined=include_predefined)
        policies_raw = [p.raw if hasattr(p, "raw") else p for p in policies]

        formatted_policies = []
        for p in policies_raw:
            entry = {
                "id": p.get("_id"),
                "name": p.get("name"),
                "enabled": p.get("enabled"),
                "action": p.get("action"),
                "rule_index": p.get("index", p.get("rule_index")),
                "description": p.get("description", p.get("desc", "")),
            }
            # Include ruleset when present (legacy policies)
            if p.get("ruleset"):
                entry["ruleset"] = p["ruleset"]
            # Include zone-based source/destination targeting when present
            for direction in ("source", "destination"):
                ep = p.get(direction)
                if ep and isinstance(ep, dict):
                    targeting = {
                        "zone_id": ep.get("zone_id"),
                        "matching_target": ep.get("matching_target"),
                    }
                    if ep.get("matching_target_type"):
                        targeting["matching_target_type"] = ep["matching_target_type"]
                    if ep.get("ips"):
                        targeting["ips"] = ep["ips"]
                    if ep.get("network_ids"):
                        targeting["network_ids"] = ep["network_ids"]
                    if ep.get("client_macs"):
                        targeting["client_macs"] = ep["client_macs"]
                    entry[direction] = targeting
            formatted_policies.append(entry)

        return {
            "success": True,
            "site": firewall_manager._connection.site,
            "count": len(formatted_policies),
            "policies": formatted_policies,
        }
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
        return {
            "success": True,
            "policy_id": policy_id,
            "details": json.loads(json.dumps(policy, default=str)),
        }
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
                    "ruleset": policy.get("ruleset"),
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


def _is_zone_based_policy(policy_data: Dict[str, Any]) -> bool:
    """Detect whether policy_data uses zone-based targeting (newer firmware).

    Zone-based policies have source/destination dicts with zone_id and no ruleset.
    Legacy policies have a ruleset field with lowercase actions.
    """
    if policy_data.get("ruleset"):
        return False
    for direction in ("source", "destination"):
        ep = policy_data.get(direction)
        if isinstance(ep, dict) and ep.get("zone_id"):
            return True
    # Uppercase actions are a zone-based indicator
    action = policy_data.get("action", "")
    if isinstance(action, str) and action in ("ALLOW", "BLOCK", "REJECT"):
        return True
    return False


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
            expected = "SPECIFIC" if target == "IP" else "OBJECT"
            return "%s.matching_target_type is required when matching_target is '%s'. Use '%s'." % (
                direction,
                target,
                expected,
            )
        if target == "IP" and not ep.get("ips"):
            return "%s.ips array is required when matching_target is 'IP'." % direction
        if target == "NETWORK" and not ep.get("network_ids"):
            return "%s.network_ids array is required when matching_target is 'NETWORK'." % direction
    return None


@server.tool(
    name="unifi_create_firewall_policy",
    description=(
        "Create a new firewall policy with schema validation. Supports both legacy "
        "ruleset-based policies (action: accept/drop/reject) and zone-based policies "
        "(action: ALLOW/BLOCK/REJECT with source/destination zone_id targeting). "
        "Format is auto-detected from the policy_data structure."
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
                "Firewall policy configuration dict. Two formats supported:\n"
                "Legacy (ruleset-based): Required: name, ruleset (WAN_IN, LAN_OUT, etc.), "
                "action (accept/drop/reject), index. Optional: enabled, description, protocol, "
                "connection_states, source, destination, logging.\n"
                "Zone-based (firmware 5.0+): Required: name, action (ALLOW/BLOCK/REJECT), "
                "source (object with zone_id, matching_target), destination (same structure). "
                "For IP targeting: matching_target='IP', matching_target_type='SPECIFIC', ips=[...]. "
                "For network targeting: matching_target='NETWORK', matching_target_type='OBJECT', "
                "network_ids=[...]. For any in zone: matching_target='ANY'."
            )
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, creates the policy. When false (default), validates and returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Create a firewall policy. Auto-detects legacy vs zone-based format."""
    if not isinstance(policy_data, dict) or not policy_data:
        return {
            "success": False,
            "error": "policy_data must be a non-empty dictionary.",
        }

    # Auto-detect format and validate accordingly. Zone-based (V2) policies
    # are rejected by the controller without fields like ``schedule`` and
    # ``create_allow_respond``, so we fill missing top-level properties from
    # schema defaults on that path. Legacy policies don't need this.
    zone_based = _is_zone_based_policy(policy_data)

    if zone_based:
        # Controller's V2 enums are strictly upper-case. Normalize common
        # mixed-case input before validation so users can pass natural forms
        # like "IPv4" or lowercase state names.
        policy_data = _normalize_v2_policy_casing(policy_data)
        schema_key = "firewall_policy_v2_create"
        is_valid, error_msg, validated_data = UniFiValidatorRegistry.validate_and_apply_defaults(
            schema_key, policy_data
        )
    else:
        schema_key = "firewall_policy_create"
        is_valid, error_msg, validated_data = UniFiValidatorRegistry.validate(schema_key, policy_data)

    if not is_valid:
        logger.warning("Invalid firewall policy data: %s", error_msg)
        return {"success": False, "error": "Validation Error: %s" % error_msg}

    if zone_based:
        # Validate zone targeting requirements (matching_target_type, ips, network_ids)
        targeting_error = _validate_zone_targeting(validated_data)
        if targeting_error:
            return {"success": False, "error": targeting_error}
        # Normalize action to uppercase
        action = validated_data.get("action", "")
        if action.upper() not in ("ALLOW", "BLOCK", "REJECT"):
            return {"success": False, "error": "Invalid action '%s'. Must be ALLOW, BLOCK, or REJECT." % action}
        validated_data["action"] = action.upper()
    else:
        # Normalize action to lowercase for legacy format
        action = validated_data.get("action", "")
        if not isinstance(action, str) or action.lower() not in ("accept", "drop", "reject"):
            return {
                "success": False,
                "error": "Invalid action '%s'. Must be one of 'accept', 'drop', 'reject'." % action,
            }
        validated_data["action"] = action.lower()

    policy_name = validated_data.get("name", "Unnamed Policy")

    if not confirm:
        return create_preview(
            resource_type="firewall_policy",
            resource_data=validated_data,
            resource_name=policy_name,
        )

    logger.info("Creating firewall policy '%s'", policy_name)

    try:
        created_policy_obj = await firewall_manager.create_firewall_policy(validated_data)

        if created_policy_obj and hasattr(created_policy_obj, "raw"):
            created_policy_details = created_policy_obj.raw
            new_policy_id = created_policy_details.get("_id", "unknown")
            logger.info("Created firewall policy '%s' with ID %s", policy_name, new_policy_id)
            return {
                "success": True,
                "message": "Firewall policy '%s' created successfully." % policy_name,
                "policy_id": new_policy_id,
                "details": json.loads(json.dumps(created_policy_details, default=str)),
            }
        else:
            logger.error("Failed to create firewall policy '%s'. Manager returned None.", policy_name)
            return {
                "success": False,
                "error": "Failed to create firewall policy '%s'. Check server logs." % policy_name,
            }

    except Exception as e:
        logger.error("Error creating firewall policy '%s': %s", policy_name, e, exc_info=True)
        return {"success": False, "error": "Failed to create firewall policy '%s': %s" % (policy_name, e)}


# Controller-side V2 firewall enums are Java-style and strictly upper-case.
# Live-controller probe (issue #203 follow-up) confirmed the accepted values:
#   ip_version            → BOTH | IPV4 | IPV6
#   connection_state_type → ALL | RESPOND_ONLY | CUSTOM
#   connection_states[]   → NEW | RELATED | INVALID | ESTABLISHED
# Normalize to upper-case so users can pass natural forms ("IPv4", "new").
def _normalize_v2_policy_casing(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a shallow copy of ``data`` with V2 firewall enum fields upper-cased.

    Only normalizes string values; non-string input is left for schema validation
    to flag with its own error.
    """
    out = dict(data)
    if isinstance(out.get("ip_version"), str):
        out["ip_version"] = out["ip_version"].upper()
    if isinstance(out.get("connection_state_type"), str):
        out["connection_state_type"] = out["connection_state_type"].upper()
    states = out.get("connection_states")
    if isinstance(states, list):
        out["connection_states"] = [s.upper() if isinstance(s, str) else s for s in states]
    return out


# Fields that indicate zone-based update data (not in the legacy update schema)
_V2_UPDATE_FIELDS = frozenset(
    {
        "source",
        "destination",
        "ip_version",
        "connection_state_type",
        "connection_states",
        "create_allow_respond",
        "match_ip_sec",
        "match_opposite_protocol",
        "schedule",
        "icmp_typename",
        "icmp_v6_typename",
    }
)


@server.tool(
    name="unifi_update_firewall_policy",
    description=(
        "Update specific fields of an existing firewall policy by ID. Supports both "
        "legacy fields (ruleset, action as accept/drop/reject) and zone-based fields "
        "(source, destination, action as ALLOW/BLOCK/REJECT, ip_version, etc.)."
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
                "Dictionary of fields to update. Accepts both legacy and zone-based fields. "
                "Legacy: name, ruleset, action (accept/drop/reject), rule_index, protocol, "
                "src_address, dst_address, enabled, description, logging. "
                "Zone-based: name, action (ALLOW/BLOCK/REJECT), enabled, source, destination, "
                "protocol, ip_version, index, logging, connection_state_type, connection_states, schedule."
            )
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the update. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Update specific fields of an existing firewall policy. Requires confirmation."""
    if not policy_id:
        return {"success": False, "error": "policy_id is required"}
    if not update_data:
        return {"success": False, "error": "update_data cannot be empty"}

    # Normalize action if provided (accept both cases)
    if "action" in update_data:
        action = update_data["action"]
        if isinstance(action, str):
            upper = action.upper()
            lower = action.lower()
            if upper in ("ALLOW", "BLOCK", "REJECT"):
                update_data["action"] = upper
            elif lower in ("accept", "drop", "reject"):
                update_data["action"] = lower
            else:
                return {"success": False, "error": "Invalid action '%s'." % action}

    # Detect whether this contains zone-based fields
    has_v2_fields = bool(set(update_data.keys()) & _V2_UPDATE_FIELDS)

    if has_v2_fields:
        # Normalize V2 enum casing before validation so common mixed-case input
        # ("IPv4", "custom", ["new"]) survives the strict-uppercase enum check.
        update_data = _normalize_v2_policy_casing(update_data)
        is_valid, error_msg, validated_data = UniFiValidatorRegistry.validate(
            "firewall_policy_v2_update", update_data
        )
        if not is_valid:
            logger.warning("Invalid V2 firewall policy update data for ID %s: %s", policy_id, error_msg)
            return {"success": False, "error": "Invalid update data: %s" % error_msg}
        if not validated_data:
            return {"success": False, "error": "Update data is effectively empty or invalid."}
    else:
        is_valid, error_msg, validated_data = UniFiValidatorRegistry.validate("firewall_policy_update", update_data)
        if not is_valid:
            logger.warning("Invalid firewall policy update data for ID %s: %s", policy_id, error_msg)
            return {"success": False, "error": "Invalid update data: %s" % error_msg}
        if not validated_data:
            return {"success": False, "error": "Update data is effectively empty or invalid."}

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
            return update_preview(
                resource_type="firewall_policy",
                resource_id=policy_id,
                resource_name=current.get("name"),
                current_state=current,
                updates=validated_data,
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
                return {
                    "success": False,
                    "policy_id": policy_id,
                    "error": "Controller accepted the request but did not apply changes to: %s" % ", ".join(mismatched),
                    "details": json.loads(json.dumps(updated_details, default=str)),
                }

            logger.info("Updated firewall policy (%s)", policy_id)
            return {
                "success": True,
                "policy_id": policy_id,
                "updated_fields": updated_fields_list,
                "details": json.loads(json.dumps(updated_details, default=str)),
            }
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
    name="unifi_create_simple_firewall_policy",
    description=(
        "Create a firewall policy using a simplified high-level schema. "
        "Accepts friendly src/dst selectors and returns a preview unless confirm=true."
    ),
    permission_category="firewall_policies",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_simple_firewall_policy(
    policy: Annotated[
        Dict[str, Any],
        Field(
            description="Simplified firewall policy dict. Required: name (str), ruleset (str: 'LAN_OUT', 'WAN_IN', etc.), action (str: 'drop', 'accept', 'reject'), src (dict with type+value), dst (dict with type+value). src/dst type options: 'zone' (value: 'wan'/'lan'), 'network' (value: network name/ID), 'client_mac' (value: MAC address), 'ip_group' (value: group ID). Optional: protocol, index, enabled, log"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, creates the policy. When false (default), validates and returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Create a firewall rule with a compact schema and optional preview.

    High-level schema (validated internally):
    {
        "name":    "Block Xbox",
        "ruleset": "LAN_OUT",
        "action":  "drop",
        "src": {"type": "client_mac", "value": "4c:3b:df:2c:c8:c6"},
        "dst": {"type": "zone", "value": "wan"},
        "protocol": "all",           # optional
        "index": 2010,                # optional – will auto-place if omitted
        "enabled": true,              # default true
        "log": true                   # default false
    }

    If *confirm* is False (default) the function only validates and returns the
    fully-expanded UniFi payload in a preview. Set *confirm* to True to commit
    the rule and return the controller's response.
    """

    # --- Step 1: validate high-level schema --------------------------------
    is_valid, error, validated = UniFiValidatorRegistry.validate("firewall_policy_simple", policy)
    if not is_valid or validated is None:
        return {"success": False, "error": error or "Validation failed"}

    pol = validated  # rename for brevity

    # --- Step 2: translate src/dst selectors into UniFi endpoint structure --
    async def _resolve_endpoint(ep: Dict[str, str]) -> Dict[str, Any]:
        etype = ep["type"].lower()
        value = ep["value"].strip()
        base = {
            "match_opposite_ports": False,
            "port_matching_type": "any",
        }
        if etype == "zone":
            return {**base, "matching_target": "zone", "zone_id": value.lower()}
        if etype == "network":
            # Accept network name or id
            networks = await network_manager.get_networks()
            net = next(
                (n for n in networks if n.get("_id") == value or n.get("name") == value),
                None,
            )
            if not net:
                raise ValueError(f"Network '{value}' not found")
            return {
                **base,
                "matching_target": "network_id",
                "network_id": net["_id"],
                "zone_id": "lan",  # network selectors still need zone for API; default lan
            }
        if etype == "client_mac":
            return {
                **base,
                "matching_target": "client_macs",
                "client_macs": [value.lower()],
                "zone_id": "lan",
            }
        if etype == "ip_group":
            return {
                **base,
                "matching_target": "ip_group_id",
                "ip_group_id": value,
                "zone_id": "lan",
            }
        raise ValueError(f"Unsupported selector type '{etype}'")

    try:
        src_ep = await _resolve_endpoint(pol["src"])
        dst_ep = await _resolve_endpoint(pol["dst"])
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    # --- Step 3: build controller payload ----------------------------------
    payload: Dict[str, Any] = {
        "name": pol["name"],
        "ruleset": pol["ruleset"],
        "action": pol["action"].lower(),
        "index": pol.get("index", 3000),  # fall-back index
        "enabled": pol.get("enabled", True),
        "logging": pol.get("log", False),
        "protocol": pol.get("protocol", "all"),
        # sane defaults for connection states (inclusive all)
        "connection_state_type": "inclusive",
        "connection_states": ["new", "established", "related", "invalid"],
        "source": src_ep,
        "destination": dst_ep,
    }

    if not confirm:
        return create_preview(
            resource_type="firewall_policy",
            resource_data=payload,
            resource_name=pol["name"],
        )

    # --- Step 4: call manager to create policy -----------------------------
    # firewall_manager.create_firewall_policy raises on API errors so the
    # controller's errorCode/message surface to the caller — wrap to return a
    # structured error response instead of letting it propagate.
    try:
        created = await firewall_manager.create_firewall_policy(payload)
    except Exception as exc:
        logger.error("Error creating migrated firewall policy '%s': %s", pol["name"], exc, exc_info=True)
        return {"success": False, "error": f"Failed to create firewall policy '{pol['name']}': {exc}"}

    if created is None:
        return {
            "success": False,
            "error": "Controller rejected policy creation. See logs.",
        }

    return {
        "success": True,
        "policy_id": created.id,
        "details": created.raw,
    }


@server.tool(
    name="unifi_list_firewall_zones",
    description="List controller firewall zones (V2 API).",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_firewall_zones() -> Dict[str, Any]:
    try:
        zones = await firewall_manager.get_firewall_zones()
        formatted = [
            {
                "id": z.get("_id"),
                "name": z.get("name"),
                "zone_key": z.get("zone_key", ""),
            }
            for z in zones
        ]
        return {
            "success": True,
            "site": firewall_manager._connection.site,
            "count": len(formatted),
            "zones": formatted,
        }
    except Exception as exc:
        logger.error("Error listing firewall zones: %s", exc, exc_info=True)
        return {"success": False, "error": f"Failed to list firewall zones: {exc}"}


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
        formatted = [
            {
                "id": g.get("_id"),
                "name": g.get("name"),
                "group_type": g.get("group_type"),
                "member_count": len(g.get("group_members", [])),
                "group_members": g.get("group_members", []),
            }
            for g in groups
        ]
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
    try:
        if not group_id:
            return {"success": False, "error": "group_id is required"}

        group = await firewall_manager.get_firewall_group_by_id(group_id)
        if not group:
            return {"success": False, "error": f"Firewall group '{group_id}' not found."}

        return {
            "success": True,
            "group_id": group_id,
            "details": json.loads(json.dumps(group, default=str)),
        }
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
    group_data = {
        "name": name,
        "group_type": group_type,
        "group_members": group_members,
    }

    if not confirm:
        return create_preview(
            resource_type="firewall_group",
            resource_data=group_data,
            resource_name=name,
        )

    try:
        result = await firewall_manager.create_firewall_group(group_data)
        if result:
            return {
                "success": True,
                "message": f"Firewall group '{name}' created successfully.",
                "group": json.loads(json.dumps(result, default=str)),
            }
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
    if not confirm:
        return create_preview(
            resource_type="firewall_group",
            resource_data=group_data,
            resource_name=group_id,
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
        return create_preview(
            resource_type="firewall_group",
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
        return create_preview(
            resource_type="firewall_policy",
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
