"""
Switch management tools for UniFi Network MCP server.

Provides access to switch port profiles (CRUD), port assignments,
live port statistics, LLDP neighbor discovery, switch capabilities,
port mirroring, link aggregation, PoE control, STP configuration,
and device management commands.
"""

import json
import logging
from typing import Annotated, Any, Dict, List

from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from unifi_core.confirmation import create_preview, update_preview
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.models._actions import (
    ConfigurePortAggregationInput,
    ConfigurePortMirrorInput,
    SetJumboFramesInput,
    SetSwitchPortProfileInput,
)
from unifi_core.network.models.switch import (
    from_controller as pp_from_controller,
)
from unifi_core.network.models.switch import (
    to_controller_update as pp_to_update,
)
from unifi_network_mcp.runtime import server, switch_manager

logger = logging.getLogger(__name__)


# ---- Port Profile CRUD ----


@server.tool(
    name="unifi_list_port_profiles",
    description="List all port profiles (port configurations) on the controller. "
    "Port profiles define VLAN assignment, port isolation, PoE mode, STP, 802.1X, "
    "and storm control settings. Profiles are assigned to switch ports via port overrides.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_port_profiles() -> Dict[str, Any]:
    """Lists all port profiles."""
    try:
        profiles = await switch_manager.get_port_profiles()
        formatted = [pp_from_controller(p).model_dump(exclude_none=True) for p in profiles]
        return {
            "success": True,
            "site": switch_manager._connection.site,
            "count": len(formatted),
            "profiles": formatted,
        }
    except Exception as e:
        logger.error("Error listing port profiles: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list port profiles: {e}"}


@server.tool(
    name="unifi_get_port_profile_details",
    description="Get detailed configuration for a specific port profile by ID. "
    "Returns full profile including VLAN, isolation, PoE, STP, 802.1X, storm control, and QoS settings.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_port_profile_details(
    profile_id: Annotated[str, Field(description="The unique identifier (_id) of the port profile")],
) -> Dict[str, Any]:
    """Gets a specific port profile."""
    try:
        if not profile_id:
            return {"success": False, "error": "profile_id is required"}

        profile = await switch_manager.get_port_profile_by_id(profile_id)
        return {
            "success": True,
            "profile_id": profile_id,
            "details": json.loads(json.dumps(profile, default=str)),
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting port profile %s: %s", profile_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get port profile {profile_id}: {e}"}


@server.tool(
    name="unifi_create_port_profile",
    description="Create a new port profile. forward values: 'native' (access port), 'all' (trunk), "
    "'customize' (selective trunk), 'disabled'. Requires confirmation.",
    permission_category="switch",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_port_profile(
    name: Annotated[str, Field(description="Profile name")],
    forward: Annotated[
        str, Field(description="Forward mode: 'native' (access), 'all' (trunk), 'customize', or 'disabled'")
    ],
    native_networkconf_id: Annotated[str, Field(description="Network/VLAN ID for native (untagged) traffic")] = "",
    voice_networkconf_id: Annotated[str, Field(description="Network/VLAN ID for voice traffic")] = "",
    isolation: Annotated[bool, Field(description="Enable port isolation (block inter-client traffic)")] = False,
    poe_mode: Annotated[str, Field(description="PoE mode: 'auto' or 'off'")] = "auto",
    stp_port_mode: Annotated[bool, Field(description="Enable STP on this port")] = True,
    dot1x_ctrl: Annotated[
        str, Field(description="802.1X control: 'force_authorized', 'auto', 'force_unauthorized'")
    ] = "",
    confirm: Annotated[
        bool,
        Field(description="When true, creates the profile. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Creates a new port profile."""
    profile_data: Dict[str, Any] = {"name": name, "forward": forward}
    if native_networkconf_id:
        profile_data["native_networkconf_id"] = native_networkconf_id
    if voice_networkconf_id:
        profile_data["voice_networkconf_id"] = voice_networkconf_id
    if isolation:
        profile_data["isolation"] = isolation
    if poe_mode != "auto":
        profile_data["poe_mode"] = poe_mode
    if not stp_port_mode:
        profile_data["stp_port_mode"] = stp_port_mode
    if dot1x_ctrl:
        profile_data["dot1x_ctrl"] = dot1x_ctrl

    if not confirm:
        return create_preview(
            resource_type="port_profile",
            resource_data=profile_data,
            resource_name=name,
        )

    try:
        result = await switch_manager.create_port_profile(profile_data)
        if result:
            return {
                "success": True,
                "message": f"Port profile '{name}' created successfully.",
                "profile": json.loads(json.dumps(result, default=str)),
            }
        return {"success": False, "error": f"Failed to create port profile '{name}'."}
    except Exception as e:
        logger.error("Error creating port profile: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to create port profile: {e}"}


@server.tool(
    name="unifi_update_port_profile",
    description="Update an existing port profile. Pass only the fields you want to change — "
    "current values are automatically preserved. "
    "Note: system profiles with attr_no_edit=true cannot be modified. Requires confirmation.",
    permission_category="switch",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_port_profile(
    profile_id: Annotated[str, Field(description="The ID of the profile to update")],
    profile_data: Annotated[
        dict,
        Field(
            description="Dictionary of fields to update. Pass only the fields you want to change — "
            "current values are automatically preserved. "
            "Allowed keys: name, forward ('all'/'native'/'customize'/'disabled'), "
            "native_networkconf_id, voice_networkconf_id, isolation (bool), "
            "poe_mode ('auto'/'off'/'pasv24'/'passthrough'), stp_port_mode (bool), "
            "dot1x_ctrl ('force_authorized'/'auto'/'force_unauthorized'/'mac_based'/'multi_host')"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, updates the profile. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Updates an existing port profile with partial data."""
    if not profile_id:
        return {"success": False, "error": "profile_id is required"}
    if not profile_data:
        return {"success": False, "error": "profile_data cannot be empty"}

    validated_data = pp_to_update(profile_data)
    if not validated_data:
        return {"success": False, "error": "No valid mutable fields provided for update."}

    if not confirm:
        return update_preview(
            resource_type="port_profile",
            resource_id=profile_id,
            resource_name=profile_id,
            current_state={},
            updates=validated_data,
        )

    try:
        merged = await switch_manager.update_port_profile(profile_id, validated_data)
        return {
            "success": True,
            "message": f"Port profile '{merged.get('name', profile_id)}' updated successfully.",
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating port profile %s: %s", profile_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update port profile '{profile_id}': {e}"}


@server.tool(
    name="unifi_delete_port_profile",
    description="Delete a port profile. System profiles with attr_no_delete=true cannot be deleted. "
    "WARNING: Switch ports using this profile will revert to defaults. Requires confirmation.",
    permission_category="switch",
    permission_action="delete",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def delete_port_profile(
    profile_id: Annotated[str, Field(description="The ID of the profile to delete")],
    confirm: Annotated[
        bool,
        Field(description="When true, deletes the profile. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Deletes a port profile."""
    if not confirm:
        return create_preview(
            resource_type="port_profile",
            resource_data={"profile_id": profile_id},
            resource_name=profile_id,
            warnings=["Switch ports using this profile will revert to defaults."],
        )

    try:
        success = await switch_manager.delete_port_profile(profile_id)
        if success:
            return {"success": True, "message": f"Port profile '{profile_id}' deleted successfully."}
        return {"success": False, "error": f"Failed to delete port profile '{profile_id}'."}
    except Exception as e:
        logger.error("Error deleting port profile %s: %s", profile_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to delete port profile '{profile_id}': {e}"}


# ---- Switch Port Read Operations ----


@server.tool(
    name="unifi_get_switch_ports",
    description="Get port assignments for a specific switch. Shows which port profile is assigned "
    "to each port, port names, and PoE mode. Use unifi_list_devices to find switch MAC addresses.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_switch_ports(
    device_mac: Annotated[str, Field(description="MAC address of the switch (from unifi_list_devices)")],
) -> Dict[str, Any]:
    """Gets port override assignments for a switch."""
    try:
        if not device_mac:
            return {"success": False, "error": "device_mac is required"}

        result = await switch_manager.get_switch_ports(device_mac)
        if not result:
            return {"success": False, "error": f"Switch '{device_mac}' not found or has no port data."}

        return {
            "success": True,
            "device_mac": device_mac,
            "details": json.loads(json.dumps(result, default=str)),
        }
    except Exception as e:
        logger.error("Error getting switch ports for %s: %s", device_mac, e, exc_info=True)
        return {"success": False, "error": f"Failed to get switch ports for {device_mac}: {e}"}


@server.tool(
    name="unifi_get_port_stats",
    description="Get live port statistics for a switch. Returns per-port data including "
    "link speed, duplex, PoE draw (voltage/current/power), error counters, MAC table count, "
    "bytes per second, and enabled state. Use unifi_list_devices to find switch MAC addresses.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_port_stats(
    device_mac: Annotated[str, Field(description="MAC address of the switch (from unifi_list_devices)")],
) -> Dict[str, Any]:
    """Gets live port table statistics for a switch."""
    try:
        if not device_mac:
            return {"success": False, "error": "device_mac is required"}

        result = await switch_manager.get_port_stats(device_mac)
        if not result:
            return {"success": False, "error": f"Switch '{device_mac}' not found or has no port data."}

        return {
            "success": True,
            "device_mac": device_mac,
            "details": json.loads(json.dumps(result, default=str)),
        }
    except Exception as e:
        logger.error("Error getting port stats for %s: %s", device_mac, e, exc_info=True)
        return {"success": False, "error": f"Failed to get port stats for {device_mac}: {e}"}


@server.tool(
    name="unifi_get_lldp_neighbors",
    description="Get LLDP neighbor discovery table for a switch. Shows what devices are "
    "connected to each port by their LLDP-advertised chassis ID and descriptions. "
    "Use unifi_list_devices to find switch MAC addresses.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_lldp_neighbors(
    device_mac: Annotated[str, Field(description="MAC address of the switch (from unifi_list_devices)")],
) -> Dict[str, Any]:
    """Gets LLDP neighbor table for a switch."""
    try:
        if not device_mac:
            return {"success": False, "error": "device_mac is required"}

        result = await switch_manager.get_lldp_neighbors(device_mac)
        if not result:
            return {"success": False, "error": f"Switch '{device_mac}' not found or has no LLDP data."}

        return {
            "success": True,
            "device_mac": device_mac,
            "details": json.loads(json.dumps(result, default=str)),
        }
    except Exception as e:
        logger.error("Error getting LLDP neighbors for %s: %s", device_mac, e, exc_info=True)
        return {"success": False, "error": f"Failed to get LLDP neighbors for {device_mac}: {e}"}


@server.tool(
    name="unifi_get_switch_capabilities",
    description="Get switch hardware capabilities including max ACL rules, max VLANs, "
    "max aggregation sessions, max mirror sessions, STP config, and jumbo frame status. "
    "Use unifi_list_devices to find switch MAC addresses.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_switch_capabilities(
    device_mac: Annotated[str, Field(description="MAC address of the switch (from unifi_list_devices)")],
) -> Dict[str, Any]:
    """Gets switch hardware capabilities."""
    try:
        if not device_mac:
            return {"success": False, "error": "device_mac is required"}

        result = await switch_manager.get_switch_capabilities(device_mac)
        if not result:
            return {"success": False, "error": f"Switch '{device_mac}' not found or has no capability data."}

        return {
            "success": True,
            "device_mac": device_mac,
            "details": json.loads(json.dumps(result, default=str)),
        }
    except Exception as e:
        logger.error("Error getting switch capabilities for %s: %s", device_mac, e, exc_info=True)
        return {"success": False, "error": f"Failed to get switch capabilities for {device_mac}: {e}"}


# ---- Switch Port Write Operations ----


@server.tool(
    name="unifi_set_switch_port_profile",
    description="Assign a port profile to a specific switch port. "
    "IMPORTANT: This sends ALL port overrides as a full replacement. Fetch current overrides "
    "with unifi_get_switch_ports first, modify the target port, and send the complete array. "
    "Missing ports revert to defaults. Requires confirmation.",
    permission_category="switch",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def set_switch_port_profile(
    device_mac: Annotated[str, Field(description="MAC address of the switch")],
    port_overrides: Annotated[
        List[Dict],
        Field(
            description="Complete list of port overrides. Each entry needs at minimum: "
            "port_idx (int, 1-based), portconf_id (str, profile ID). "
            "Optional: name, poe_mode, op_mode ('switch'/'mirror'/'aggregate')"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the changes. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Sets port overrides for a switch."""
    try:
        SetSwitchPortProfileInput(device_mac=device_mac, port_overrides=port_overrides)
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    if not confirm:
        return create_preview(
            resource_type="switch_port_assignment",
            resource_data={"device_mac": device_mac, "port_overrides": port_overrides},
            resource_name=device_mac,
        )

    try:
        success = await switch_manager.set_port_overrides(device_mac, port_overrides)
        if success:
            return {"success": True, "message": f"Port overrides updated for switch '{device_mac}'."}
        return {"success": False, "error": f"Failed to set port overrides for '{device_mac}'."}
    except Exception as e:
        logger.error("Error setting port overrides for %s: %s", device_mac, e, exc_info=True)
        return {"success": False, "error": f"Failed to set port overrides for {device_mac}: {e}"}


@server.tool(
    name="unifi_power_cycle_port",
    description="Power cycle PoE on a specific switch port. This briefly cuts power to the "
    "connected PoE device, causing it to reboot. Requires confirmation.",
    permission_category="switch",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def power_cycle_port(
    device_mac: Annotated[str, Field(description="MAC address of the switch")],
    port_idx: Annotated[int, Field(description="1-based port number to power cycle")],
    confirm: Annotated[
        bool,
        Field(description="When true, power cycles the port. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Power cycles PoE on a specific port."""
    if not confirm:
        return create_preview(
            resource_type="poe_power_cycle",
            resource_data={"device_mac": device_mac, "port_idx": port_idx},
            resource_name=f"{device_mac}:port{port_idx}",
            warnings=[f"This will briefly cut PoE power to port {port_idx}, rebooting any connected PoE device."],
        )

    try:
        success = await switch_manager.power_cycle_port(device_mac, port_idx)
        if success:
            return {"success": True, "message": f"Power cycled port {port_idx} on switch '{device_mac}'."}
        return {"success": False, "error": f"Failed to power cycle port {port_idx} on '{device_mac}'."}
    except Exception as e:
        logger.error("Error power cycling port %s on %s: %s", port_idx, device_mac, e, exc_info=True)
        return {"success": False, "error": f"Failed to power cycle port {port_idx} on {device_mac}: {e}"}


# ---- Advanced Switch Configuration ----


@server.tool(
    name="unifi_configure_port_mirror",
    description="Configure port mirroring on a switch. Mirrors traffic from one port to a "
    "destination port for packet capture/analysis. Most switches support only 1 mirror session. "
    "Fetch current overrides with unifi_get_switch_ports, set op_mode='mirror' and mirror_port_idx "
    "on the source port, then send all overrides. Requires confirmation.",
    permission_category="switch",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def configure_port_mirror(
    device_mac: Annotated[str, Field(description="MAC address of the switch")],
    port_overrides: Annotated[
        List[Dict],
        Field(
            description="Complete port overrides array. The source port must have "
            "op_mode='mirror' and mirror_port_idx='<destination_port_idx>'"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the mirror config. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Configures port mirroring."""
    try:
        ConfigurePortMirrorInput(device_mac=device_mac, port_overrides=port_overrides)
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    if not confirm:
        return create_preview(
            resource_type="port_mirror",
            resource_data={"device_mac": device_mac, "port_overrides": port_overrides},
            resource_name=device_mac,
        )

    try:
        success = await switch_manager.set_port_overrides(device_mac, port_overrides)
        if success:
            return {"success": True, "message": f"Port mirror configured on switch '{device_mac}'."}
        return {"success": False, "error": f"Failed to configure port mirror on '{device_mac}'."}
    except Exception as e:
        logger.error("Error configuring port mirror on %s: %s", device_mac, e, exc_info=True)
        return {"success": False, "error": f"Failed to configure port mirror on {device_mac}: {e}"}


@server.tool(
    name="unifi_configure_port_aggregation",
    description="Configure link aggregation (LACP/LAG) on a switch. Bonds consecutive ports "
    "for increased bandwidth. Most switches support up to 8 aggregate sessions. "
    "Ports must be sequential and same speed. "
    "The master port override must include: op_mode='aggregate', aggregate_members=[list of port indices], "
    "and lag_idx=<group number starting at 1>. Member ports (all except the master) must be REMOVED "
    "from the overrides array — the controller auto-manages them. Requires confirmation.",
    permission_category="switch",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def configure_port_aggregation(
    device_mac: Annotated[str, Field(description="MAC address of the switch")],
    port_overrides: Annotated[
        List[Dict],
        Field(
            description="Complete port overrides array. The master port must have "
            "op_mode='aggregate', aggregate_members=[port_idx, port_idx+1, ...], and lag_idx=<int>. "
            "Remove member ports from the array — the controller claims them automatically"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the LAG config. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Configures link aggregation."""
    try:
        ConfigurePortAggregationInput(device_mac=device_mac, port_overrides=port_overrides)
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    if not confirm:
        return create_preview(
            resource_type="port_aggregation",
            resource_data={"device_mac": device_mac, "port_overrides": port_overrides},
            resource_name=device_mac,
        )

    try:
        success = await switch_manager.set_port_overrides(device_mac, port_overrides)
        if success:
            return {"success": True, "message": f"Link aggregation configured on switch '{device_mac}'."}
        return {"success": False, "error": f"Failed to configure aggregation on '{device_mac}'."}
    except Exception as e:
        logger.error("Error configuring port aggregation on %s: %s", device_mac, e, exc_info=True)
        return {"success": False, "error": f"Failed to configure port aggregation on {device_mac}: {e}"}


@server.tool(
    name="unifi_update_switch_stp",
    description="Update STP (Spanning Tree Protocol) configuration for a switch. "
    "stp_priority valid values: 4096, 8192, 12288, ..., 61440 (default: 32768). "
    "stp_version: 'stp' or 'rstp' (default). Requires confirmation.",
    permission_category="switch",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_switch_stp(
    device_mac: Annotated[str, Field(description="MAC address of the switch")],
    stp_priority: Annotated[
        int,
        Field(description="STP bridge priority (4096-61440 in steps of 4096, default 32768)"),
    ] = 32768,
    stp_version: Annotated[
        str,
        Field(description="STP version: 'stp' or 'rstp' (default)"),
    ] = "rstp",
    confirm: Annotated[
        bool,
        Field(description="When true, applies the STP config. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Updates STP configuration for a switch."""
    config = {"stp_priority": str(stp_priority), "stp_version": stp_version}

    if not confirm:
        return create_preview(
            resource_type="switch_stp",
            resource_data={"device_mac": device_mac, **config},
            resource_name=device_mac,
        )

    try:
        success = await switch_manager.update_device_config(device_mac, config)
        if success:
            return {"success": True, "message": f"STP config updated on switch '{device_mac}'."}
        return {"success": False, "error": f"Failed to update STP config on '{device_mac}'."}
    except Exception as e:
        logger.error("Error updating STP on %s: %s", device_mac, e, exc_info=True)
        return {"success": False, "error": f"Failed to update STP on {device_mac}: {e}"}


@server.tool(
    name="unifi_set_jumbo_frames",
    description="Enable or disable jumbo frames on a switch. "
    "Note: the UniFi controller requires jumbo frames to be enabled via the UI at least once "
    "before the API can toggle it. If you get JumboFrameChangeNotAllowed, enable it in the UI first. "
    "Requires confirmation.",
    permission_category="switch",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def set_jumbo_frames(
    device_mac: Annotated[str, Field(description="MAC address of the switch")],
    enabled: Annotated[bool, Field(description="True to enable jumbo frames, False to disable")],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the change. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Enables or disables jumbo frames on a switch."""
    try:
        SetJumboFramesInput(device_mac=device_mac, enabled=enabled)
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    if not confirm:
        return create_preview(
            resource_type="jumbo_frames",
            resource_data={"device_mac": device_mac, "jumboframe_enabled": enabled},
            resource_name=device_mac,
        )

    try:
        success = await switch_manager.update_device_config(device_mac, {"jumboframe_enabled": enabled})
        if success:
            state = "enabled" if enabled else "disabled"
            return {"success": True, "message": f"Jumbo frames {state} on switch '{device_mac}'."}
        return {"success": False, "error": f"Failed to set jumbo frames on '{device_mac}'."}
    except Exception as e:
        logger.error("Error setting jumbo frames on %s: %s", device_mac, e, exc_info=True)
        return {"success": False, "error": f"Failed to set jumbo frames on {device_mac}: {e}"}
