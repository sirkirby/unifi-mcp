"""
UniFi Network MCP hotspot voucher tools.

This module provides MCP tools to manage hotspot vouchers on a UniFi Network Controller.
"""

import logging
from typing import Annotated, Any, Dict, Optional

from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from unifi_core.confirmation import create_preview, preview_response
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.models._actions import CreateVoucherInput, RevokeVoucherInput
from unifi_core.network.models.vouchers import voucher_from_controller
from unifi_core.network.read_views import VOUCHER_ALLOWED_FIELDS, shape_voucher_list
from unifi_core.redaction import redact_sensitive_fields
from unifi_network_mcp.runtime import hotspot_manager, server, should_redact_sensitive_fields

logger = logging.getLogger(__name__)


@server.tool(
    name="unifi_list_vouchers",
    description="""List hotspot vouchers for the current site.

Returns voucher codes, expiration times, usage quotas, and bandwidth limits.
Vouchers are used for guest network access in captive portal setups. Supports
optional limit, offset, case-insensitive search by code or note (including UI
hyphenated codes), and strict fields projection. Deterministic pagination sorts
by created_at descending with id descending tie-break for shaped calls;
unshaped calls preserve controller return order for backward compatibility.""",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_vouchers(
    limit: Annotated[
        Optional[int],
        Field(
            default=None,
            ge=1,
            le=1000,
            description="Optional maximum number of vouchers to return (1-1000). None preserves returning all vouchers.",
        ),
    ] = None,
    offset: Annotated[
        int,
        Field(
            default=0,
            ge=0,
            description="Zero-based offset into the vouchers collection (default 0).",
        ),
    ] = 0,
    search: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Optional case-insensitive substring search over voucher note and code (including UI hyphenated codes).",
        ),
    ] = None,
    fields: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Optional comma-separated list of fields to include in each voucher. "
                "Available fields: id, code, status, duration, qos_overwrite, created_at, "
                "used_at, quota, used, note, up_limit_kbps, down_limit_kbps, data_limit_mb."
            ),
        ),
    ] = None,
) -> Dict[str, Any]:
    """List hotspot vouchers with optional shaping."""
    if limit is not None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 1000:
            return {
                "success": False,
                "error": f"Invalid limit: {limit}. Must be an integer between 1 and 1000.",
            }

    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        return {
            "success": False,
            "error": f"Invalid offset: {offset}. Must be a non-negative integer.",
        }

    if fields is not None:
        if not isinstance(fields, str):
            return {
                "success": False,
                "error": f"Invalid fields parameter type: {type(fields).__name__}. Expected comma-separated string.",
            }
        field_items = [f.strip() for f in fields.split(",") if f.strip()]
        if field_items:
            unknown_fields = set(field_items) - VOUCHER_ALLOWED_FIELDS
            if unknown_fields:
                return {
                    "success": False,
                    "error": (
                        f"Unknown projection fields: {sorted(unknown_fields)}. "
                        f"Allowed fields: {sorted(VOUCHER_ALLOWED_FIELDS)}"
                    ),
                }

    try:
        vouchers = await hotspot_manager.get_vouchers()
        response = shape_voucher_list(
            vouchers,
            site=hotspot_manager._connection.site,
            search=search,
            limit=limit,
            offset=offset,
            fields=fields,
        )
        if not response.get("success", True):
            return response
        redact_sensitive = should_redact_sensitive_fields()
        return redact_sensitive_fields(response, redact_sensitive=redact_sensitive)
    except Exception as e:
        logger.error("Error listing vouchers: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list vouchers: {e}"}


