"""
Port forward tools for Unifi Network MCP server.
"""

import json
import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from unifi_core.confirmation import toggle_preview, update_preview
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.models._actions import (
    PortForwardCreateInput,
    PortForwardSimpleInput,
    PortForwardUpdateInput,
)
from unifi_core.network.models.port_forwards import (
    from_controller as pf_from_controller,
)
from unifi_core.network.models.port_forwards import (
    to_controller_update as pf_to_update,
)
from unifi_network_mcp.runtime import firewall_manager, server

logger = logging.getLogger(__name__)  # Changed logger name for consistency


@server.tool(
    name="unifi_list_port_forwards",
    description="List all port forwarding rules on your Unifi Network controller.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_port_forwards() -> Dict[str, Any]:  # Removed context, adjusted return type
    """List all port forwarding rules configured on the UniFi Network controller.

    Returns:
        A dictionary containing:
        - success (bool): Indicates if the operation was successful.
        - site (str): The identifier of the UniFi site queried.
        - count (int): The number of port forwarding rules found.
        - port_forwards (List[Dict]): A list of port forward rules, each containing:
            - id (str): The unique identifier of the rule.
            - name (str): The user-defined name of the rule.
            - enabled (bool): Whether the rule is currently active.
            - src_port (str): The destination/external port or range.
            - dst_port (str): The internal port or range to forward to.
            - protocol (str): The network protocol ('tcp', 'udp', 'tcp/udp').
            - dest_ip (str): The internal IP address to forward to.
        - error (str, optional): An error message if the operation failed.

    Example response (success):
    {
        "success": True,
        "site": "default",
        "count": 1,
        "port_forwards": [
            {
                "id": "60f5a9b3e4b0f4a7f7d6e8c1",
                "name": "Web Server",
                "enabled": True,
                "src_port": "80",
                "dst_port": "8080",
                "protocol": "tcp",
                "dest_ip": "192.168.1.100"
            }
        ]
    }
    """
    try:
        rules = await firewall_manager.get_port_forwards()
        rules_raw = [r.raw if hasattr(r, "raw") else r for r in rules]
        formatted = [pf_from_controller(r).model_dump(exclude_none=True) for r in rules_raw]
        return {
            "success": True,
            "site": firewall_manager._connection.site,
            "count": len(formatted),
            "port_forwards": formatted,
        }
    except Exception as e:
        logger.error("Error listing port forwards: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list port forwards: {e}"}


@server.tool(
    name="unifi_get_port_forward",
    description="Get a specific port forwarding rule by ID from your Unifi Network controller.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_port_forward(
    port_forward_id: Annotated[
        str, Field(description="Unique identifier (_id) of the port forwarding rule (from unifi_list_port_forwards)")
    ],
) -> Dict[str, Any]:
    """Get detailed information about a specific port forwarding rule by its ID.

    Args:
        port_forward_id (str): The unique identifier (_id) of the port forwarding rule.

    Returns:
        A dictionary containing:
        - success (bool): Indicates if the operation was successful.
        - port_forward_id (str): The ID of the rule requested.
        - details (Dict[str, Any]): A dictionary containing the raw configuration details
          of the port forwarding rule as returned by the UniFi controller.
        - error (str, optional): An error message if the operation failed (e.g., rule not found).

    Example response (success):
    {
        "success": True,
        "port_forward_id": "60f5a9b3e4b0f4a7f7d6e8c1",
        "details": {
            "_id": "60f5a9b3e4b0f4a7f7d6e8c1",
            "name": "Web Server",
            "enabled": True,
            "dst_port": "80",
            "fwd_port": "8080",
            "fwd_ip": "192.168.1.100",
            "protocol": "tcp",
            "site_id": "...",
            # ... other fields
        }
    }
    """
    if not port_forward_id:
        return {"success": False, "error": "port_forward_id is required"}
    try:
        rule_obj = await firewall_manager.get_port_forward_by_id(port_forward_id)
        rule = rule_obj.raw if hasattr(rule_obj, "raw") else rule_obj
        return {
            "success": True,
            "port_forward_id": port_forward_id,
            "details": json.loads(json.dumps(rule, default=str)),
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting port forward %s: %s", port_forward_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get port forward {port_forward_id}: {e}"}


@server.tool(
    name="unifi_toggle_port_forward",
    description="Toggle a port forwarding rule on or off on your Unifi Network controller.",
    permission_category="port_forwards",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def toggle_port_forward(
    port_forward_id: Annotated[
        str,
        Field(
            description="Unique identifier (_id) of the port forwarding rule to toggle (from unifi_list_port_forwards)"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, executes the toggle. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Enables or disables a specific port forwarding rule. Requires confirmation.

    Args:
        port_forward_id (str): The unique identifier (_id) of the port forwarding rule to toggle.
        confirm (bool): Must be explicitly set to `True` to execute the toggle operation. Defaults to `False`.

    Returns:
        A dictionary containing:
        - success (bool): Indicates if the operation was successful.
        - port_forward_id (str): The ID of the rule that was toggled.
        - enabled (bool): The new state of the rule (True if enabled, False if disabled).
        - message (str): A confirmation message indicating the action taken.
        - error (str, optional): An error message if the operation failed (e.g., permission denied,
          confirmation missing, rule not found, toggle failed).

    Example response (success):
    {
        "success": True,
        "port_forward_id": "60f5a9b3e4b0f4a7f7d6e8c1",
        "enabled": False,
        "message": "Port forward 'Web Server' toggled to disabled."
    }
    """

    try:
        if not port_forward_id:
            return {"success": False, "error": "port_forward_id is required"}

        rule_obj = await firewall_manager.get_port_forward_by_id(port_forward_id)
        rule = rule_obj.raw if (rule_obj and hasattr(rule_obj, "raw")) else rule_obj
        if not rule:
            return {
                "success": False,
                "error": f"Port forwarding rule '{port_forward_id}' not found",
            }

        rule_name = rule.get("name", port_forward_id)
        current_enabled = rule.get("enabled", False)

        # Return preview when confirm=false
        if not confirm:
            return toggle_preview(
                resource_type="port_forward",
                resource_id=port_forward_id,
                resource_name=rule_name,
                current_enabled=current_enabled,
                additional_info={
                    "dst_port": rule.get("dst_port"),
                    "fwd_ip": rule.get("fwd_ip"),
                    "fwd_port": rule.get("fwd_port"),
                },
            )

        new_state = not current_enabled

        logger.info("Attempting to toggle port forward '%s' (%s) to %s", rule_name, port_forward_id, new_state)
        update_payload = pf_to_update({"enabled": new_state})
        success = await firewall_manager.update_port_forward(port_forward_id, update_payload)

        if success:
            logger.info("Successfully toggled port forward '%s' (%s) to %s", rule_name, port_forward_id, new_state)
            return {
                "success": True,
                "port_forward_id": port_forward_id,
                "enabled": new_state,
                "message": f"Port forward '{rule_name}' toggled to {'enabled' if new_state else 'disabled'}.",
            }
        else:
            # Re-fetch to check the state if the update call failed
            rule_after_toggle_obj = await firewall_manager.get_port_forward_by_id(port_forward_id)
            rule_after_toggle = (
                rule_after_toggle_obj.raw
                if (rule_after_toggle_obj and hasattr(rule_after_toggle_obj, "raw"))
                else rule_after_toggle_obj
            )
            state_after = rule_after_toggle.get("enabled") if rule_after_toggle else "unknown"
            logger.error(
                "Failed to toggle port forward '%s' (%s). State after attempt: %s. Manager update returned false.",
                rule_name,
                port_forward_id,
                state_after,
            )
            return {
                "success": False,
                "error": f"Failed to toggle port forward '{rule_name}'. Check server logs.",
            }

    except Exception as e:
        logger.error("Error toggling port forward %s: %s", port_forward_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to toggle port forward {port_forward_id}: {e}"}


# Create Port Forward
@server.tool(
    name="unifi_create_port_forward",
    description="Create a new port forwarding rule on your Unifi Network controller using schema validation.",
    permission_category="port_forwards",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_port_forward(
    port_forward_data: Annotated[
        Dict[str, Any],
        Field(
            description="Port forward configuration dict. Required: name (str), dst_port (external port, e.g. '80' or '10000-10010'), fwd_port (internal port), fwd_ip (internal IP, e.g. '192.168.1.100'). Optional: protocol ('tcp'/'udp'/'tcp_udp', default 'tcp_udp'), enabled (bool, default true), src_ip (source IP/CIDR), log (bool)"
        ),
    ],
) -> Dict[str, Any]:
    """Create a new port forwarding rule with comprehensive validation.

    Required parameters in port_forward_data:
    - name (string): Name for the port forwarding rule
    - dst_port (string): Destination/external port (e.g., "80", "443", "22" or range "10000-10010")
    - fwd_port (string): Internal port to forward to (e.g., "80", "8080" or range "10000-10010")
    - fwd_ip (string): Internal IP address to forward to

    Optional parameters in port_forward_data:
    - protocol (string): Network protocol - "tcp", "udp", or "tcp_udp" (default: "tcp_udp")
    - enabled (boolean): Whether rule is enabled initially (default: true)
    - src_ip (string): Source IP/CIDR to match (default: any)
    - log (boolean): Whether to log rule matches (default: false)

    Example:
    {
        "name": "Web Server",
        "dst_port": "80",
        "fwd_port": "8080",
        "fwd_ip": "192.168.1.100",
        "protocol": "tcp",
        "enabled": true
    }

    Returns:
    - success (boolean): Whether the operation succeeded
    - port_forward_id (string): ID of the created rule if successful
    - details (object): Additional details about the created rule
    - error (string): Error message if unsuccessful
    """
    try:
        validated = PortForwardCreateInput(**port_forward_data)
    except ValidationError as exc:
        err = exc.errors()[0]["msg"]
        logger.warning("Invalid port forward data: %s", err)
        return {"success": False, "error": err}

    try:
        # Prepare data for the manager
        rule_data = {
            "name": validated.name,
            "dst_port": validated.dst_port,
            "fwd_port": validated.fwd_port,
            "fwd_ip": validated.fwd_ip,
            "proto": validated.protocol.replace("_", "/"),  # Manager expects 'tcp/udp'
            "protocol_match_excepted": False,
            "enabled": validated.enabled,
            "log": validated.log,
        }

        # Handle optional source IP
        if validated.src_ip:
            rule_data["src"] = validated.src_ip

        logger.info(
            "Attempting to create port forward: %s (%s %s -> %s:%s)",
            validated.name,
            rule_data["proto"],
            validated.dst_port,
            validated.fwd_ip,
            validated.fwd_port,
        )

        result = await firewall_manager.create_port_forward(rule_data)

        if result:
            new_rule_id = result if isinstance(result, str) else result.get("_id", "unknown")
            details = result if isinstance(result, dict) else {"id": new_rule_id}
            logger.info("Successfully created port forward '%s' with ID %s", validated.name, new_rule_id)
            return {
                "success": True,
                "message": f"Port forward '{validated.name}' created successfully.",
                "port_forward_id": new_rule_id,
                "details": json.loads(json.dumps(details, default=str)),
            }
        else:
            fail_msg = (
                result.get("error", "Manager returned failure")
                if isinstance(result, dict)
                else "Manager returned failure"
            )
            logger.error("Failed to create port forward '%s'. Reason: %s", validated.name, fail_msg)
            return {
                "success": False,
                "error": f"Failed to create port forward '{validated.name}'. {fail_msg}",
            }

    except Exception as e:
        logger.error(
            "Error creating port forward '%s': %s",
            port_forward_data.get("name", "unknown"),
            e,
            exc_info=True,
        )
        return {"success": False, "error": str(e)}


# --- NEW UPDATE TOOL ---
@server.tool(
    name="unifi_update_port_forward",
    description="Update specific fields of an existing port forwarding rule using schema validation. Requires confirmation.",
    permission_category="port_forwards",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_port_forward(
    port_forward_id: Annotated[
        str,
        Field(
            description="Unique identifier (_id) of the port forwarding rule to update (from unifi_list_port_forwards)"
        ),
    ],
    update_data: Annotated[
        Dict[str, Any],
        Field(
            description="Dictionary of fields to update. Allowed keys: name, dst_port (external port), fwd_port (internal port), fwd_ip (internal IP), protocol ('tcp'/'udp'/'tcp_udp'), enabled (bool), src_ip (source IP/CIDR, empty string to remove), log (bool)"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the update. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Updates specific fields of an existing port forwarding rule.

    This tool allows modifying one or more properties of a port forward rule
    identified by its ID. All fields in `update_data` are optional; only provided
    fields will be updated. Requires confirmation.

    Args:
        port_forward_id (str): The unique identifier (_id) of the port forwarding rule to update.
        update_data (Dict[str, Any]): A dictionary containing the fields to update.
            Allowed fields (all optional):
            - name (string): New name for the rule.
            - dst_port (string): New destination/external port or range.
            - fwd_port (string): New internal port or range.
            - fwd_ip (string): New internal IP address.
            - protocol (string): New protocol ("tcp", "udp", or "tcp_udp").
            - enabled (boolean): New enabled state (True/False).
            - src_ip (string): New source IP/CIDR match (use empty string "" or null to remove).
            - log (boolean): New logging state (True/False).
        confirm (bool): Must be explicitly set to `True` to execute the update. Defaults to `False`.

    Returns:
        A dictionary containing:
        - success (bool): Indicates if the operation was successful.
        - port_forward_id (str): The ID of the rule that was updated.
        - updated_fields (List[str]): A list of field names that were successfully updated.
        - details (Dict[str, Any]): The full details of the rule after the update.
        - error (str, optional): An error message if the operation failed.

    Example call:
    update_port_forward(
        port_forward_id="60f5a9b3e4b0f4a7f7d6e8c1",
        update_data={
            "name": "Updated Web Server Name",
            "enabled": False,
            "dst_port": "443"
        },
        confirm=True
    )

    Example response (success):
    {
        "success": True,
        "port_forward_id": "60f5a9b3e4b0f4a7f7d6e8c1",
        "updated_fields": ["name", "enabled", "dst_port"],
        "details": { ... updated rule details ... }
    }
    """
    if not port_forward_id:
        return {"success": False, "error": "port_forward_id is required"}
    if not update_data:
        return {"success": False, "error": "update_data dictionary cannot be empty"}

    # Validate the update data against the update schema
    try:
        validated_obj = PortForwardUpdateInput(**update_data)
    except ValidationError as exc:
        err = exc.errors()[0]["msg"]
        logger.warning("Invalid port forward update data for ID %s: %s", port_forward_id, err)
        return {"success": False, "error": f"Invalid update data: {err}"}

    # Build validated_data dict from the model (exclude unset/None values)
    validated_data = validated_obj.model_dump(exclude_none=True)

    if not validated_data:
        logger.warning("Port forward update data for ID %s is empty after validation.", port_forward_id)
        return {
            "success": False,
            "error": "Update data is effectively empty or invalid.",
        }

    # Prepare the payload for the manager update function
    update_payload = {}
    updated_fields_list = []
    for key, value in validated_data.items():
        updated_fields_list.append(key)
        if key == "protocol":
            update_payload["proto"] = value.replace("_", "/")
        elif key == "src_ip":
            update_payload["src"] = value if value else None
        elif key == "log":
            update_payload["log"] = value
        else:
            update_payload[key] = value

    if not confirm:
        return update_preview(
            resource_type="port_forward",
            resource_id=port_forward_id,
            resource_name=port_forward_id,
            current_state={},
            updates=validated_data,
        )

    try:
        success = await firewall_manager.update_port_forward(port_forward_id, update_payload)
        if success:
            return {
                "success": True,
                "port_forward_id": port_forward_id,
                "updated_fields": updated_fields_list,
            }
        return {
            "success": False,
            "port_forward_id": port_forward_id,
            "error": f"Failed to update port forward '{port_forward_id}'. Check server logs.",
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating port forward %s: %s", port_forward_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update port forward {port_forward_id}: {e}"}


@server.tool(
    name="unifi_create_simple_port_forward",
    description=("Create a port forward using a simplified schema. Returns a preview unless confirm=true."),
    permission_category="port_forwards",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_simple_port_forward(
    rule: Annotated[
        Dict[str, Any],
        Field(
            description="Simplified port forward dict. Required: name (str), ext_port (external port, e.g. '8443'), to_ip (internal IP, e.g. '192.168.1.10'). Optional: int_port (internal port, defaults to ext_port), protocol ('tcp'/'udp'/'both', default 'both'), enabled (bool, default true)"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, creates the rule. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Create port forward with compact input.

    Schema (validated internally):
    {
        "name": "Home Web",
        "ext_port": "8443",
        "to_ip": "192.168.1.10",
        "int_port": "443",          # optional (defaults to ext_port)
        "protocol": "tcp",          # optional (default both)
        "enabled": true              # optional (default true)
    }
    """

    try:
        r = PortForwardSimpleInput(**rule)
    except ValidationError as exc:
        return {"success": False, "error": exc.errors()[0]["msg"]}

    # Build API payload matching existing V1 schema keys
    payload: Dict[str, Any] = {
        "name": r.name,
        "dst_port": str(r.ext_port),
        "fwd_port": str(r.int_port if r.int_port is not None else r.ext_port),
        "fwd_ip": r.to_ip,
        "protocol": {
            "tcp": "tcp",
            "udp": "udp",
            "both": "tcp_udp",
        }.get(r.protocol, "tcp_udp"),
        "enabled": r.enabled,
    }

    if not confirm:
        return {
            "success": True,
            "preview": payload,
            "message": "Set confirm=true to apply.",
        }

    try:
        created = await firewall_manager.create_port_forward(payload)
    except Exception as exc:
        logger.error("Error creating simple port forward: %s", exc, exc_info=True)
        return {"success": False, "error": f"Failed to create port forward: {exc}"}

    if created is None or not isinstance(created, dict):
        return {
            "success": False,
            "error": "Controller rejected port forward creation. See logs.",
        }

    return {
        "success": True,
        "port_forward_id": created.get("_id"),
        "details": json.loads(json.dumps(created, default=str)),
    }
