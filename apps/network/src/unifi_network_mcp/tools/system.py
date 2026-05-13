"""
Unifi Network MCP system tools.

This module provides MCP tools to interact with a Unifi Network Controller's system functions.
"""

import logging
from typing import Annotated, Any, Dict, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.confirmation import create_preview, update_preview
from unifi_core.network.models.system import (
    autobackup_to_controller_update,
    backup_from_controller,
    network_health_from_controller,
    site_settings_from_controller,
    snmp_from_controller,
    snmp_to_controller_update,
    system_info_from_controller,
)
from unifi_network_mcp.runtime import server, system_manager

logger = logging.getLogger(__name__)

# Explicitly retrieve and log the server instance to confirm it's being used
logger.info("System tools module loaded, server instance: %s", server)


@server.tool(
    name="unifi_get_system_info",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    description=(
        "Returns controller version, uptime, hostname, memory/CPU usage, and update availability. "
        "Use for basic 'is the controller healthy?' checks. "
        "For network subsystem status (WAN/LAN/WLAN), use unifi_get_network_health instead. "
        "For network subsystem details, use unifi_get_network_health."
    ),
)
async def get_system_info() -> Dict[str, Any]:
    """Implementation for getting system info."""
    logger.info("unifi_get_system_info tool called")
    try:
        info = await system_manager.get_system_info()
        shaped = system_info_from_controller(info).model_dump(exclude_none=False)
        return {
            "success": True,
            "site": system_manager._connection.site,
            "system_info": shaped,
        }
    except Exception as e:
        logger.error("Error getting system info: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get system info: {e}"}


@server.tool(
    name="unifi_get_network_health",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    description=(
        "Returns per-subsystem health status for WAN, LAN, WLAN, and VPN — each with "
        "status, number of gateways/switches/APs, and active user counts. "
        "Use to check WAN connectivity, see how many devices are online per subsystem, "
        "or detect degraded network segments. "
        "For controller-level info (version, uptime), use unifi_get_system_info."
    ),
)
async def get_network_health() -> Dict[str, Any]:
    """Implementation for getting network health.

    Returns a dict with ``health_summary`` containing a list of per-subsystem dicts.
    """
    logger.info("unifi_get_network_health tool called")
    try:
        health = await system_manager.get_network_health()
        subsystems = health if isinstance(health, list) else [health]
        shaped = [network_health_from_controller(s).model_dump(exclude_none=False) for s in subsystems]
        return {
            "success": True,
            "site": system_manager._connection.site,
            "health_summary": shaped,
        }
    except Exception as e:
        logger.error("Error getting network health: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get network health: {e}"}


