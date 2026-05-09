"""
Unifi Network MCP device management tools.

This module provides MCP tools to manage devices in a Unifi Network Controller.
"""

import logging
from datetime import datetime, timedelta
from typing import Annotated, Any, Dict, List, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.confirmation import create_preview, preview_response, update_preview
from unifi_core.exceptions import UniFiNotFoundError

# Import the global FastMCP server instance, config, and managers
from unifi_network_mcp.runtime import device_manager, server
from unifi_network_mcp.validator_registry import UniFiValidatorRegistry

logger = logging.getLogger(__name__)


# Model prefixes for USP Smart Power devices that may report as 'uap' type
_POWER_DEVICE_MODELS = {"UP1", "UP6", "USP"}


def classify_device(device: Dict[str, Any]) -> str:
    """Classify a device into a semantic category.

    Uses the controller's ``is_access_point`` flag as the primary signal
    for distinguishing real APs from other ``uap``-typed devices (e.g.,
    USP Smart Power strips that connect via wireless mesh).  Falls back
    to model-prefix matching when the flag is absent.

    Returns one of: 'ap', 'switch', 'gateway', 'pdu', 'unknown'
    """
    device_type = device.get("type", "")
    model = device.get("model", "")

    # Explicit power device types
    if device_type.startswith("usp"):
        return "pdu"

    # For uap-typed devices, use the controller's is_access_point flag
    if device_type.startswith("uap"):
        is_ap = device.get("is_access_point")
        if is_ap is not None:
            if not is_ap:
                return "pdu"
            return "ap"
        # Fallback: check model prefix when flag is missing (older firmware)
        if any(model.upper().startswith(prefix) for prefix in _POWER_DEVICE_MODELS):
            return "pdu"
        return "ap"

    if device_type[:3] in ("usw", "usk"):
        return "switch"
    if device_type[:3] in ("ugw", "udm", "uxg"):
        return "gateway"
    if device_type == "uci":
        return "wan"

    return "unknown"


def get_wifi_bands(device: Dict[str, Any]) -> List[str]:
    """Extract active WiFi bands from device radio table."""
    bands = set()
    for radio in device.get("radio_table", []):
        if radio.get("radio") == "na":
            bands.add("5GHz")
        elif radio.get("radio") == "ng":
            bands.add("2.4GHz")
        elif radio.get("radio") == "wifi6e":
            bands.add("6GHz")
    return sorted(list(bands))


