"""
QoS tools for Unifi Network MCP server.
"""

import json
import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.confirmation import create_preview, toggle_preview, update_preview
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.models._actions import QosRuleSimpleInput
from unifi_core.network.models.qos import (
    from_controller as qos_from_controller,
)
from unifi_core.network.models.qos import (
    to_controller_update as qos_to_update,
)
from unifi_network_mcp.runtime import qos_manager, server

logger = logging.getLogger(__name__)


@server.tool(
    name="unifi_list_qos_rules",
    description="List all QoS rules on the Unifi Network controller for the current site.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_qos_rules() -> Dict[str, Any]:
    """Lists all Quality of Service (QoS) rules configured for the current UniFi site.

    Returns:
        A dictionary containing:
        - success (bool): Indicates if the operation was successful.
        - site (str): The identifier of the UniFi site queried.
        - count (int): The number of QoS rules found.
        - qos_rules (List[Dict]): A list of QoS rules, each containing summary info:
            - id (str): The unique identifier (_id) of the rule.
            - name (str): The user-defined name of the rule.
            - enabled (bool): Whether the rule is currently active.
            # Add other simple summary fields if available and useful
        - error (str, optional): An error message if the operation failed.

    Example response (success):
    {
        "success": True,
        "site": "default",
        "count": 1,
        "qos_rules": [
            {
                "id": "60d4e5f6a7b8c9d0e1f2a3b4",
                "name": "VoIP Prioritization",
                "enabled": True
            }
        ]
    }
    """
    try:
        qos_rules = await qos_manager.get_qos_rules()
        rules_raw = [r.raw if hasattr(r, "raw") else r for r in qos_rules]
        formatted_rules = [qos_from_controller(r).model_dump(exclude_none=True) for r in rules_raw]
        return {
            "success": True,
            "site": qos_manager._connection.site,
            "count": len(formatted_rules),
            "qos_rules": formatted_rules,
        }
    except Exception as e:
        logger.error("Error listing QoS rules: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list QoS rules: {e}"}


@server.tool(
    name="unifi_get_qos_rule_details",
    description="Get details for a specific QoS rule by ID.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_qos_rule_details(
    rule_id: Annotated[str, Field(description="Unique identifier (_id) of the QoS rule (from unifi_list_qos_rules)")],
) -> Dict[str, Any]:
    """Gets the detailed configuration of a specific QoS rule by its ID.

    Args:
        rule_id (str): The unique identifier (_id) of the QoS rule.

    Returns:
        A dictionary containing:
        - success (bool): Indicates if the operation was successful.
        - site (str): The identifier of the UniFi site queried.
        - rule_id (str): The ID of the rule requested.
        - details (Dict[str, Any]): A dictionary containing the raw configuration details
          of the QoS rule as returned by the UniFi controller.
        - error (str, optional): An error message if the operation failed (e.g., rule not found).

    Example response (success):
    {
        "success": True,
        "site": "default",
        "rule_id": "60d4e5f6a7b8c9d0e1f2a3b4",
        "details": {
            "_id": "60d4e5f6a7b8c9d0e1f2a3b4",
            "name": "VoIP Prioritization",
            "enabled": True,
            "interface": "WAN",
            "direction": "upload",
            "bandwidth_limit_kbps": 500,
            "dscp_value": 46,
            "site_id": "...",
            # ... other fields
        }
    }
    """
    if not rule_id:
        return {"success": False, "error": "rule_id is required"}
    try:
        rule = await qos_manager.get_qos_rule_details(rule_id)
        return {
            "success": True,
            "site": qos_manager._connection.site,
            "rule_id": rule_id,
            "details": json.loads(json.dumps(rule, default=str)),
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting QoS rule %s: %s", rule_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get QoS rule {rule_id}: {e}"}


@server.tool(
    name="unifi_toggle_qos_rule_enabled",  # Renamed from update_qos_rule_state
    description="Enable or disable a specific QoS rule by ID. Requires confirmation.",
    permission_category="qos_rules",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def toggle_qos_rule_enabled(
    rule_id: Annotated[
        str, Field(description="Unique identifier (_id) of the QoS rule to toggle (from unifi_list_qos_rules)")
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, executes the toggle. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Enables or disables a specific QoS rule. Requires confirmation.

    Args:
        rule_id (str): The unique identifier (_id) of the QoS rule to toggle.
        confirm (bool): Must be explicitly set to `True` to execute the toggle operation. Defaults to `False`.

    Returns:
        A dictionary containing:
        - success (bool): Indicates if the operation was successful.
        - rule_id (str): The ID of the rule toggled.
        - enabled (bool): The new state of the rule (True if enabled, False if disabled).
        - message (str): A confirmation message.
        - error (str, optional): An error message if the operation failed.

    Example response (success):
    {
        "success": True,
        "rule_id": "60d4e5f6a7b8c9d0e1f2a3b4",
        "enabled": false,
        "message": "QoS rule 'VoIP Prioritization' (60d4e5f6a7b8c9d0e1f2a3b4) toggled to disabled."
    }
    """
    if not rule_id:
        return {"success": False, "error": "rule_id is required"}

    try:
        # Fetch the rule first to determine current state and name
        rule = await qos_manager.get_qos_rule_details(rule_id)
        if not rule:
            return {
                "success": False,
                "error": f"QoS rule with ID '{rule_id}' not found.",
            }

        if not confirm:
            return toggle_preview(
                resource_type="qos_rule",
                resource_id=rule_id,
                resource_name=rule.get("name") or rule.get("description"),
                current_enabled=rule.get("enabled", True),
                additional_info={"bandwidth_limit": rule.get("bandwidth_limit_kbps")},
            )

        current_state = rule.get("enabled", False)
        new_state = not current_state
        rule_name = rule.get("name", rule_id)

        logger.info("Attempting to toggle QoS rule '%s' (%s) to %s", rule_name, rule_id, new_state)

        update_data = qos_to_update({"enabled": new_state})
        success = await qos_manager.update_qos_rule(rule_id, update_data)

        if success:
            # Fetch again to confirm state
            rule_after_toggle = await qos_manager.get_qos_rule_details(rule_id)
            final_state = rule_after_toggle.get("enabled", new_state) if rule_after_toggle else new_state

            logger.info("Successfully toggled QoS rule '%s' (%s) enabled status to %s", rule_name, rule_id, final_state)
            return {
                "success": True,
                "rule_id": rule_id,
                "enabled": final_state,
                "message": f"QoS rule '{rule_name}' ({rule_id}) toggled to {'enabled' if final_state else 'disabled'}.",
            }
        else:
            logger.error("Failed to toggle QoS rule '%s' (%s). Manager returned false.", rule_name, rule_id)
            # Fetch state after failure
            rule_after_fail = await qos_manager.get_qos_rule_details(rule_id)
            state_after = rule_after_fail.get("enabled", "unknown") if rule_after_fail else "unknown"
            return {
                "success": False,
                "rule_id": rule_id,
                "state_after_attempt": state_after,
                "error": f"Failed to toggle QoS rule '{rule_name}' ({rule_id}). Check server logs.",
            }

    except Exception as e:
        logger.error("Error toggling QoS rule %s state: %s", rule_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to toggle QoS rule {rule_id} state: {e}"}


# --- NEW UPDATE QOS RULE TOOL ---
@server.tool(
    name="unifi_update_qos_rule",
    description="Update specific fields of an existing QoS rule. Requires confirmation.",
    permission_category="qos_rules",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_qos_rule(
    rule_id: Annotated[
        str, Field(description="Unique identifier (_id) of the QoS rule to update (from unifi_list_qos_rules)")
    ],
    update_data: Annotated[
        Dict[str, Any],
        Field(
            description="Dictionary of fields to update. Allowed keys: name, interface ('WAN'/'LAN'), direction ('upload'/'download'), bandwidth_limit_kbps (int), target_ip_address (IP), target_subnet (CIDR), dscp_value (0-63), enabled (bool)"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the update. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Updates specific fields of an existing Quality of Service (QoS) rule.

    Allows modifying properties like name, bandwidth limits, targeting, DSCP values, etc.
    Only provided fields are updated. Requires confirmation.

    Args:
        rule_id (str): The unique identifier (_id) of the QoS rule to update.
        update_data (Dict[str, Any]): Dictionary of fields to update.
            Allowed fields (all optional):
            - name (string): New name for the rule.
            - interface (string): New interface (e.g., 'WAN', 'LAN').
            - direction (string): New direction ('upload', 'download').
            - bandwidth_limit_kbps (integer): New bandwidth limit in Kbps.
            - target_ip_address (string): New target IP address.
            - target_subnet (string): New target subnet (CIDR).
            - dscp_value (integer): New DSCP value (0-63).
            - enabled (boolean): New enabled state.
        confirm (bool): Must be set to `True` to execute. Defaults to `False`.

    Returns:
        Dict: Success status, ID, updated fields, details, or error message.
        Example (success):
        {
            "success": True,
            "rule_id": "60d4e5f6a7b8c9d0e1f2a3b4",
            "updated_fields": ["name", "bandwidth_limit_kbps"],
            "details": { ... updated rule details ... }
        }
    """
    if not rule_id:
        return {"success": False, "error": "rule_id is required"}
    if not update_data:
        return {"success": False, "error": "update_data cannot be empty"}

    # Translate to controller-safe mutable fields
    validated_data = qos_to_update(update_data)
    if not validated_data:
        logger.warning("QoS rule update data for ID %s is empty after filtering.", rule_id)
        return {
            "success": False,
            "error": "No valid mutable fields provided for update.",
        }

    if not confirm:
        return update_preview(
            resource_type="qos_rule",
            resource_id=rule_id,
            resource_name=rule_id,
            current_state={},
            updates=validated_data,
        )

    updated_fields_list = list(validated_data.keys())
    try:
        merged = await qos_manager.update_qos_rule(rule_id, validated_data)
        return {
            "success": True,
            "rule_id": rule_id,
            "updated_fields": updated_fields_list,
            "details": json.loads(json.dumps(merged, default=str)),
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating QoS rule %s: %s", rule_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update QoS rule {rule_id}: {e}"}


@server.tool(
    name="unifi_create_qos_rule",
    description="Create a new QoS rule on the Unifi Network controller. Requires confirmation.",
    permission_category="qos_rules",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_qos_rule(
    qos_data: Annotated[
        Dict[str, Any],
        Field(
            description="QoS rule configuration dict. Required: name (str), interface ('WAN'/'LAN'), direction ('upload'/'download'), bandwidth_limit_kbps (int). Optional: target_ip_address (IP), target_subnet (CIDR), dscp_value (0-63), enabled (bool, default true)"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, creates the rule. When false (default), validates and returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Creates a new Quality of Service (QoS) rule with schema validation. Requires confirmation.

    Args:
        qos_data: Dictionary containing the QoS rule configuration.
            Required fields:
            - name (string): Descriptive name for the QoS rule.
            - interface (string): Network interface (e.g., 'WAN', 'LAN').
            - direction (string): Direction ('upload' or 'download').
            - bandwidth_limit_kbps (integer): Bandwidth limit in Kbps.

            Optional fields:
            - target_ip_address (string): Specific IP address target.
            - target_subnet (string): Subnet target (CIDR notation).
            - dscp_value (integer): DSCP value (0-63).
            - enabled (boolean): Whether the rule is enabled (default: true).
        confirm (bool): Must be set to `True` to execute. Defaults to `False`.

    Example:
    {
        "name": "Zoom Meetings High Priority",
        "interface": "WAN",
        "direction": "upload",
        "bandwidth_limit_kbps": 1000,
        "target_subnet": "192.168.1.0/24",
        "dscp_value": 46,
        "enabled": true
    }

    Returns:
    - success (boolean): Whether the operation succeeded.
    - rule_id (string): ID of the created rule if successful.
    - details (object): Details of the created rule.
    - error (string): Error message if unsuccessful.
    """
    # Filter input to known mutable fields
    validated_data = qos_to_update(qos_data) if qos_data else {}
    # Required field check
    required = ["name", "interface", "direction", "bandwidth_limit_kbps"]
    missing = [k for k in required if k not in validated_data]
    if missing:
        return {"success": False, "error": f"Missing required fields: {missing}"}

    if not confirm:
        return create_preview(
            resource_type="qos_rule",
            resource_data=validated_data,
            resource_name=validated_data.get("name"),
        )

    rule_name = validated_data["name"]
    logger.info("Attempting to create QoS rule '%s'", rule_name)
    try:
        # Pass validated data directly to manager
        created_rule = await qos_manager.create_qos_rule(validated_data)

        # Check manager response
        if created_rule and created_rule.get("_id"):
            new_rule_id = created_rule.get("_id")
            logger.info("Successfully created QoS rule '%s' with ID %s", rule_name, new_rule_id)
            return {
                "success": True,
                "site": qos_manager._connection.site,
                "message": f"QoS rule '{rule_name}' created successfully.",
                "rule_id": new_rule_id,
                "details": json.loads(json.dumps(created_rule, default=str)),
            }
        else:
            error_msg = (
                created_rule.get("error", "Manager returned failure")
                if isinstance(created_rule, dict)
                else "Manager returned non-dict or failure"
            )
            logger.error("Failed to create QoS rule '%s'. Reason: %s", rule_name, error_msg)
            return {
                "success": False,
                "error": f"Failed to create QoS rule '{rule_name}'. {error_msg}",
            }

    except Exception as e:
        logger.error("Error creating QoS rule '%s': %s", rule_name, e, exc_info=True)
        return {"success": False, "error": f"Failed to create QoS rule '{rule_name}': {e}"}


@server.tool(
    name="unifi_create_simple_qos_rule",
    description=("Create a QoS rule using a simplified high-level schema. Returns a preview unless confirm=true."),
    permission_category="qos_rules",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_simple_qos_rule(
    rule: Annotated[
        Dict[str, Any],
        Field(
            description="Simplified QoS rule dict. Required: name (str), interface ('wan'/'lan'), direction ('upload'/'download'), limit_kbps (int). Optional: enabled (bool, default true), dscp_value (int 0-63), target (dict with type='ip'/'subnet' and value, e.g. {'type': 'ip', 'value': '192.168.1.50'})"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, creates the rule. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Create a QoS rule with a compact schema and optional preview.

    High-level schema (validated internally):
    {
        "name": "Zoom Upload Limit",
        "interface": "wan",
        "direction": "upload",
        "limit_kbps": 2000,
        "enabled": true,             # optional – default true
        "dscp_value": 46,            # optional
        "target": {                  # optional – omit for all clients
            "type": "ip",          # "ip" | "subnet"
            "value": "192.168.1.50"
        }
    }

    If *confirm* is False (default) the function only validates and returns the
    fully-expanded UniFi payload in a preview. Set *confirm* to True to commit
    the rule and return the controller's response.
    """

    # --- Step 1: validate high-level schema --------------------------------
    from pydantic import ValidationError

    try:
        r = QosRuleSimpleInput(**rule)
    except ValidationError as exc:
        return {"success": False, "error": exc.errors()[0]["msg"]}

    # --- Step 2: translate into controller payload -------------------------
    payload: Dict[str, Any] = {
        "name": r.name,
        "interface": r.interface,
        "direction": r.direction,
        "bandwidth_limit_kbps": r.limit_kbps,
        "enabled": r.enabled,
    }

    if r.dscp_value is not None:
        payload["dscp_value"] = r.dscp_value

    target = r.target
    if target:
        t_type = target.type.lower()
        value = target.value
        if t_type == "ip":
            payload["target_ip_address"] = value
        elif t_type == "subnet":
            payload["target_subnet"] = value
        else:
            return {"success": False, "error": f"Unsupported target type '{t_type}'"}

    # --- Step 3: preview or commit -----------------------------------------
    if not confirm:
        return {
            "success": True,
            "preview": payload,
            "message": "Set confirm=true to apply.",
        }

    created = await qos_manager.create_qos_rule(payload)
    if created is None or not isinstance(created, dict):
        return {
            "success": False,
            "error": "Controller rejected QoS rule creation. See logs.",
        }

    return {
        "success": True,
        "rule_id": created.get("_id"),
        "details": json.loads(json.dumps(created, default=str)),
    }
