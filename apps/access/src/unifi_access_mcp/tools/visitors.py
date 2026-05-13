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
    from_controller as visitor_from_controller,
    to_controller_create as visitor_to_controller_create,
)
from unifi_core.confirmation import create_preview, preview_response
from unifi_core.exceptions import UniFiNotFoundError

logger = logging.getLogger(__name__)


@server.tool(
    name="access_list_visitors",
    description=("Lists all visitor passes with their name, status, valid time range, and assigned doors."),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="visitor",
    permission_action="read",
    auth="local_only",
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
        "Returns detailed information for a single visitor pass including "
        "name, access time range, assigned doors, and status."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="visitor",
    permission_action="read",
    auth="local_only",
)
async def access_get_visitor(
    visitor_id: Annotated[str, Field(description="Visitor UUID (from access_list_visitors)")],
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
        "Create a new visitor pass with a name and access time range. "
        "Optionally assign specific doors and contact information. "
        "Requires confirm=true to execute. Only available via local proxy session."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False),
    permission_category="visitor",
    permission_action="create",
    auth="local_only",
)
async def access_create_visitor(
    name: Annotated[str, Field(description="Visitor display name")],
    access_start: Annotated[
        str,
        Field(description="Start of access period as ISO 8601 timestamp (e.g., 2026-03-17T09:00:00Z)"),
    ],
    access_end: Annotated[
        str,
        Field(description="End of access period as ISO 8601 timestamp (e.g., 2026-03-17T17:00:00Z)"),
    ],
    email: Annotated[
        str | None,
        Field(description="Visitor email address for notifications. Optional."),
    ] = None,
    phone: Annotated[
        str | None,
        Field(description="Visitor phone number. Optional."),
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
            model = Visitor(
                name=name,
                valid_from=access_start,
                valid_until=access_end,
                email=email,
                phone=phone,
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
        "Delete a visitor pass. This permanently removes the visitor's access. "
        "Requires confirm=true to execute. Only available via local proxy session."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False),
    permission_category="visitor",
    permission_action="delete",
    auth="local_only",
)
async def access_delete_visitor(
    visitor_id: Annotated[str, Field(description="Visitor UUID (from access_list_visitors)")],
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
        return preview_response(
            action="delete",
            resource_type="visitor_pass",
            resource_id=visitor_id,
            current_state=preview_data["current_state"],
            proposed_changes=preview_data["proposed_changes"],
            resource_name=preview_data.get("visitor_name"),
            warnings=["This will permanently remove the visitor pass and revoke all associated access."],
        )
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error deleting visitor %s: %s", visitor_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to delete visitor: {e}"}


logger.info(
    "Visitor tools registered: access_list_visitors, access_get_visitor, access_create_visitor, access_delete_visitor"
)
