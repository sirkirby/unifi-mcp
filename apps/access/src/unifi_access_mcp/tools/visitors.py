"""Visitor tools for UniFi Access MCP server.

Provides tools for listing, inspecting, creating, and deleting visitor passes.
"""

import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from unifi_access_mcp.runtime import server, visitor_manager
from unifi_core.access.models._actions import DeleteVisitorInput
from unifi_core.access.models.visitors import (
    Visitor,
)
from unifi_core.access.models.visitors import (
    from_controller as visitor_from_controller,
)
from unifi_core.access.models.visitors import (
    to_controller_create as visitor_to_controller_create,
)
from unifi_core.confirmation import create_preview, delete_preview
from unifi_core.exceptions import UniFiNotFoundError

logger = logging.getLogger(__name__)


@server.tool(
    name="access_list_visitors",
    description=(
        "List visitor passes from the UniFi Access Developer API. Returned UUIDs are scoped to the "
        "Access Developer API visitor tool family — pass them only to access_get_visitor and "
        "access_delete_visitor; do not pass them to other Access user or credential tools."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="visitor",
    permission_action="read",
    auth="api_key_only",
)
async def access_list_visitors() -> Dict[str, Any]:
    """List all visitors."""
    logger.info("access_list_visitors tool called")
    try:
        raw_visitors = await visitor_manager.list_visitors()
        visitors = [visitor_from_controller(v).model_dump(exclude_none=True) for v in raw_visitors]
        return {"success": True, "data": {"visitors": visitors, "count": len(visitors)}}
    except Exception as e:
        logger.error("Error listing visitors: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list visitors: {e}"}


@server.tool(
    name="access_get_visitor",
    description=(
        "Return one visitor pass from the UniFi Access Developer API. The visitor UUID must come "
        "from access_list_visitors and is scoped to this visitor tool family — do not pass IDs "
        "from other Access user or credential tools."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="visitor",
    permission_action="read",
    auth="api_key_only",
)
async def access_get_visitor(
    visitor_id: Annotated[
        str,
        Field(description="Access Developer API visitor UUID from access_list_visitors; visitor-family scoped"),
    ],
) -> Dict[str, Any]:
    """Get detailed visitor information by ID."""
    logger.info("access_get_visitor tool called for %s", visitor_id)
    try:
        raw = await visitor_manager.get_visitor(visitor_id)
        detail = visitor_from_controller(raw).model_dump(exclude_none=True)
        return {"success": True, "data": detail}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting visitor %s: %s", visitor_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get visitor: {e}"}


@server.tool(
    name="access_create_visitor",
    description=(
        "Create a visitor pass in the UniFi Access Developer API. The returned UUID is scoped to "
        "the Access Developer API visitor tool family — use it only with access_get_visitor and "
        "access_delete_visitor. Requires a UniFi Access API token and confirm=true to execute."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False),
    permission_category="visitor",
    permission_action="create",
    auth="api_key_only",
)
async def access_create_visitor(
    name: Annotated[str, Field(description="Visitor display name")],
    access_start: Annotated[
        str | None,
        Field(description="Backward-compatible alias for valid_from (ISO 8601 with timezone)."),
    ] = None,
    access_end: Annotated[
        str | None,
        Field(description="Backward-compatible alias for valid_until (ISO 8601 with timezone)."),
    ] = None,
    valid_from: Annotated[
        str | None,
        Field(description="Start of access period as ISO 8601 timestamp (e.g., 2026-03-17T09:00:00Z)."),
    ] = None,
    valid_until: Annotated[
        str | None,
        Field(description="End of access period as ISO 8601 timestamp (e.g., 2026-03-17T17:00:00Z)."),
    ] = None,
    first_name: Annotated[
        str | None,
        Field(description="Explicit first name. Provide together with last_name to override splitting name."),
    ] = None,
    last_name: Annotated[
        str | None,
        Field(description="Explicit last name. Provide together with first_name to override splitting name."),
    ] = None,
    email: Annotated[
        str | None,
        Field(description="Visitor email address for notifications. Optional."),
    ] = None,
    phone: Annotated[
        str | None,
        Field(description="Visitor mobile phone number. Optional."),
    ] = None,
    company: Annotated[
        str | None,
        Field(description="Visitor company. Optional."),
    ] = None,
    visit_reason: Annotated[
        str | None,
        Field(description="Reason for the visit. Optional."),
    ] = None,
    remarks: Annotated[
        str | None,
        Field(description="Operator notes about the visit. Optional."),
    ] = None,
    confirm: Annotated[
        bool,
        Field(description="When true, creates the visitor pass. When false (default), returns a preview."),
    ] = False,
) -> Dict[str, Any]:
    """Create a visitor pass with preview/confirm."""
    logger.info("access_create_visitor tool called (name=%s, confirm=%s)", name, confirm)
    try:
        try:
            if access_start and valid_from and access_start != valid_from:
                raise ValueError("access_start and valid_from must match when both are provided")
            if access_end and valid_until and access_end != valid_until:
                raise ValueError("access_end and valid_until must match when both are provided")
            resolved_start = valid_from or access_start
            resolved_end = valid_until or access_end
            if not resolved_start or not resolved_end:
                raise ValueError("valid_from and valid_until are required")
            model = Visitor(
                name=name,
                valid_from=resolved_start,
                valid_until=resolved_end,
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone=phone,
                company=company,
                visit_reason=visit_reason,
                remarks=remarks,
            )
        except Exception as e:
            return {"success": False, "error": f"Invalid visitor input: {e}"}

        payload = visitor_to_controller_create(model)

        if confirm:
            result = await visitor_manager.apply_create_visitor(**payload)
            return {"success": True, "data": result}

        preview_data = await visitor_manager.create_visitor(**payload)
        return create_preview(
            resource_type="visitor_pass",
            resource_data=preview_data["proposed_changes"],
            resource_name=name,
        )
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error creating visitor: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to create visitor: {e}"}


@server.tool(
    name="access_delete_visitor",
    description=(
        "Delete a visitor pass through the UniFi Access Developer API, revoking its access; the "
        "controller retains a cancelled historical record. The UUID must come from "
        "access_list_visitors and is scoped to this visitor tool family — do not pass IDs from "
        "other Access user or credential tools. Requires an Access API token and confirm=true."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False),
    permission_category="visitor",
    permission_action="delete",
    auth="api_key_only",
)
async def access_delete_visitor(
    visitor_id: Annotated[
        str,
        Field(description="Access Developer API visitor UUID from access_list_visitors; visitor-family scoped"),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, deletes the visitor pass. When false (default), returns a preview."),
    ] = False,
) -> Dict[str, Any]:
    """Delete a visitor pass with preview/confirm."""
    logger.info("access_delete_visitor tool called for %s (confirm=%s)", visitor_id, confirm)
    try:
        try:
            params = DeleteVisitorInput(visitor_id=visitor_id)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}
        visitor_id = params.visitor_id

        if confirm:
            result = await visitor_manager.apply_delete_visitor(visitor_id)
            return {"success": True, "data": result}

        preview_data = await visitor_manager.delete_visitor(visitor_id)
        return delete_preview(
            resource_type="visitor_pass",
            resource_id=visitor_id,
            resource_data=preview_data["current_state"],
            resource_name=preview_data.get("visitor_name"),
            warnings=[
                "This will revoke all associated access. The controller retains the visitor as cancelled history."
            ],
        )
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error deleting visitor %s: %s", visitor_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to delete visitor: {e}"}


logger.info(
    "Visitor tools registered: access_list_visitors, access_get_visitor, access_create_visitor, access_delete_visitor"
)
