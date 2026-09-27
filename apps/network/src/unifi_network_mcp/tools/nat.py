"""V2 NAT rule reads and verified IPv4 mutations."""

import logging
from typing import Annotated, Any, Dict

from aiounifi.errors import Forbidden, LoginRequired, NoPermission, TwoFaTokenRequired, Unauthorized
from mcp.types import ToolAnnotations
from pydantic import Field, WithJsonSchema

from unifi_core.confirmation import create_preview, delete_preview, preview_response
from unifi_core.exceptions import UniFiNotFoundError, UniFiOperationError
from unifi_core.network.models.nat import (
    NatCreateToolInput,
    NatUpdateToolInput,
    from_controller,
    nat_write_input_schema,
    normalize_nat_verified_write,
)
from unifi_core.redaction import redact_sensitive_fields
from unifi_core.write_verification import WriteVerificationResult
from unifi_network_mcp.runtime import nat_manager, server, should_redact_sensitive_fields

logger = logging.getLogger(__name__)
_SAFE_READ_ERRORS = (UniFiOperationError, LoginRequired, Forbidden, NoPermission, TwoFaTokenRequired, Unauthorized)
_ID = Annotated[str, Field(description="V2 NAT rule ID from unifi_list_nat_rules; scoped to this NAT family")]
_WRITE = Annotated[dict[str, Any], WithJsonSchema(nat_write_input_schema())]


def _project(value: Any) -> Any:
    return redact_sensitive_fields(value, redact_sensitive=should_redact_sensitive_fields())


def _result(result: WriteVerificationResult) -> Dict[str, Any]:
    payload = result.to_dict()
    if result.resource is not None:
        payload["details_after_attempt"] = from_controller(result.resource).model_dump()
    return _project(payload)


def _error(operation: str, error: Exception) -> Dict[str, Any]:
    logger.error("Failed to %s NAT rule: %s", operation, type(error).__name__)
    if isinstance(error, (ValueError, UniFiNotFoundError)):
        return {"success": False, "error": f"Failed to {operation} NAT rule: {error}"}
    return {
        "success": False,
        "error": f"Failed to {operation} NAT rule ({type(error).__name__}). Check Network session access and permissions.",
    }


