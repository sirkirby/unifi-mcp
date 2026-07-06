"""Device tools for UniFi Access MCP server.

Provides tools for listing, inspecting, and rebooting Access hardware devices
(hubs, readers, relays, intercoms).
"""

import logging
from typing import Annotated, Any, Dict, Optional

from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from unifi_access_mcp.runtime import device_manager, server, should_redact_sensitive_fields
from unifi_core.access.models._actions import RebootDeviceInput
from unifi_core.access.models.device_configs import from_controller as device_config_from_controller
from unifi_core.access.models.device_configs import redact_config_entries
from unifi_core.access.models.devices import from_controller as access_device_from_controller
from unifi_core.confirmation import preview_response
from unifi_core.exceptions import UniFiNotFoundError

logger = logging.getLogger(__name__)


@server.tool(
    name="access_list_devices",
    description=(
        "Lists all Access hardware devices (hubs, readers, relays, intercoms) "
        "with their name, type, connection state, and firmware version."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="device",
    permission_action="read",
    auth="either",
)
async def access_list_devices(
    compact: Annotated[
        bool,
        Field(
            description=(
                "When true, strips configs, images, location/door/floor duplicates, extensions, "
                "update_manual, and capabilities fields (~87% smaller). Recommended for overviews and summaries."
            )
        ),
    ] = False,
) -> Dict[str, Any]:
    """List all Access devices."""
    logger.info("access_list_devices tool called (compact=%s)", compact)
    try:
        raw_devices = await device_manager.list_devices(compact=compact)
        devices = [access_device_from_controller(d).model_dump(exclude_none=True) for d in raw_devices]
        return {"success": True, "data": {"devices": devices, "count": len(devices)}}
    except Exception as e:
        logger.error("Error listing devices: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list devices: {e}"}


@server.tool(
    name="access_get_device",
    description=(
        "Returns detailed information for a single Access device including "
        "name, type, connection state, firmware version, MAC, and IP address."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="device",
    permission_action="read",
    auth="either",
)
async def access_get_device(
    device_id: Annotated[str, Field(description="Device UUID (from access_list_devices)")],
) -> Dict[str, Any]:
    """Get detailed device information by ID."""
    logger.info("access_get_device tool called for %s", device_id)
    try:
        raw = await device_manager.get_device(device_id)
        detail = access_device_from_controller(raw).model_dump(exclude_none=True)
        return {"success": True, "data": detail}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting device %s: %s", device_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get device: {e}"}


@server.tool(
    name="access_reboot_device",
    description=(
        "Reboot an Access hardware device (hub, reader, relay, intercom). "
        "The device will be temporarily offline during reboot. "
        "Requires confirm=true to execute. Only available via local proxy session."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False),
    permission_category="device",
    permission_action="update",
    auth="local_only",
)
async def access_reboot_device(
    device_id: Annotated[str, Field(description="Device UUID (from access_list_devices)")],
    confirm: Annotated[
        bool,
        Field(description="When true, executes the reboot. When false (default), returns a preview."),
    ] = False,
) -> Dict[str, Any]:
    """Reboot a device with preview/confirm."""
    logger.info("access_reboot_device tool called for %s (confirm=%s)", device_id, confirm)
    try:
        try:
            params = RebootDeviceInput(device_id=device_id)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}
        device_id = params.device_id

        if confirm:
            result = await device_manager.apply_reboot_device(device_id)
            return {"success": True, "data": result}

        preview_data = await device_manager.reboot_device(device_id)
        return preview_response(
            action="reboot",
            resource_type="access_device",
            resource_id=device_id,
            current_state=preview_data["current_state"],
            proposed_changes=preview_data["proposed_changes"],
            resource_name=preview_data.get("device_name"),
            warnings=["The device will be temporarily offline during reboot."],
        )
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error rebooting device %s: %s", device_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to reboot device: {e}"}


@server.tool(
    name="access_get_device_configs",
    description=(
        "Returns a device's settings (its configs[] array) — the per-device settings the Access web UI "
        "edits, such as the reader voice greeting. Each entry is a {key, value, tag} record; tags group "
        "entries by category (device_setting, device_extra, hub_action, hub_power, wiring_state, credential). "
        "Credential-tagged and secret-named values are redacted. Use this to discover the exact keys before "
        "calling access_update_device_config. Only available via local proxy session."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="device",
    permission_action="read",
    auth="local_only",
)
async def access_get_device_configs(
    device_id: Annotated[str, Field(description="Device UUID (from access_list_devices)")],
) -> Dict[str, Any]:
    """Return a device's config/settings entries, redacting sensitive values."""
    logger.info("access_get_device_configs tool called for %s", device_id)
    redact_sensitive = should_redact_sensitive_fields()
    try:
        info = await device_manager.get_device_configs(device_id)
        projected = [device_config_from_controller(c).model_dump(exclude_none=True) for c in info["configs"]]
        configs = redact_config_entries(projected, redact_sensitive=redact_sensitive)
        return {
            "success": True,
            "data": {
                "device_id": info["device_id"],
                "device_name": info["device_name"],
                "is_camera": info["is_camera"],
                "configs": configs,
                "count": len(configs),
            },
        }
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting device configs %s: %s", device_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get device configs: {e}"}


@server.tool(
    name="access_update_device_config",
    description=(
        "Update a device's settings (its configs[] entries), e.g. the reader voice greeting. Pass 'updates' "
        "as a {key: value} map; only keys the device already exposes may be set (call access_get_device_configs "
        "first to discover them), and credential/secret keys are refused. Requires confirm=true to execute; "
        "confirm=false returns a preview of the current→proposed change. Only available via local proxy session."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    permission_category="device",
    permission_action="update",
    auth="local_only",
)
async def access_update_device_config(
    device_id: Annotated[str, Field(description="Device UUID (from access_list_devices)")],
    updates: Annotated[
        Dict[str, str],
        Field(description="Map of config key → new value. Keys must already exist on the device."),
    ],
    is_camera: Annotated[
        Optional[bool],
        Field(
            description=(
                "Override the camera-class flag for the config PUT. Omit to auto-derive from the device "
                "(camera-class readers vs hubs)."
            )
        ),
    ] = None,
    confirm: Annotated[
        bool,
        Field(description="When true, applies the update. When false (default), returns a preview."),
    ] = False,
) -> Dict[str, Any]:
    """Update device config entries with preview/confirm."""
    logger.info("access_update_device_config tool called for %s (confirm=%s)", device_id, confirm)
    try:
        if confirm:
            result = await device_manager.apply_update_device_config(device_id, updates, is_camera=is_camera)
            return {"success": True, "data": result}

        preview_data = await device_manager.update_device_config(device_id, updates)
        return preview_response(
            action="update",
            resource_type="access_device_config",
            resource_id=device_id,
            current_state=preview_data["current_state"],
            proposed_changes=preview_data["proposed_changes"],
            resource_name=preview_data.get("device_name"),
            warnings=["Applies persistent device settings. Credential/secret keys cannot be written."],
        )
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating device config %s: %s", device_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update device config: {e}"}


logger.info(
    "Device tools registered: access_list_devices, access_get_device, access_reboot_device, "
    "access_get_device_configs, access_update_device_config"
)