@server.tool(
    name="unifi_get_site_settings",
    description="Get current site settings (e.g., country code, timezone, connectivity monitoring).",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_site_settings() -> Dict[str, Any]:
    """Implementation for getting site settings."""
    logger.info("unifi_get_site_settings tool called")
    try:
        settings = await system_manager.get_site_settings()
        shaped = site_settings_from_controller(settings).model_dump(exclude_none=False)
        return {
            "success": True,
            "site": system_manager._connection.site,
            "site_settings": shaped,
        }
    except Exception as e:
        logger.error("Error getting site settings: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get site settings: {e}"}


@server.tool(
    name="unifi_get_snmp_settings",
    description="Get current SNMP settings for the site (enabled state, community string).",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_snmp_settings() -> Dict[str, Any]:
    """Implementation for getting SNMP settings."""
    logger.info("unifi_get_snmp_settings tool called")
    try:
        settings_list = await system_manager.get_settings("snmp")
        shaped = snmp_from_controller(settings_list).model_dump(exclude_none=False)
        return {
            "success": True,
            "site": system_manager._connection.site,
            "snmp_settings": shaped,
        }
    except Exception as e:
        logger.error("Error getting SNMP settings: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get SNMP settings: {e}"}


@server.tool(
    name="unifi_update_snmp_settings",
    description="Update SNMP settings for the site (enable/disable, set community string). Requires confirm=true to apply changes.",
    permission_category="snmp",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_snmp_settings(
    enabled: Annotated[bool, Field(description="Set to true to enable SNMP on the site, false to disable it")],
    community: Annotated[
        Optional[str],
        Field(description="SNMP community string (e.g., 'public'). Omit to keep the current value"),
    ] = None,
    confirm: Annotated[
        bool,
        Field(description="When true, applies the changes. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Implementation for updating SNMP settings.

    Args:
        enabled: Whether SNMP should be enabled on the site.
        community: SNMP community string (optional, keeps current value if not provided).
        confirm: Must be true to apply changes. When false, returns a preview of proposed changes.
    """
    logger.info("unifi_update_snmp_settings tool called (enabled=%s, confirm=%s)", enabled, confirm)

    updates: Dict[str, Any] = {"enabled": enabled}
    if community is not None:
        updates["community"] = community

    validated_data = snmp_to_controller_update(updates)
    if not validated_data:
        return {"success": False, "error": "No valid fields to update after validation."}

    if not confirm:
        return update_preview(
            resource_type="snmp_settings",
            resource_id="snmp",
            resource_name="SNMP Settings",
            current_state={},
            updates=validated_data,
        )

    try:
        success = await system_manager.update_settings("snmp", validated_data)
        if success:
            return {
                "success": True,
                "site": system_manager._connection.site,
                "snmp_settings": {
                    "enabled": validated_data.get("enabled", enabled),
                    "community": validated_data.get("community", community or ""),
                },
            }
        return {"success": False, "error": "Failed to update SNMP settings."}
    except Exception as e:
        logger.error("Error updating SNMP settings: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to update SNMP settings: {e}"}


# ---- Backup Management ----


@server.tool(
    name="unifi_list_backups",
    description="List available backups on the controller. Returns filename, datetime, size, and version for each backup.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_backups() -> Dict[str, Any]:
    """List available backups."""
    logger.info("unifi_list_backups tool called")
    try:
        backups = await system_manager.list_backups()
        shaped = [backup_from_controller(b).model_dump(exclude_none=False) for b in backups]
        return {
            "success": True,
            "site": system_manager._connection.site,
            "count": len(shaped),
            "backups": shaped,
        }
    except Exception as e:
        logger.error("Error listing backups: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list backups: {e}"}


@server.tool(
    name="unifi_create_backup",
    description="Create a new backup of the controller configuration. "
    "Returns the backup metadata on success. Requires confirmation.",
    permission_category="system",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_backup(
    confirm: Annotated[
        bool,
        Field(description="When true, creates the backup. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Create a controller backup."""
    logger.info("unifi_create_backup tool called (confirm=%s)", confirm)
    if not confirm:
        return create_preview(
            resource_type="backup",
            resource_data={"action": "create_backup"},
            resource_name="controller_backup",
        )

    try:
        result = await system_manager.create_backup()
        if result is not None:
            return {
                "success": True,
                "message": "Backup created successfully.",
                "details": result,
            }
        return {"success": False, "error": "Failed to create backup."}
    except Exception as e:
        logger.error("Error creating backup: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to create backup: {e}"}


@server.tool(
    name="unifi_delete_backup",
    description="Delete a backup file from the controller. Use unifi_list_backups to find filenames. "
    "Requires confirmation.",
    permission_category="system",
    permission_action="delete",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def delete_backup(
    filename: Annotated[str, Field(description="Backup filename to delete (from unifi_list_backups)")],
    confirm: Annotated[
        bool,
        Field(description="When true, deletes the backup. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Delete a backup file."""
    logger.info("unifi_delete_backup tool called (filename=%s, confirm=%s)", filename, confirm)
    if not confirm:
        return create_preview(
            resource_type="backup",
            resource_data={"filename": filename},
            resource_name=filename,
            warnings=["This will permanently delete the backup file."],
        )

    try:
        success = await system_manager.delete_backup(filename)
        if success:
            return {"success": True, "message": f"Backup '{filename}' deleted successfully."}
        return {"success": False, "error": f"Failed to delete backup '{filename}'."}
    except Exception as e:
        logger.error("Error deleting backup '%s': %s", filename, e, exc_info=True)
        return {"success": False, "error": f"Failed to delete backup '{filename}': {e}"}


@server.tool(
    name="unifi_get_autobackup_settings",
    description="Get auto-backup settings (enabled state, schedule, retention count, cloud backup).",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_autobackup_settings() -> Dict[str, Any]:
    """Get auto-backup configuration."""
    logger.info("unifi_get_autobackup_settings tool called")
    try:
        settings = await system_manager.get_autobackup_settings()
        return {
            "success": True,
            "site": system_manager._connection.site,
            "autobackup_settings": settings,
        }
    except Exception as e:
        logger.error("Error getting auto-backup settings: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get auto-backup settings: {e}"}


@server.tool(
    name="unifi_update_autobackup_settings",
    description="Update auto-backup settings. Pass only the fields you want to change — "
    "current values are automatically preserved. "
    "Fields: autobackup_enabled (bool), autobackup_cron_expr (str, cron format), "
    "autobackup_days (int, retention days), autobackup_max_files (int, max backup files to keep), "
    "autobackup_timezone (str), autobackup_cloud_enabled (bool). "
    "Requires confirmation.",
    permission_category="system",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_autobackup_settings(
    update_data: Annotated[
        Dict[str, Any],
        Field(description="Dictionary of auto-backup fields to update. See tool description for supported fields."),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the update. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Update auto-backup settings."""
    logger.info("unifi_update_autobackup_settings tool called (confirm=%s)", confirm)
    if not update_data:
        return {"success": False, "error": "No settings provided to update."}

    validated_data = autobackup_to_controller_update(update_data)
    if not validated_data:
        return {"success": False, "error": "No valid fields to update after validation."}

    if not confirm:
        return update_preview(
            resource_type="autobackup_settings",
            resource_id="super_mgmt",
            resource_name="Auto-Backup Settings",
            current_state={},
            updates=validated_data,
        )

    try:
        success = await system_manager.update_autobackup_settings(validated_data)
        if success:
            return {
                "success": True,
                "message": "Auto-backup settings updated successfully.",
                "autobackup_settings": validated_data,
            }
        return {"success": False, "error": "Failed to update auto-backup settings."}
    except Exception as e:
        logger.error("Error updating auto-backup settings: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to update auto-backup settings: {e}"}
