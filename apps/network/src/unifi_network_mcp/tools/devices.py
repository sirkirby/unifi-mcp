"""
Unifi Network MCP device management tools.

This module provides MCP tools to manage devices in a Unifi Network Controller.
"""

import logging
from typing import Annotated, Any, Dict, List, Optional

from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from unifi_core.confirmation import create_preview, preview_response, update_preview
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.models._actions import (
    AdoptDeviceInput,
    ForceProvisionDeviceInput,
    LocateDeviceInput,
    RebootDeviceInput,
    RenameDeviceInput,
    SetDeviceLedInput,
    SetOutletStateInput,
    SetSiteLedsInput,
    UpgradeDeviceInput,
)
from unifi_core.network.models.devices import validate_radio_update
from unifi_core.network.read_views import shape_device_details, shape_device_list, shape_rogue_ap_list

# Import the global FastMCP server instance, config, and managers
from unifi_network_mcp.runtime import device_manager, server

logger = logging.getLogger(__name__)


@server.tool(
    name="unifi_list_devices",
    description=(
        "Returns adopted device inventory with MAC, name, model, IP, firmware version, "
        "uptime, status (online/offline/upgrading/etc), device_category (ap/switch/gateway/pdu), "
        "upgradable flag, connection_network, uplink topology, load_avg, mem_pct, and model_eol. "
        "Filter by device_type (ap/switch/gateway/pdu) and status (online/offline/pending/upgrading). "
        "Note: device_type=ap correctly excludes USP Smart Power strips. "
        "Use search to filter by name, IP, or MAC (case-insensitive). "
        "Set include_details=true for additional per-device fields: by default (summary=true) "
        "compressed radio/port summaries; set summary=false to return the full raw tables "
        "(radio_table, port_table, network_table, system_stats, wan1/wan2)."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_devices(
    device_type: Annotated[
        str,
        Field(
            description="Filter by device type: 'all' (default), 'ap' (access points), 'switch', 'gateway', or 'pdu'"
        ),
    ] = "all",
    status: Annotated[
        str,
        Field(
            description="Filter by device status: 'all' (default), 'online', 'offline', 'pending', 'adopting', 'provisioning', or 'upgrading'"
        ),
    ] = "all",
    search: Annotated[
        Optional[str],
        Field(description="Filter by name, IP, or MAC (case-insensitive substring match)"),
    ] = None,
    limit: Annotated[
        Optional[int],
        Field(description="Maximum number of devices to return (default: all)"),
    ] = None,
    include_details: Annotated[
        bool,
        Field(
            description="When true, includes additional per-device details (shape controlled by summary). Default false"
        ),
    ] = False,
    summary: Annotated[
        bool,
        Field(
            description=(
                "Controls the shape of include_details (only applies when include_details=true). "
                "When true (default), returns compressed summaries (counts, flattened uplink fields). "
                "When false, returns the legacy raw tables (radio_table/port_table/network_table/"
                "system_stats/wan1/wan2/poe_info)."
            )
        ),
    ] = True,
) -> Dict[str, Any]:
    """Implementation for listing devices."""
    try:
        devices = await device_manager.get_devices()
        return shape_device_list(
            devices,
            site=device_manager._connection.site,
            device_type=device_type,
            status=status,
            search=search,
            limit=limit,
            include_details=include_details,
            summary=summary,
        )
    except Exception as e:
        logger.error("Error listing devices: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list devices: {e}"}


@server.tool(
    name="unifi_get_device_details",
    description=(
        "Returns device data for one device by MAC address. By default (summary=false) returns the "
        "full raw device object — all controller-reported fields including radio tables, port tables, "
        "system stats, WAN info, firmware details. Set summary=true to trim to selected sections via "
        "include (basic, ports, radios, stats, uplink, lldp, all).\n\n"
        "Port fields (summary mode):\n"
        "- last_seen_mac: last MAC that sent traffic on port (may be wireless client traffic, not reliable)\n"
        "- lldp_neighbor: actual connected infrastructure device (from LLDP, reliable for switches/APs)\n\n"
        "Examples: <no args> (full raw); summary=true,include='basic' (minimal); "
        "summary=true,include='basic,ports' (switches); summary=true,include='basic,radios' (APs)."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_device_details(
    mac_address: Annotated[
        str,
        Field(description="Device MAC address in format AA:BB:CC:DD:EE:FF (from unifi_list_devices)"),
    ],
    include: Annotated[
        str,
        Field(
            description=(
                "Comma-separated sections to return when summary=true (default 'basic,ports'). "
                "Sections: basic, ports, radios, stats, uplink, lldp, all."
            )
        ),
    ] = "basic,ports",
    summary: Annotated[
        bool,
        Field(
            description=(
                "When false (default), returns the full raw device object. "
                "When true, trims to the sections named in include."
            )
        ),
    ] = False,
) -> Dict[str, Any]:
    """Implementation for getting device details."""
    try:
        device = await device_manager.get_device_details(mac_address)
        return shape_device_details(
            device,
            site=device_manager._connection.site,
            mac_address=mac_address,
            include=include,
            summary=summary,
        )
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting device details for %s: %s", mac_address, e, exc_info=True)
        return {"success": False, "error": f"Failed to get device details for {mac_address}: {e}"}


@server.tool(
    name="unifi_reboot_device",
    description="Reboot a specific device by MAC address",
    permission_category="devices",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False),
)
async def reboot_device(
    mac_address: Annotated[
        str,
        Field(description="MAC address of the device to reboot, in format AA:BB:CC:DD:EE:FF (from unifi_list_devices)"),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, executes the reboot. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Implementation for rebooting a device."""
    try:
        RebootDeviceInput(mac_address=mac_address)
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    if not confirm:
        return preview_response(
            action="reboot",
            resource_type="device",
            resource_id=mac_address,
            resource_name=mac_address,
            current_state={},
            proposed_changes={"action": "reboot - device will restart"},
            warnings=["Device will be offline for 1-2 minutes during reboot"],
        )

    try:
        success = await device_manager.reboot_device(mac_address)
        if success:
            return {
                "success": True,
                "message": f"Reboot initiated for device: {mac_address}",
            }
        return {"success": False, "error": f"Failed to reboot device: {mac_address}"}
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error rebooting device %s: %s", mac_address, e, exc_info=True)
        return {"success": False, "error": f"Failed to reboot device {mac_address}: {e}"}


@server.tool(
    name="unifi_rename_device",
    description="Rename a device in the Unifi Network controller by MAC address",
    permission_category="devices",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def rename_device(
    mac_address: Annotated[
        str,
        Field(description="MAC address of the device to rename, in format AA:BB:CC:DD:EE:FF (from unifi_list_devices)"),
    ],
    name: Annotated[str, Field(description="New display name for the device (e.g., 'Office AP')")],
    confirm: Annotated[
        bool,
        Field(description="When true, executes the rename. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Implementation for renaming a device."""
    try:
        RenameDeviceInput(mac_address=mac_address, name=name)
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    if not confirm:
        return update_preview(
            resource_type="device",
            resource_id=mac_address,
            resource_name=mac_address,
            current_state={},
            updates={"name": name},
        )

    try:
        success = await device_manager.rename_device(mac_address, name)
        if success:
            return {
                "success": True,
                "message": f"Device {mac_address} renamed to '{name}' successfully.",
            }
        return {"success": False, "error": f"Failed to rename device {mac_address}."}
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error renaming device %s: %s", mac_address, e, exc_info=True)
        return {"success": False, "error": f"Failed to rename device {mac_address}: {e}"}


@server.tool(
    name="unifi_adopt_device",
    description="Adopt a pending device into the Unifi Network by MAC address",
    permission_category="devices",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def adopt_device(
    mac_address: Annotated[
        str,
        Field(
            description="MAC address of the pending device to adopt, in format AA:BB:CC:DD:EE:FF (from unifi_list_devices with status='pending')"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(
            description="When true, initiates device adoption. When false (default), returns a preview of the changes"
        ),
    ] = False,
) -> Dict[str, Any]:
    """Implementation for adopting a device."""
    try:
        AdoptDeviceInput(mac_address=mac_address)
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    if not confirm:
        return create_preview(
            resource_type="device_adoption",
            resource_name=mac_address,
            resource_data={"mac": mac_address},
            warnings=[
                "Device will be adopted into this site",
                "Device may reboot during adoption process",
            ],
        )

    try:
        success = await device_manager.adopt_device(mac_address)
        if success:
            return {
                "success": True,
                "message": f"Adoption initiated for device: {mac_address}",
            }
        return {"success": False, "error": f"Failed to adopt device {mac_address}."}
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error adopting device %s: %s", mac_address, e, exc_info=True)
        return {"success": False, "error": f"Failed to adopt device {mac_address}: {e}"}


@server.tool(
    name="unifi_upgrade_device",
    description="Initiate a firmware upgrade for a device by MAC address (uses cached firmware by default)",
    permission_category="devices",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False),
)
async def upgrade_device(
    mac_address: Annotated[
        str,
        Field(
            description="MAC address of the device to upgrade, in format AA:BB:CC:DD:EE:FF (from unifi_list_devices)"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(
            description="When true, initiates the firmware upgrade. When false (default), returns a preview of the changes"
        ),
    ] = False,
) -> Dict[str, Any]:
    """Implementation for upgrading a device."""
    try:
        UpgradeDeviceInput(mac_address=mac_address)
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    if not confirm:
        return preview_response(
            action="upgrade",
            resource_type="device",
            resource_id=mac_address,
            resource_name=mac_address,
            current_state={},
            proposed_changes={"action": "firmware upgrade"},
            warnings=[
                "Device will be offline during firmware upgrade",
                "Upgrade process may take several minutes",
                "Do not power off device during upgrade",
            ],
        )

    try:
        success = await device_manager.upgrade_device(mac_address)
        if success:
            return {
                "success": True,
                "message": f"Upgrade initiated for device: {mac_address}",
            }
        return {"success": False, "error": f"Failed to upgrade device {mac_address}."}
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error upgrading device %s: %s", mac_address, e, exc_info=True)
        return {"success": False, "error": f"Failed to upgrade device {mac_address}: {e}"}


RADIO_BAND_LABELS = {"ng": "2.4GHz", "na": "5GHz", "6e": "6GHz", "wifi6e": "6GHz"}


@server.tool(
    name="unifi_get_device_radio",
    description=(
        "Get radio configuration and live statistics for an access point. "
        "Returns per-band config (channel, tx_power, channel width, min_rssi) "
        "and live stats (actual tx_power, channel utilization, client count, retries)."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_device_radio(
    mac_address: Annotated[
        str,
        Field(
            description="MAC address of the access point, in format AA:BB:CC:DD:EE:FF (from unifi_list_devices with device_type='ap')"
        ),
    ],
) -> Dict[str, Any]:
    """Implementation for getting focused radio config and stats for an AP."""
    try:
        result = await device_manager.get_device_radio(mac_address)
        if result is None:
            return {
                "success": False,
                "error": f"Device {mac_address} is not an access point.",
            }
        return {
            "success": True,
            "site": device_manager._connection.site,
            **result,
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting radio info for %s: %s", mac_address, e, exc_info=True)
        return {"success": False, "error": f"Failed to get radio info for device {mac_address}: {e}"}


@server.tool(
    name="unifi_update_device_radio",
    description=(
        "Update radio settings for a specific band on an access point. "
        "Supports tx_power_mode, tx_power (custom dBm), channel, ht (channel width), "
        "min_rssi_enabled, min_rssi, assisted_roaming_enabled (802.11k/v), "
        "antenna_gain (dBi), vwire_enabled, sens_level_enabled, sens_level. "
        "Use unifi_get_device_radio first to see current settings."
    ),
    permission_category="devices",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_device_radio(
    mac_address: Annotated[
        str,
        Field(description="MAC address of the access point, in format AA:BB:CC:DD:EE:FF (from unifi_list_devices)"),
    ],
    radio: Annotated[
        str,
        Field(
            description="Radio band code to configure: 'na' (5GHz), 'ng' (2.4GHz), '6e'/'wifi6e' (6GHz), or internal name like 'wifi0', 'wifi1'"
        ),
    ],
    tx_power_mode: Annotated[
        Optional[str],
        Field(description="Transmit power mode: 'auto', 'high', 'medium', 'low', or 'custom' (requires tx_power)"),
    ] = None,
    tx_power: Annotated[
        Optional[int],
        Field(description="Custom transmit power in dBm (only valid when tx_power_mode='custom')"),
    ] = None,
    channel: Annotated[
        Optional[int],
        Field(description="WiFi channel number (e.g., 1, 6, 11 for 2.4GHz; 36, 44, 149 for 5GHz)"),
    ] = None,
    ht: Annotated[
        Optional[str],
        Field(description="Channel width: '20', '40', '80', '160', or '320' MHz"),
    ] = None,
    min_rssi_enabled: Annotated[
        Optional[bool],
        Field(description="Enable minimum RSSI threshold to disconnect weak clients"),
    ] = None,
    min_rssi: Annotated[
        Optional[int],
        Field(description="Minimum RSSI value in dBm (e.g., -75). Only valid when min_rssi_enabled=true"),
    ] = None,
    assisted_roaming_enabled: Annotated[
        Optional[bool],
        Field(description="Enable 802.11k/v assisted roaming (neighbor reports and BSS transition management)"),
    ] = None,
    antenna_gain: Annotated[
        Optional[int],
        Field(description="External antenna gain in dBi for regulatory TX power compensation"),
    ] = None,
    vwire_enabled: Annotated[
        Optional[bool],
        Field(description="Enable virtual wire mode (transparent bridge for meshed APs)"),
    ] = None,
    sens_level_enabled: Annotated[
        Optional[bool],
        Field(description="Enable receive sensitivity level adjustment"),
    ] = None,
    sens_level: Annotated[
        Optional[int],
        Field(description="Receive sensitivity level in dBm. Only valid when sens_level_enabled=true"),
    ] = None,
    confirm: Annotated[
        bool,
        Field(description="When true, applies radio changes. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Implementation for updating AP radio settings."""
    updates: Dict[str, Any] = {}
    if tx_power_mode is not None:
        updates["tx_power_mode"] = tx_power_mode
    if tx_power is not None:
        updates["tx_power"] = tx_power
    if channel is not None:
        updates["channel"] = channel
    if ht is not None:
        updates["ht"] = ht
    if min_rssi_enabled is not None:
        updates["min_rssi_enabled"] = min_rssi_enabled
    if min_rssi is not None:
        updates["min_rssi"] = min_rssi
    if assisted_roaming_enabled is not None:
        updates["assisted_roaming_enabled"] = assisted_roaming_enabled
    if antenna_gain is not None:
        updates["antenna_gain"] = antenna_gain
    if vwire_enabled is not None:
        updates["vwire_enabled"] = vwire_enabled
    if sens_level_enabled is not None:
        updates["sens_level_enabled"] = sens_level_enabled
    if sens_level is not None:
        updates["sens_level"] = sens_level

    try:
        validated_data = validate_radio_update(radio, updates)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    try:
        radio_data = await device_manager.get_device_radio(mac_address)
        if radio_data is None:
            return {
                "success": False,
                "error": f"Device {mac_address} not found or is not an access point.",
            }

        target_radio = next((r for r in radio_data["radios"] if r["radio"] == radio or r["name"] == radio), None)
        if not target_radio:
            available = [
                f"{r['radio']} ({RADIO_BAND_LABELS.get(r['radio'], r['radio'])})" for r in radio_data["radios"]
            ]
            return {
                "success": False,
                "error": f"Radio '{radio}' not found on device. Available: {', '.join(available)}",
            }

        band_label = RADIO_BAND_LABELS.get(target_radio["radio"], target_radio.get("name", radio))
        device_name = radio_data.get("name", mac_address)

        current_state = {k: target_radio.get(k) for k in validated_data}

        if not confirm:
            preview = update_preview(
                resource_type="device_radio",
                resource_id=f"{mac_address}/{radio}",
                resource_name=f"{device_name} ({band_label})",
                current_state=current_state,
                updates=validated_data,
            )
            preview["warnings"] = [
                "AP radio will restart briefly after changes are applied.",
                "Connected clients may experience a brief disconnection.",
            ]
            return preview

        success = await device_manager.update_device_radio(mac_address, radio, validated_data)
        if success:
            return {
                "success": True,
                "message": f"Radio '{radio}' ({band_label}) updated on {device_name} ({mac_address}).",
                "updated_fields": list(updates.keys()),
            }
        return {"success": False, "error": f"Failed to update radio '{radio}' on device {mac_address}."}
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating radio on %s: %s", mac_address, e, exc_info=True)
        return {"success": False, "error": f"Failed to update radio on device {mac_address}: {e}"}


# ---- Device Management Commands ----


@server.tool(
    name="unifi_locate_device",
    description="Toggle device locate mode (LED blinking) to physically identify a device. "
    "Works on any UniFi device (switches, APs, gateways). Requires confirmation.",
    permission_category="devices",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def locate_device(
    device_mac: Annotated[str, Field(description="MAC address of the device (from unifi_list_devices)")],
    enabled: Annotated[bool, Field(description="True to start blinking, False to stop")],
    confirm: Annotated[
        bool,
        Field(description="When true, toggles locate mode. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Toggles device locate mode (LED blinking)."""
    try:
        LocateDeviceInput(device_mac=device_mac, enabled=enabled)
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    if not confirm:
        action = "start" if enabled else "stop"
        return create_preview(
            resource_type="device_locate",
            resource_data={"device_mac": device_mac, "enabled": enabled},
            resource_name=device_mac,
            warnings=[f"Will {action} LED blinking on device {device_mac}."],
        )

    try:
        success = await device_manager.locate_device(device_mac, enabled)
        if success:
            state = "enabled" if enabled else "disabled"
            return {"success": True, "message": f"Locate mode {state} on device '{device_mac}'."}
        return {"success": False, "error": f"Failed to set locate mode on '{device_mac}'."}
    except Exception as e:
        logger.error("Error setting locate mode on %s: %s", device_mac, e, exc_info=True)
        return {"success": False, "error": f"Failed to set locate mode on {device_mac}: {e}"}


@server.tool(
    name="unifi_force_provision_device",
    description="Force re-provision a device, pushing the current configuration from the "
    "controller to the device. Works on any UniFi device (switches, APs, gateways). "
    "Useful after manual changes or to resolve config drift. Requires confirmation.",
    permission_category="devices",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def force_provision_device(
    device_mac: Annotated[str, Field(description="MAC address of the device (from unifi_list_devices)")],
    confirm: Annotated[
        bool,
        Field(description="When true, force provisions the device. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Force re-provisions a device."""
    try:
        ForceProvisionDeviceInput(device_mac=device_mac)
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    if not confirm:
        return create_preview(
            resource_type="force_provision",
            resource_data={"device_mac": device_mac},
            resource_name=device_mac,
        )

    try:
        success = await device_manager.force_provision(device_mac)
        if success:
            return {"success": True, "message": f"Force provision initiated for device '{device_mac}'."}
        return {"success": False, "error": f"Failed to force provision device '{device_mac}'."}
    except Exception as e:
        logger.error("Error force provisioning %s: %s", device_mac, e, exc_info=True)
        return {"success": False, "error": f"Failed to force provision device {device_mac}: {e}"}


# ---- Speedtest Commands ----


@server.tool(
    name="unifi_trigger_speedtest",
    description="Trigger a speedtest on the gateway device. Returns immediately; "
    "use unifi_get_speedtest_status to poll for results.",
    permission_category="devices",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def trigger_speedtest(
    gateway_mac: Annotated[str, Field(description="MAC address of the gateway device")],
    confirm: Annotated[
        bool,
        Field(description="When true, triggers the speedtest. When false (default), returns a preview."),
    ] = False,
) -> Dict[str, Any]:
    """Triggers a speedtest on the gateway."""
    if not confirm:
        return create_preview(
            resource_type="speedtest",
            resource_data={"gateway_mac": gateway_mac},
            resource_name=gateway_mac,
        )

    try:
        success = await device_manager.trigger_speedtest(gateway_mac)
        if success:
            return {
                "success": True,
                "message": f"Speedtest triggered on gateway '{gateway_mac}'. Use unifi_get_speedtest_status to check progress.",
            }
        return {"success": False, "error": f"Failed to trigger speedtest on '{gateway_mac}'."}
    except Exception as e:
        logger.error("Error triggering speedtest on %s: %s", gateway_mac, e, exc_info=True)
        return {"success": False, "error": f"Failed to trigger speedtest on {gateway_mac}: {e}"}


@server.tool(
    name="unifi_get_speedtest_status",
    description="Check the status of a running speedtest on the gateway.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_speedtest_status(
    gateway_mac: Annotated[str, Field(description="MAC address of the gateway device")],
) -> Dict[str, Any]:
    """Checks speedtest status on the gateway."""
    try:
        status = await device_manager.get_speedtest_status(gateway_mac)
        return {
            "success": True,
            "site": device_manager._connection.site,
            "gateway_mac": gateway_mac,
            "status": status,
        }
    except Exception as e:
        logger.error("Error getting speedtest status for %s: %s", gateway_mac, e, exc_info=True)
        return {"success": False, "error": f"Failed to get speedtest status for {gateway_mac}: {e}"}


# ---- RF Environment Tools ----


@server.tool(
    name="unifi_list_rogue_aps",
    description=(
        "List neighboring/rogue APs detected by your access points. "
        "Defaults to a compact 100-record page; pass summary=false for raw records in the selected page. "
        "Filters apply before pagination, limit is at most 500, and pagination metadata includes "
        "total_count, returned_count/count, limit, offset, next_offset, and has_more."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_rogue_aps(
    within_hours: Annotated[
        int,
        Field(description="Hours to look back for detected APs (default 24)"),
    ] = 24,
    channel: Annotated[
        Optional[int],
        Field(description="Filter to a specific channel (e.g., 1, 6, 11 for 2.4GHz; 36, 100 for 5GHz)"),
    ] = None,
    min_signal: Annotated[
        Optional[int],
        Field(description="Minimum signal strength in dBm (e.g., -70 to only show strong neighbors)"),
    ] = None,
    limit: Annotated[
        int,
        Field(ge=1, le=500, description="Maximum records per page (default 100, max 500)"),
    ] = 100,
    offset: Annotated[
        int,
        Field(ge=0, description="Zero-based offset into the filtered records (default 0)"),
    ] = 0,
    summary: Annotated[
        bool,
        Field(description="Return compact AP fields; default true. Set false for raw records in the selected page"),
    ] = True,
) -> Dict[str, Any]:
    """List neighboring/rogue APs detected by your access points."""
    try:
        rogue_aps = await device_manager.list_rogue_aps(within_hours)
        return shape_rogue_ap_list(
            rogue_aps,
            site=device_manager._connection.site,
            within_hours=within_hours,
            channel=channel,
            min_signal=min_signal,
            limit=limit,
            offset=offset,
            summary=summary,
        )
    except Exception as e:
        logger.error("Error listing rogue APs: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list rogue APs: {e}"}


@server.tool(
    name="unifi_trigger_rf_scan",
    description=(
        "Trigger an RF spectrum scan on an access point. Requires confirmation. "
        "The scan takes 5-10 minutes to complete. Some APs have a dedicated scanning radio "
        "and scan without going offline; others briefly go off-channel "
        "which may cause momentary client disconnections. "
        "Poll unifi_get_rf_scan_results periodically — results appear only after the scan finishes. "
        "Returns per-channel interference levels and utilization across all bands."
    ),
    permission_category="devices",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def trigger_rf_scan(
    ap_mac: Annotated[
        str,
        Field(
            description="MAC address of the access point to scan, in format AA:BB:CC:DD:EE:FF (from unifi_list_devices with device_type='ap')"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(
            description="When true, triggers the RF scan. When false (default), returns a preview. "
            "WARNING: AP briefly goes off-channel during scan"
        ),
    ] = False,
) -> Dict[str, Any]:
    """Trigger an RF spectrum scan on an access point."""
    if not confirm:
        return create_preview(
            resource_type="rf_scan",
            resource_data={"ap_mac": ap_mac},
            resource_name=ap_mac,
            warnings=[
                "Scan takes 5-10 minutes. Some APs go off-channel during scan (momentary client disconnections). "
                "APs with a dedicated scanning radio scan without disruption.",
                "Poll unifi_get_rf_scan_results periodically — results appear only after completion.",
            ],
        )

    try:
        success = await device_manager.trigger_rf_scan(ap_mac)
        if success:
            return {
                "success": True,
                "message": f"RF scan triggered on AP '{ap_mac}'. Use unifi_get_rf_scan_results to check results.",
            }
        return {"success": False, "error": f"Failed to trigger RF scan on AP '{ap_mac}'."}
    except Exception as e:
        logger.error("Error triggering RF scan on %s: %s", ap_mac, e, exc_info=True)
        return {"success": False, "error": f"Failed to trigger RF scan on AP '{ap_mac}': {e}"}


@server.tool(
    name="unifi_get_rf_scan_results",
    description=(
        "Get RF spectrum scan results for an access point. "
        "Returns per-channel interference levels (dBm), utilization (%), and BSS counts for each radio band. "
        "Trigger a scan first with unifi_trigger_rf_scan if no results are available. "
        "Scans take 5-10 minutes — if spectrum_scanning is true, the scan is still in progress."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_rf_scan_results(
    ap_mac: Annotated[
        str,
        Field(
            description="MAC address of the access point, in format AA:BB:CC:DD:EE:FF (from unifi_list_devices with device_type='ap')"
        ),
    ],
) -> Dict[str, Any]:
    """Get RF spectrum scan results for an AP."""
    try:
        results = await device_manager.get_rf_scan_results(ap_mac)
        return {
            "success": True,
            "site": device_manager._connection.site,
            "ap_mac": ap_mac,
            "count": len(results),
            "scan_results": results,
        }
    except Exception as e:
        logger.error("Error getting RF scan results for %s: %s", ap_mac, e, exc_info=True)
        return {"success": False, "error": f"Failed to get RF scan results for AP '{ap_mac}': {e}"}


@server.tool(
    name="unifi_list_available_channels",
    description=(
        "List allowed RF channels for the site's regulatory domain. "
        "Returns per-band channel lists with DFS status and max power. "
        "Useful for planning channel assignments."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_available_channels() -> Dict[str, Any]:
    """List allowed RF channels for the site's regulatory domain."""
    try:
        channels = await device_manager.list_available_channels()
        return {
            "success": True,
            "site": device_manager._connection.site,
            "channels": channels,
        }
    except Exception as e:
        logger.error("Error listing available channels: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list available channels: {e}"}


# ---- Device LED & State Controls ----


@server.tool(
    name="unifi_set_device_led",
    description=(
        "Set the LED override state on a specific device. "
        "Use 'on' to force LEDs on, 'off' to force them off, or 'default' to use site-wide setting. "
        "Requires confirmation."
    ),
    permission_category="devices",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def set_device_led(
    device_mac: Annotated[str, Field(description="MAC address of the device (from unifi_list_devices)")],
    led_state: Annotated[
        str,
        Field(description="LED override state: 'on' (force on), 'off' (force off), or 'default' (use site setting)"),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the LED change. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Set LED override state on a device."""
    try:
        SetDeviceLedInput(device_mac=device_mac, led_state=led_state)
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    valid_states = ("on", "off", "default")
    if led_state not in valid_states:
        return {
            "success": False,
            "error": f"Invalid led_state '{led_state}'. Must be one of: {', '.join(valid_states)}",
        }

    if not confirm:
        return create_preview(
            resource_type="device_led",
            resource_data={"device_mac": device_mac, "led_override": led_state},
            resource_name=device_mac,
        )

    try:
        success = await device_manager.set_device_led_override(device_mac, led_state)
        if success:
            return {"success": True, "message": f"LED override set to '{led_state}' on device '{device_mac}'."}
        return {"success": False, "error": f"Failed to set LED override on '{device_mac}'."}
    except Exception as e:
        logger.error("Error setting LED override on %s: %s", device_mac, e, exc_info=True)
        return {"success": False, "error": f"Failed to set LED override on {device_mac}: {e}"}


@server.tool(
    name="unifi_toggle_device",
    description=(
        "Enable or disable a device without unadopting it. "
        "A disabled device remains adopted but stops passing traffic. "
        "Requires confirmation."
    ),
    permission_category="devices",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def toggle_device(
    device_mac: Annotated[str, Field(description="MAC address of the device (from unifi_list_devices)")],
    disabled: Annotated[bool, Field(description="True to disable the device, False to enable it")],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the change. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Enable or disable a device without unadopting it."""
    if not confirm:
        action = "disable" if disabled else "enable"
        return create_preview(
            resource_type="device_toggle",
            resource_data={"device_mac": device_mac, "disabled": disabled},
            resource_name=device_mac,
            warnings=[f"Will {action} device {device_mac}. A disabled device stops passing traffic."],
        )

    try:
        success = await device_manager.set_device_disabled(device_mac, disabled)
        if success:
            state = "disabled" if disabled else "enabled"
            return {"success": True, "message": f"Device '{device_mac}' has been {state}."}
        return {"success": False, "error": f"Failed to set disabled state on '{device_mac}'."}
    except Exception as e:
        logger.error("Error toggling device %s: %s", device_mac, e, exc_info=True)
        return {"success": False, "error": f"Failed to toggle device {device_mac}: {e}"}


@server.tool(
    name="unifi_set_site_leds",
    description=(
        "Toggle all device LEDs site-wide on or off. "
        "This sets the global LED policy for the site — individual device overrides take precedence. "
        "Requires confirmation."
    ),
    permission_category="devices",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def set_site_leds(
    enabled: Annotated[bool, Field(description="True to enable all site LEDs, False to disable them")],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the change. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Toggle all device LEDs site-wide."""
    try:
        SetSiteLedsInput(enabled=enabled)
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    if not confirm:
        action = "enable" if enabled else "disable"
        return create_preview(
            resource_type="site_leds",
            resource_data={"led_enabled": enabled},
            resource_name="site-wide LEDs",
            warnings=[f"Will {action} LEDs on all devices site-wide. Individual device overrides take precedence."],
        )

    try:
        success = await device_manager.set_site_led_enabled(enabled)
        if success:
            state = "enabled" if enabled else "disabled"
            return {"success": True, "message": f"Site-wide LEDs have been {state}."}
        return {"success": False, "error": "Failed to set site-wide LED state."}
    except Exception as e:
        logger.error("Error setting site LEDs: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to set site-wide LED state: {e}"}


# ---- Smart Power Strip (UP6 / USP-Strip) Outlet Control ----


@server.tool(
    name="unifi_get_pdu_outlets",
    description=(
        "Return per-outlet state for a UniFi Smart Power PDU (UP6 / USP-Strip). "
        "Combines the device's sensed outlet_table (live relay_state, cycle_enabled, "
        "has_relay, has_metering) with the controller's desired outlet_overrides "
        "so callers see both reported and intended state per outlet. "
        "Returns an error if the device is not a PDU."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_pdu_outlets(
    mac_address: Annotated[
        str,
        Field(
            description="MAC address of the PDU, in format AA:BB:CC:DD:EE:FF (from unifi_list_devices with device_type='pdu')"
        ),
    ],
) -> Dict[str, Any]:
    """Implementation for fetching per-outlet state on a Smart Power PDU."""
    try:
        result = await device_manager.get_pdu_outlets(mac_address)
        if result is None:
            return {
                "success": False,
                "error": f"Device {mac_address} is not a Smart Power PDU.",
            }
        return {
            "success": True,
            "site": device_manager._connection.site,
            **result,
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting PDU outlets for %s: %s", mac_address, e, exc_info=True)
        return {"success": False, "error": f"Failed to get PDU outlets for {mac_address}: {e}"}


@server.tool(
    name="unifi_set_outlet_state",
    description=(
        "Set per-outlet relay state (on/off) and optionally cycle_enabled on a UniFi "
        "Smart Power PDU (UP6 / USP-Strip). The controller stores per-outlet desired "
        "state in the outlet_overrides array on the device document; this tool reads "
        "the existing array, replaces only the entry whose index matches outlet_index, "
        "and PUTs the full array back -- preserving all sibling outlets' overrides "
        "(name, relay_state, cycle_enabled) verbatim. If no override exists for the "
        "target outlet yet, one is created from the outlet's current sensed state. "
        "Use unifi_get_pdu_outlets first to inspect current state."
    ),
    permission_category="devices",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def set_outlet_state(
    mac_address: Annotated[
        str,
        Field(
            description="MAC address of the PDU, in format AA:BB:CC:DD:EE:FF (from unifi_list_devices with device_type='pdu')"
        ),
    ],
    outlet_index: Annotated[
        int,
        Field(
            description="1-based outlet index on the strip (e.g. 1..6 for UP6, 1..7 if a USB outlet group is present)"
        ),
    ],
    relay_state: Annotated[
        bool,
        Field(description="Desired relay state for this outlet: true to power on, false to power off"),
    ],
    cycle_enabled: Annotated[
        Optional[bool],
        Field(
            description=(
                "Optional override for the per-outlet 'power cycle on power loss' toggle. "
                "Omit (null) to leave it unchanged."
            )
        ),
    ] = None,
    confirm: Annotated[
        bool,
        Field(description="When true, writes the change. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Set per-outlet relay/cycle state on a UP6 / USP-Strip PDU."""
    try:
        SetOutletStateInput(
            mac_address=mac_address,
            outlet_index=outlet_index,
            relay_state=relay_state,
            cycle_enabled=cycle_enabled,
        )
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    if outlet_index < 1:
        return {"success": False, "error": "outlet_index must be >= 1."}

    try:
        pdu = await device_manager.get_pdu_outlets(mac_address)
        if pdu is None:
            return {
                "success": False,
                "error": f"Device {mac_address} is not a Smart Power PDU.",
            }

        outlets = pdu.get("outlets", [])
        target = next((o for o in outlets if o.get("index") == outlet_index), None)
        if target is None:
            available = sorted(o.get("index") for o in outlets if o.get("index") is not None)
            return {
                "success": False,
                "error": (
                    f"Outlet index {outlet_index} not found on PDU {mac_address}. Available indices: {available}"
                ),
            }
        if target.get("has_relay") is False:
            return {
                "success": False,
                "error": (
                    f"Outlet {outlet_index} ('{target.get('name')}') on PDU {mac_address} "
                    "does not have a controllable relay (has_relay=false)."
                ),
            }

        device_name = pdu.get("name", mac_address)
        # Effective current desired state = override if present, else sensed.
        current_relay = target.get("override_relay_state")
        if current_relay is None:
            current_relay = target.get("relay_state")
        current_cycle = target.get("override_cycle_enabled")
        if current_cycle is None:
            current_cycle = target.get("cycle_enabled")

        proposed: Dict[str, Any] = {"relay_state": relay_state}
        if cycle_enabled is not None:
            proposed["cycle_enabled"] = cycle_enabled

        if not confirm:
            preview = update_preview(
                resource_type="pdu_outlet",
                resource_id=f"{mac_address}/outlet/{outlet_index}",
                resource_name=f"{device_name} -- outlet {outlet_index} ({target.get('name')})",
                current_state={"relay_state": current_relay, "cycle_enabled": current_cycle},
                updates=proposed,
            )
            warnings: List[str] = []
            if current_relay is True and relay_state is False:
                warnings.append(
                    f"Outlet {outlet_index} ('{target.get('name')}') is currently powered ON -- "
                    "anything plugged into it will lose power."
                )
            warnings.append(
                "All other outlets on this strip will be left untouched (their existing overrides are preserved)."
            )
            preview["warnings"] = warnings
            return preview

        result = await device_manager.set_outlet_state(
            device_mac=mac_address,
            outlet_index=outlet_index,
            relay_state=relay_state,
            cycle_enabled=cycle_enabled,
        )
        if result is None:
            return {
                "success": False,
                "error": f"Failed to set outlet state on PDU {mac_address}.",
            }
        return {
            "success": True,
            "message": (
                f"Outlet {outlet_index} ('{result.get('name')}') on {device_name} "
                f"set to relay_state={result['relay_state']}."
            ),
            "outlet": result,
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error setting outlet state on %s: %s", mac_address, e, exc_info=True)
        return {
            "success": False,
            "error": f"Failed to set outlet state on PDU {mac_address}: {e}",
        }
