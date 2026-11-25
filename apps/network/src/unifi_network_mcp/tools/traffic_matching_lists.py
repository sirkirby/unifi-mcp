"""Traffic matching list tools (Integration API).

Traffic matching lists are reusable IP/IPv4/port lists referenced by firewall
policy traffic filters through ``trafficMatchingListId``. Their IDs are
Integration API UUIDs and are NOT interchangeable with V1 firewall group IDs,
V2 firewall policy IDs or MAC ACL rule IDs.
"""

import logging
from typing import Annotated, Any, Dict, List, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.confirmation import create_preview, delete_preview
from unifi_core.exceptions import (
    UniFiAuthError,
    UniFiMalformedResponseError,
    UniFiOperationError,
    UniFiPermissionError,
)
from unifi_core.network.models.traffic_matching_lists import from_controller, to_controller_create
from unifi_core.redaction import redact_sensitive_fields
from unifi_network_mcp.runtime import server, should_redact_sensitive_fields, traffic_matching_list_manager

logger = logging.getLogger(__name__)

_ID_SCOPE = (
    "These IDs are Integration API UUIDs scoped to the traffic-matching-list tool "
    "family — do not pass them to firewall group, firewall policy or MAC ACL tools."
)

_INTEGRATION_ERRORS = (
    UniFiAuthError,
    UniFiPermissionError,
    UniFiOperationError,
    UniFiMalformedResponseError,
)


def _redact(value: Any) -> Any:
    return redact_sensitive_fields(value, redact_sensitive=should_redact_sensitive_fields())


def _failure(operation: str, exc: Exception, *, fixed_text: bool) -> Dict[str, Any]:
    """Log the operation and exception class only; typed errors keep their fixed text."""
    logger.error("Error %s: %s", operation, type(exc).__name__)
    detail = str(exc) if fixed_text else type(exc).__name__
    return {"success": False, "error": f"Failed to {operation}: {detail}"}


