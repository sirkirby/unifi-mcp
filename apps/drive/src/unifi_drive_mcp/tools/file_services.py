"""File service tools for the UniFi Drive MCP server: SMB, NFS, Time Machine and rsync."""

import logging
from typing import Annotated, Any, Dict, Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.confirmation import preview_response
from unifi_drive_mcp.runtime import file_service_manager, server, tool_failure, tool_success

logger = logging.getLogger(__name__)


@server.tool(
    name="drive_get_file_services",
    description=(
        "Returns whether SMB, NFS and Time Machine are enabled on the NAS, and the network interfaces "
        "(address, link speed) clients connect to."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="file_service",
    permission_action="read",
)
async def drive_get_file_services() -> Dict[str, Any]:
    """Get file service status."""
    try:
        services = await file_service_manager.get_file_services()
        return tool_success(services.model_dump(exclude_none=True))
    except Exception as exc:
        return tool_failure("get file services", exc)


@server.tool(
    name="drive_get_smb_advanced_settings",
    description=(
        "Returns whether SMB Trash for personal drives is on (files removed over SMB go to Trash instead of "
        "being deleted) and whether every personal drive could move to it."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="file_service",
    permission_action="read",
)
async def drive_get_smb_advanced_settings() -> Dict[str, Any]:
    """Get the SMB advanced settings."""
    try:
        settings = await file_service_manager.get_smb_advanced_settings()
        return tool_success(settings.model_dump(exclude_none=True))
    except Exception as exc:
        return tool_failure("get SMB advanced settings", exc)


@server.tool(
    name="drive_get_rsync_settings",
    description=(
        "Returns whether the rsync service is on, whether a dedicated rsync account is set and its username "
        "(never its password), and whether SSH, which rsync needs, is on."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="file_service",
    permission_action="read",
)
async def drive_get_rsync_settings() -> Dict[str, Any]:
    """Get the rsync service settings."""
    try:
        settings = await file_service_manager.get_rsync_settings()
        return tool_success(settings.model_dump(exclude_none=True))
    except Exception as exc:
        return tool_failure("get rsync settings", exc)


@server.tool(
    name="drive_set_file_service",
    description=(
        "Turns a file-sharing service on or off: smb, nfs or time_machine (Time Machine runs over SMB and "
        "needs SMB on). Turning a service off disconnects its clients. Turning NFS off keeps the NFS "
        "connection list, so it applies again when NFS is turned back on. "
        "Requires confirm=true to execute; without it, returns a preview."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    permission_category="file_service",
    permission_action="update",
)
async def drive_set_file_service(
    service: Annotated[Literal["smb", "nfs", "time_machine"], Field(description="smb, nfs or time_machine")],
    enabled: Annotated[bool, Field(description="true to turn the service on, false to turn it off")],
    confirm: Annotated[
        bool, Field(description="When true, applies the change. When false (default), returns a preview.")
    ] = False,
) -> Dict[str, Any]:
    """Enable or disable a file service, with preview/confirm."""
    try:
        if confirm:
            change, after = await file_service_manager.set_file_service(service, enabled)
            return tool_success({"service": service, "enabled": after, "changed": change.changes_anything})
        change = await file_service_manager.plan_set_file_service(service, enabled)
        if not change.changes_anything:
            return tool_success({"service": service, "enabled": enabled, "changed": False})
        return preview_response(
            action="update",
            resource_type="file_service",
            resource_id=service,
            current_state={"enabled": change.enabled_before},
            proposed_changes={"enabled": change.enabled_after},
            warnings=change.warnings or None,
        )
    except Exception as exc:
        return tool_failure("set file service", exc)