@server.tool(
    name="unifi_list_devices",
    description=(
        "Returns adopted device inventory with MAC, name, model, IP, firmware version, "
        "uptime, status (online/offline/upgrading/etc), device_category (ap/switch/gateway/pdu), "
        "upgradable flag, connection_network, uplink topology, load_avg, mem_pct, and model_eol. "
        "Filter by device_type (ap/switch/gateway/pdu) and status (online/offline/pending/upgrading). "
        "Note: device_type=ap correctly excludes USP Smart Power strips. "
        "Set include_details=true for radio tables, port tables, and client counts. "
        "For a single device's full raw object, use unifi_get_device_details."
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
    include_details: Annotated[
        bool,
        Field(
            description="When true, includes additional details like radio tables (APs), port tables (switches), WAN info (gateways), and client counts. Default false"
        ),
    ] = False,
) -> Dict[str, Any]:
    """Implementation for listing devices."""
    try:
        devices = await device_manager.get_devices()

        # Convert Device objects to plain dictionaries for easier filtering
        devices_raw = [d.raw if hasattr(d, "raw") else d for d in devices]

        # Filter by device type using semantic classification
        if device_type != "all":
            devices_raw = [d for d in devices_raw if classify_device(d) == device_type]

        # Filter by status
        if status != "all":
            status_map = {
                "online": 1,
                "offline": 0,
                "pending": 2,
                "adopting": 4,
                "provisioning": 5,
                "upgrading": 6,
            }
            target_state = status_map.get(status)
            if target_state is not None:
                devices_raw = [d for d in devices_raw if d.get("state") == target_state]
            else:
                logger.warning("Unknown status filter: %s", status)

        formatted_devices = []
        state_map = {
            0: "offline",
            1: "online",
            2: "pending_adoption",
            4: "managed_by_other/adopting",
            5: "provisioning",
            6: "upgrading",
            11: "error/heartbeat_missed",
        }

        for device in devices_raw:
            device_state = device.get("state", 0)
            device_status_str = state_map.get(device_state, f"unknown_state ({device_state})")

            category = classify_device(device)

            # Extract per-device resource stats (available on all device types)
            sys_stats = device.get("sys_stats", {})
            mem_total = sys_stats.get("mem_total", 0)
            mem_used = sys_stats.get("mem_used", 0)
            mem_pct = round((mem_used / mem_total) * 100, 1) if mem_total else None

            # Uplink topology
            uplink = device.get("uplink", device.get("last_uplink", {}))
            uplink_info = None
            if uplink:
                uplink_info = {
                    "type": uplink.get("type", "unknown"),
                    "speed": uplink.get("speed", 0),
                    "uplink_device": uplink.get("uplink_device_name"),
                    "uplink_port": uplink.get("uplink_remote_port"),
                }

            device_info = {
                "mac": device.get("mac", ""),
                "name": device.get("name", device.get("model", "Unknown")),
                "model": device.get("model", ""),
                "type": device.get("type", ""),
                "device_category": category,
                "ip": device.get("ip", ""),
                "status": device_status_str,
                "uptime": str(timedelta(seconds=device.get("uptime", 0))) if device.get("uptime") else "N/A",
                "last_seen": (
                    datetime.fromtimestamp(device.get("last_seen", 0)).isoformat() if device.get("last_seen") else "N/A"
                ),
                "firmware": device.get("version", ""),
                "upgradable": device.get("upgradable", False),
                "adopted": device.get("adopted", False),
                "connection_network": device.get("connection_network_name", ""),
                "uplink": uplink_info,
                "load_avg_1": sys_stats.get("loadavg_1"),
                "mem_pct": mem_pct,
                "model_eol": device.get("model_in_eol", False),
                "_id": device.get("_id", ""),
            }

            if include_details:
                details_to_add = {
                    "serial": device.get("serial", ""),
                    "hw_revision": device.get("hw_rev", ""),
                    "model_display": device.get("model_display", device.get("model")),
                    "clients": device.get("num_sta", 0),
                }

                if category == "ap":
                    details_to_add.update(
                        {
                            "radio_table": device.get("radio_table", []),
                            "vap_table": device.get("vap_table", []),
                            "wifi_bands": get_wifi_bands(device),
                            "experience_score": device.get("satisfaction", 0),
                            "num_clients": device.get("num_sta", 0),
                        }
                    )
                elif category == "switch":
                    details_to_add.update(
                        {
                            "ports": device.get("port_table", []),
                            "total_ports": len(device.get("port_table", [])),
                            "num_clients": device.get("user-num_sta", 0) + device.get("guest-num_sta", 0),
                            "poe_info": {
                                "poe_current": device.get("poe_current"),
                                "poe_power": device.get("poe_power"),
                                "poe_voltage": device.get("poe_voltage"),
                            },
                        }
                    )
                elif category == "gateway":
                    details_to_add.update(
                        {
                            "wan1": device.get("wan1", {}),
                            "wan2": device.get("wan2", {}),
                            "num_clients": device.get("user-num_sta", 0) + device.get("guest-num_sta", 0),
                            "network_table": device.get("network_table", []),
                            "system_stats": device.get("system-stats", {}),
                            "speedtest_status": device.get("speedtest-status", {}),
                        }
                    )

                device_info.update(details_to_add)

            formatted_devices.append(device_info)

        return {
            "success": True,
            "site": device_manager._connection.site,
            "filter_type": device_type,
            "filter_status": status,
            "count": len(formatted_devices),
            "devices": formatted_devices,
        }
    except Exception as e:
        logger.error("Error listing devices: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list devices: {e}"}


@server.tool(
    name="unifi_get_device_details",
    description=(
        "Returns the full raw device object for one device by MAC address — includes "
        "radio tables, port tables, system stats, WAN info, firmware details, and all "
        "controller-reported fields. Use when you need deep inspection of a specific "
        "device. For a filtered overview of all devices, use unifi_list_devices."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_device_details(
    mac_address: Annotated[
        str,
        Field(description="Device MAC address in format AA:BB:CC:DD:EE:FF (from unifi_list_devices)"),
    ],
) -> Dict[str, Any]:
    """Implementation for getting device details."""
    try:
        device = await device_manager.get_device_details(mac_address)
        return {
            "success": True,
            "site": device_manager._connection.site,
            "device": device.raw if hasattr(device, "raw") else device,
        }
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

VALID_RADIOS = {"na", "ng", "6e", "wifi6e"}
VALID_TX_POWER_MODES = {"auto", "high", "medium", "low", "custom"}
VALID_HT_VALUES = {"20", "40", "80", "160", "320"}


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
    if radio not in VALID_RADIOS and not radio.startswith("wifi"):
        return {
            "success": False,
            "error": (
                f"Invalid radio '{radio}'. Must be a band code ({', '.join(sorted(VALID_RADIOS))}) "
                "or an internal radio name (e.g. 'wifi0', 'wifi1')."
            ),
        }

    if tx_power_mode is not None and tx_power_mode not in VALID_TX_POWER_MODES:
        return {
            "success": False,
            "error": f"Invalid tx_power_mode '{tx_power_mode}'. Must be one of: {', '.join(sorted(VALID_TX_POWER_MODES))}",
        }

    if tx_power is not None and tx_power_mode != "custom":
        return {"success": False, "error": "tx_power can only be set when tx_power_mode is 'custom'."}

    if ht is not None and ht not in VALID_HT_VALUES:
        return {"success": False, "error": f"Invalid ht '{ht}'. Must be one of: {', '.join(sorted(VALID_HT_VALUES))}"}

    if min_rssi is not None and min_rssi_enabled is not True:
        return {"success": False, "error": "min_rssi can only be set when min_rssi_enabled is true."}

    if sens_level is not None and sens_level_enabled is not True:
        return {"success": False, "error": "sens_level can only be set when sens_level_enabled is true."}

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

    if not updates:
        return {"success": False, "error": "No radio settings provided to update."}

    # Validate against schema (type checks, bounds, no unknown keys)
    is_valid, error_msg, validated_data = UniFiValidatorRegistry.validate("device_radio_update", updates)
    if not is_valid:
        logger.warning("Invalid radio update data for %s: %s", mac_address, error_msg)
        return {"success": False, "error": f"Invalid radio update data: {error_msg}"}

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
        "Returns BSSID, SSID, channel, RSSI, band, and which of your APs detected each one. "
        "Useful for RF environment analysis and interference troubleshooting. "
        "WARNING: This can return hundreds of APs. Use channel and/or min_signal filters "
        "to reduce the result set."
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
) -> Dict[str, Any]:
    """List neighboring/rogue APs detected by your access points."""
    try:
        rogue_aps = await device_manager.list_rogue_aps(within_hours)

        # Apply client-side filters
        if channel is not None:
            rogue_aps = [ap for ap in rogue_aps if ap.get("channel") == channel]
        if min_signal is not None:
            rogue_aps = [ap for ap in rogue_aps if ap.get("signal", -100) >= min_signal]

        return {
            "success": True,
            "site": device_manager._connection.site,
            "within_hours": within_hours,
            "filters": {"channel": channel, "min_signal": min_signal},
            "count": len(rogue_aps),
            "rogue_aps": rogue_aps,
        }
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