@server.tool(
    name="unifi_list_traffic_matching_lists",
    auth="api_key_only",
    description=(
        "List the site's reusable traffic matching lists (IP/IPv4/port lists referenced by "
        "firewall policy traffic filters) from the UniFi public Integration API, with pagination. "
        f"{_ID_SCOPE} "
        "Requires UNIFI_NETWORK_API_KEY (or UNIFI_API_KEY on the UNIFI_HOST console)."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
)
async def list_traffic_matching_lists(
    offset: Annotated[int, Field(description="Page offset (default 0)", ge=0)] = 0,
    limit: Annotated[int, Field(description="Page size (default 25)", ge=1, le=200)] = 25,
    filter_expr: Annotated[
        Optional[str],
        Field(description="Optional Integration API filter expression (e.g. name like 'Allowed')"),
    ] = None,
    site_id: Annotated[
        Optional[str],
        Field(description="Optional Integration API site UUID; resolved from the configured site when omitted"),
    ] = None,
) -> Dict[str, Any]:
    """List traffic matching lists on a site."""
    try:
        page = await traffic_matching_list_manager.list_traffic_matching_lists(
            offset=offset, limit=limit, filter_expr=filter_expr, site_id=site_id
        )
        lists = [_redact(from_controller(raw).model_dump()) for raw in page["data"]]
        return {
            "success": True,
            "count": page.get("count", len(lists)),
            "totalCount": page.get("totalCount", len(lists)),
            "offset": page.get("offset", offset),
            "limit": page.get("limit", limit),
            "lists": lists,
        }
    except _INTEGRATION_ERRORS as e:
        return _failure("list traffic matching lists", e, fixed_text=True)
    except Exception as e:
        return _failure("list traffic matching lists", e, fixed_text=False)


@server.tool(
    name="unifi_get_traffic_matching_list",
    auth="api_key_only",
    description=(
        "Read one traffic matching list by ID, including its entries, from the UniFi public "
        f"Integration API. {_ID_SCOPE} "
        "Requires UNIFI_NETWORK_API_KEY (or UNIFI_API_KEY on the UNIFI_HOST console)."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
)
async def get_traffic_matching_list(
    list_id: Annotated[
        str,
        Field(description="Integration API UUID of the traffic matching list (from unifi_list_traffic_matching_lists)"),
    ],
    site_id: Annotated[
        Optional[str],
        Field(description="Optional Integration API site UUID; resolved from the configured site when omitted"),
    ] = None,
) -> Dict[str, Any]:
    """Read one traffic matching list."""
    try:
        if not list_id:
            return {"success": False, "error": "list_id is required"}
        raw = await traffic_matching_list_manager.get_traffic_matching_list(list_id, site_id=site_id)
        return {"success": True, "list": _redact(from_controller(raw).model_dump())}
    except _INTEGRATION_ERRORS as e:
        return _failure(f"get traffic matching list {list_id}", e, fixed_text=True)
    except Exception as e:
        return _failure(f"get traffic matching list {list_id}", e, fixed_text=False)


@server.tool(
    name="unifi_create_traffic_matching_list",
    auth="api_key_only",
    description=(
        "Create a reusable traffic matching list (IP/IPv4/port entries referenced by firewall "
        f"policies) through the UniFi public Integration API. {_ID_SCOPE} "
        "The controller rejects unknown type/item shapes and reports the valid values in its "
        "error; observed on this API: list types PORTS, IPV4_ADDRESSES, IPV6_ADDRESSES, and port "
        "items {type: PORT_NUMBER|PORT_NUMBER_RANGE, value|range}. Send type and items as the "
        "controller requires — the model carries them opaquely so a future controller's values "
        "still pass through. Requires confirmation, UNIFI_NETWORK_API_KEY (or UNIFI_API_KEY on "
        "the UNIFI_HOST console)."
    ),
    permission_category="traffic_matching_lists",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_traffic_matching_list(
    name: Annotated[str, Field(description="List name (e.g. 'Allowed port list')")],
    type: Annotated[str, Field(description="List type as an opaque string (no enum is published)")],
    items: Annotated[
        Optional[List[Dict[str, Any]]],
        Field(
            description=(
                "Optional entry objects sent exactly as supplied (e.g. port entries). Omit to create an empty list."
            )
        ),
    ] = None,
    site_id: Annotated[
        Optional[str],
        Field(description="Optional Integration API site UUID; resolved from the configured site when omitted"),
    ] = None,
    confirm: Annotated[
        bool,
        Field(description="When true, creates the list. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Create a traffic matching list after previewing the payload."""
    try:
        if not name or not name.strip():
            return {"success": False, "error": "name is required"}
        if not type or not type.strip():
            return {"success": False, "error": "type is required"}
        payload = to_controller_create(name, type, items)

        if not confirm:
            return _redact(
                create_preview(
                    resource_type="traffic_matching_list",
                    resource_data=payload,
                    resource_name=name,
                )
            )

        raw = await traffic_matching_list_manager.create_traffic_matching_list(name, type, items=items, site_id=site_id)
        return {"success": True, "list": _redact(from_controller(raw).model_dump())}
    except ValueError as e:
        return {"success": False, "error": f"Failed to create traffic matching list: {e}"}
    except _INTEGRATION_ERRORS as e:
        return _failure("create traffic matching list", e, fixed_text=True)
    except Exception as e:
        return _failure("create traffic matching list", e, fixed_text=False)


@server.tool(
    name="unifi_delete_traffic_matching_list",
    auth="api_key_only",
    description=(
        "Delete a traffic matching list by ID. A list referenced by firewall policies may be "
        "refused by the controller; that error is surfaced, never swallowed. This cannot be "
        f"undone — recreate the list to restore it. {_ID_SCOPE} "
        "Requires confirmation, UNIFI_NETWORK_API_KEY (or UNIFI_API_KEY on the UNIFI_HOST console)."
    ),
    permission_category="traffic_matching_lists",
    permission_action="delete",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def delete_traffic_matching_list(
    list_id: Annotated[
        str,
        Field(description="Integration API UUID of the traffic matching list (from unifi_list_traffic_matching_lists)"),
    ],
    site_id: Annotated[
        Optional[str],
        Field(description="Optional Integration API site UUID; resolved from the configured site when omitted"),
    ] = None,
    confirm: Annotated[
        bool,
        Field(description="When true, deletes the list. When false (default), returns a live-state preview"),
    ] = False,
) -> Dict[str, Any]:
    """Delete a traffic matching list after previewing its live state."""
    try:
        if not list_id:
            return {"success": False, "error": "list_id is required"}

        if not confirm:
            raw = await traffic_matching_list_manager.get_traffic_matching_list(list_id, site_id=site_id)
            model = from_controller(raw)
            return delete_preview(
                resource_type="traffic_matching_list",
                resource_id=list_id,
                resource_data=_redact(model.model_dump()),
                resource_name=model.name or list_id,
            )

        await traffic_matching_list_manager.delete_traffic_matching_list(list_id, site_id=site_id)
        return {
            "success": True,
            "list_id": list_id,
            "message": f"Traffic matching list '{list_id}' deleted successfully.",
        }
    except _INTEGRATION_ERRORS as e:
        return _failure(f"delete traffic matching list {list_id}", e, fixed_text=True)
    except Exception as e:
        return _failure(f"delete traffic matching list {list_id}", e, fixed_text=False)