@server.tool(
    name="unifi_get_voucher_details",
    description="Get detailed information about a specific voucher by its ID",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_voucher_details(
    voucher_id: Annotated[str, Field(description="Unique identifier (_id) of the voucher (from unifi_list_vouchers)")],
) -> Dict[str, Any]:
    """Get details for a specific voucher."""
    try:
        voucher = await hotspot_manager.get_voucher_details(voucher_id)
        shaped = voucher_from_controller(voucher)
        return {
            "success": True,
            "site": hotspot_manager._connection.site,
            "voucher": shaped.model_dump(exclude_none=True),
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting voucher details for %s: %s", voucher_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get voucher details for {voucher_id}: {e}"}


@server.tool(
    name="unifi_create_voucher",
    description="""Create hotspot voucher(s) for guest network access.

Vouchers can have:
- Time limits: How long the voucher is valid after activation
- Usage quota: Single-use (1), multi-use (0), or n-times usable
- Bandwidth limits: Upload/download speed caps in Kbps
- Data caps: Total data transfer limit in MB""",
    permission_category="vouchers",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_voucher(
    expire_minutes: Annotated[
        int,
        Field(description="Duration in minutes the voucher is valid after activation (default 1440 = 24 hours)"),
    ] = 1440,
    count: Annotated[int, Field(description="Number of vouchers to create in this batch (1-10000, default 1)")] = 1,
    quota: Annotated[
        int,
        Field(description="Usage limit per voucher: 1 = single-use (default), 0 = unlimited uses, N = N-times usable"),
    ] = 1,
    note: Annotated[
        Optional[str], Field(description="Optional note/label for the voucher batch (e.g., 'Conference guests')")
    ] = None,
    up_limit_kbps: Annotated[
        Optional[int], Field(description="Upload speed limit in Kbps (e.g., 5000 for 5 Mbps). Omit for unlimited")
    ] = None,
    down_limit_kbps: Annotated[
        Optional[int],
        Field(description="Download speed limit in Kbps (e.g., 10000 for 10 Mbps). Omit for unlimited"),
    ] = None,
    bytes_limit_mb: Annotated[
        Optional[int], Field(description="Total data transfer limit in MB. Omit for unlimited")
    ] = None,
    confirm: Annotated[
        bool,
        Field(description="When true, creates the voucher(s). When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Create one or more hotspot vouchers."""
    try:
        validated = CreateVoucherInput(
            expire_minutes=expire_minutes,
            count=count,
            quota=quota,
            note=note,
            up_limit_kbps=up_limit_kbps,
            down_limit_kbps=down_limit_kbps,
            bytes_limit_mb=bytes_limit_mb,
        )
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}
    expire_minutes = validated.expire_minutes
    count = validated.count

    if not confirm:
        resource_data = {
            "count": count,
            "expire_minutes": expire_minutes,
            "quota": quota,
        }
        if note:
            resource_data["note"] = note
        if up_limit_kbps:
            resource_data["up_limit_kbps"] = up_limit_kbps
        if down_limit_kbps:
            resource_data["down_limit_kbps"] = down_limit_kbps
        if bytes_limit_mb:
            resource_data["bytes_limit_mb"] = bytes_limit_mb

        return create_preview(
            resource_type="voucher",
            resource_data=resource_data,
            resource_name=f"{count} voucher(s)",
        )

    try:
        vouchers = await hotspot_manager.create_voucher(
            expire_minutes=expire_minutes,
            count=count,
            quota=quota,
            note=note,
            up_limit_kbps=up_limit_kbps,
            down_limit_kbps=down_limit_kbps,
            bytes_limit_mb=bytes_limit_mb,
        )

        if vouchers:
            return {
                "success": True,
                "message": f"Created {len(vouchers)} voucher(s).",
                "site": hotspot_manager._connection.site,
                "count": len(vouchers),
                "vouchers": vouchers,
            }
        return {"success": False, "error": "Failed to create vouchers."}
    except Exception as e:
        logger.error("Error creating vouchers: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to create vouchers: {e}"}


@server.tool(
    name="unifi_revoke_voucher",
    description="Revoke/delete a hotspot voucher by its ID, preventing further use",
    permission_category="vouchers",
    permission_action="delete",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def revoke_voucher(
    voucher_id: Annotated[
        str,
        Field(description="Unique identifier (_id) of the voucher to revoke (from unifi_list_vouchers)"),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, revokes the voucher. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Revoke a hotspot voucher."""
    try:
        RevokeVoucherInput(voucher_id=voucher_id)
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    if not confirm:
        return preview_response(
            action="revoke",
            resource_type="voucher",
            resource_id=voucher_id,
            resource_name=voucher_id,
            current_state={},
            proposed_changes={"status": "revoked"},
            warnings=["This voucher will no longer be usable"],
        )

    try:
        success = await hotspot_manager.revoke_voucher(voucher_id)

        if success:
            return {
                "success": True,
                "message": f"Voucher {voucher_id} revoked successfully.",
            }
        return {"success": False, "error": f"Failed to revoke voucher {voucher_id}."}
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error revoking voucher %s: %s", voucher_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to revoke voucher {voucher_id}: {e}"}
