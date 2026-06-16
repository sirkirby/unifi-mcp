"""Confirmation and preview utilities for mutating operations.

This module provides helpers for the preview-then-confirm pattern used by
mutating tools. When confirm=false, tools should return a preview of what
will happen, giving LLM agents context to make informed decisions.

Preview responses return success=True because a preview is itself a
successful operation that requires further confirmation to execute.

Permission mode (confirm vs bypass) is controlled via:
    UNIFI_TOOL_PERMISSION_MODE=confirm|bypass
    UNIFI_<SERVER>_TOOL_PERMISSION_MODE=confirm|bypass
See policy_gate.resolve_permission_mode() for details.
"""

from typing import Any, Dict, List, Optional


def preview_response(
    action: str,
    resource_type: str,
    resource_id: str,
    current_state: Dict[str, Any],
    proposed_changes: Dict[str, Any],
    resource_name: Optional[str] = None,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build a standardized preview response for confirm=false.

    Preview responses use success=True because the preview itself is a
    successful operation. The requires_confirmation flag signals that
    the mutation has not yet been executed.

    Args:
        action: The action being performed (e.g., "toggle", "update", "create", "delete")
        resource_type: Type of resource (e.g., "port_forward", "firewall_rule")
        resource_id: Unique identifier of the resource
        current_state: Current state of relevant fields
        proposed_changes: What will change if confirmed
        resource_name: Human-readable name of the resource (optional)
        warnings: List of warning messages (optional)

    Returns:
        Standardized preview response dict
    """
    response: Dict[str, Any] = {
        "success": True,
        "requires_confirmation": True,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "preview": {
            "current": current_state,
            "proposed": proposed_changes,
        },
        "message": "Review the changes above. Set confirm=true to execute.",
    }

    if resource_name:
        response["resource_name"] = resource_name

    if warnings:
        response["warnings"] = warnings

    return response


def toggle_preview(
    resource_type: str,
    resource_id: str,
    resource_name: Optional[str],
    current_enabled: bool,
    additional_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Convenience helper for toggle operations.

    Args:
        resource_type: Type of resource being toggled
        resource_id: Unique identifier
        resource_name: Human-readable name
        current_enabled: Current enabled state
        additional_info: Extra fields to include in current state

    Returns:
        Preview response for toggle operation
    """
    current_state = {"enabled": current_enabled}
    if additional_info:
        current_state.update(additional_info)

    proposed = {"enabled": not current_enabled}
    new_state = "disabled" if current_enabled else "enabled"

    response = preview_response(
        action="toggle",
        resource_type=resource_type,
        resource_id=resource_id,
        resource_name=resource_name,
        current_state=current_state,
        proposed_changes=proposed,
    )

    # Make the message more descriptive for toggles
    name_str = f"'{resource_name}'" if resource_name else resource_id
    response["message"] = f"Will {new_state} {resource_type} {name_str}. Set confirm=true to execute."

    return response


def update_preview(
    resource_type: str,
    resource_id: str,
    resource_name: Optional[str],
    current_state: Dict[str, Any],
    updates: Dict[str, Any],
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Convenience helper for update operations.

    Args:
        resource_type: Type of resource being updated
        resource_id: Unique identifier
        resource_name: Human-readable name
        current_state: Current values of fields being changed
        updates: New values being applied
        warnings: Optional warnings about the update (e.g. connectivity risk)

    Returns:
        Preview response for update operation
    """
    # Filter current_state to only show fields being changed
    relevant_current = {k: current_state.get(k) for k in updates.keys()}

    response = preview_response(
        action="update",
        resource_type=resource_type,
        resource_id=resource_id,
        resource_name=resource_name,
        current_state=relevant_current,
        proposed_changes=updates,
        warnings=warnings,
    )

    # Make the message more descriptive
    name_str = f"'{resource_name}'" if resource_name else resource_id
    fields = ", ".join(updates.keys())
    response["message"] = f"Will update {fields} on {resource_type} {name_str}. Set confirm=true to execute."

    return response


def create_preview(
    resource_type: str,
    resource_data: Dict[str, Any],
    resource_name: Optional[str] = None,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Convenience helper for create operations.

    Args:
        resource_type: Type of resource being created
        resource_data: The data that will be used to create the resource
        resource_name: Human-readable name if available
        warnings: Any warnings about the create operation

    Returns:
        Preview response for create operation
    """
    response: Dict[str, Any] = {
        "success": True,
        "requires_confirmation": True,
        "action": "create",
        "resource_type": resource_type,
        "preview": {
            "will_create": resource_data,
        },
        "message": f"Will create new {resource_type}. Set confirm=true to execute.",
    }

    if resource_name:
        response["resource_name"] = resource_name
        response["message"] = f"Will create {resource_type} '{resource_name}'. Set confirm=true to execute."

    if warnings:
        response["warnings"] = warnings

    return response