@server.tool(
    name="unifi_list_nat_rules",
    description=(
        "List NAT rules from the V2 controller API. Requires Network session credentials. "
        "These IDs are scoped to the V2 NAT tool family — do not pass them to port-forward or Integration API tools."
    ),
    permission_category="nat",
    auth="local_only",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_nat_rules() -> Dict[str, Any]:
    """Return all NAT rules with explicit nulls for unknown fields."""
    try:
        rules = await nat_manager.list_nat_rules()
        data = [from_controller(rule).model_dump() for rule in rules]
        return {
            "success": True,
            "data": redact_sensitive_fields(data, redact_sensitive=should_redact_sensitive_fields()),
        }
    except Exception as exc:
        logger.error("Failed to list NAT rules: %s", type(exc).__name__)
        if isinstance(exc, _SAFE_READ_ERRORS):
            return {"success": False, "error": f"Failed to list NAT rules: {exc}"}
        return {"success": False, "error": f"Failed to list NAT rules ({type(exc).__name__})."}


@server.tool(
    name="unifi_get_nat_rule",
    description=(
        "Get a NAT rule from the V2 controller API. Requires Network session credentials. "
        "These IDs are scoped to the V2 NAT tool family — do not pass them to port-forward or Integration API tools."
    ),
    permission_category="nat",
    auth="local_only",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_nat_rule(
    rule_id: Annotated[
        str,
        Field(description="V2 NAT rule ID returned by unifi_list_nat_rules; not a port-forward or Integration API ID"),
    ],
) -> Dict[str, Any]:
    """Look up one NAT rule by its V2 controller ID."""
    if not isinstance(rule_id, str) or not rule_id.strip():
        return {"success": False, "error": "Failed to get NAT rule: rule_id is required."}
    try:
        rule = await nat_manager.get_nat_rule(rule_id)
        data = from_controller(rule).model_dump()
        return {
            "success": True,
            "data": redact_sensitive_fields(data, redact_sensitive=should_redact_sensitive_fields()),
        }
    except UniFiNotFoundError:
        return {"success": False, "error": "Failed to get NAT rule: rule not found."}
    except Exception as exc:
        logger.error("Failed to get NAT rule: %s", type(exc).__name__)
        if isinstance(exc, _SAFE_READ_ERRORS):
            return {"success": False, "error": f"Failed to get NAT rule: {exc}"}
        return {"success": False, "error": f"Failed to get NAT rule ({type(exc).__name__})."}


@server.tool(
    name="unifi_create_nat_rule",
    input_schema=nat_write_input_schema(NatCreateToolInput),
    description=(
        "Create an IPv4 V2 NAT rule (DNAT, SNAT or MASQUERADE) with verified readback; disabled by default. "
        "Requires Network session credentials. The assigned rule_index is chosen again at confirmation. "
        "These IDs are scoped to the V2 NAT tool family — do not pass them to port-forward or Integration API tools."
    ),
    permission_category="nat",
    permission_action="create",
    auth="local_only",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_nat_rule(rule_data: _WRITE, confirm: bool = False) -> Dict[str, Any]:
    try:
        payload = normalize_nat_verified_write(rule_data, create=True)
        if not confirm:
            return _project(create_preview(resource_type="nat_rule", resource_data=payload))
        return _result(await nat_manager.create_nat_rule_verified(rule_data))
    except Exception as exc:
        return _error("create", exc)


@server.tool(
    name="unifi_update_nat_rule",
    input_schema=nat_write_input_schema(NatUpdateToolInput),
    description=(
        "Update a manual V2 NAT rule with verified fresh readback. Pass only the fields you want to change — "
        "current values are automatically preserved. A full fetch-merge-put can overwrite a concurrent edit "
        "between fetch and PUT. Requires Network session credentials. These IDs are scoped to the V2 NAT "
        "tool family — do not pass them to port-forward or Integration API tools."
    ),
    permission_category="nat",
    permission_action="update",
    auth="local_only",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_nat_rule(rule_id: _ID, update_data: _WRITE, confirm: bool = False) -> Dict[str, Any]:
    try:
        if not confirm:
            current, merged = await nat_manager.preview_nat_update(rule_id, update_data)
            return _project(
                preview_response(
                    "update",
                    "nat_rule",
                    rule_id,
                    from_controller(current).model_dump(),
                    from_controller(merged).model_dump(),
                )
            )
        return _result(await nat_manager.update_nat_rule_verified(rule_id, update_data))
    except Exception as exc:
        return _error("update", exc)


@server.tool(
    name="unifi_delete_nat_rule",
    description=(
        "Delete a manual V2 NAT rule and verify its absence. Requires Network session credentials. "
        "These IDs are scoped to the V2 NAT tool family — do not pass them to port-forward or Integration API tools."
    ),
    permission_category="nat",
    permission_action="delete",
    auth="local_only",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False),
)
async def delete_nat_rule(rule_id: _ID, confirm: bool = False) -> Dict[str, Any]:
    try:
        if not confirm:
            current, _ = await nat_manager.preview_nat_update(rule_id, {})
            return _project(delete_preview("nat_rule", rule_id, resource_data=from_controller(current).model_dump()))
        return _result(await nat_manager.delete_nat_rule_verified(rule_id))
    except Exception as exc:
        return _error("delete", exc)


@server.tool(
    name="unifi_toggle_nat_rule",
    description=(
        "Set a manual V2 NAT rule's enabled state explicitly; setting its current state is a no-op. "
        "Pass only the fields you want to change — current values are automatically preserved. "
        "A full fetch-merge-put can overwrite a concurrent edit between fetch and PUT. Requires Network "
        "session credentials. These IDs are scoped to the V2 NAT tool family — do not pass them to "
        "port-forward or Integration API tools."
    ),
    permission_category="nat",
    permission_action="update",
    auth="local_only",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def toggle_nat_rule(rule_id: _ID, enabled: bool, confirm: bool = False) -> Dict[str, Any]:
    try:
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean.")
        if not confirm:
            current, merged = await nat_manager.preview_nat_update(rule_id, {"enabled": enabled})
            return _project(
                preview_response(
                    "update",
                    "nat_rule",
                    rule_id,
                    from_controller(current).model_dump(),
                    from_controller(merged).model_dump(),
                )
            )
        return _result(await nat_manager.toggle_nat_rule_verified(rule_id, enabled))
    except Exception as exc:
        return _error("toggle", exc)
