"""
Unifi Network MCP network tools.

This module provides MCP tools to interact with a Unifi Network Controller's network functions,
including managing LAN networks and WLANs.
"""

import json
import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.confirmation import create_preview, toggle_preview, update_preview
from unifi_core.network.models.ap_group import (
    from_controller as ap_group_from_controller,
)
from unifi_core.network.models.ap_group import (
    to_controller_create as ap_group_to_create,
)
from unifi_core.network.models.ap_group import (
    to_controller_update as ap_group_to_update,
)
from unifi_core.network.models.networks import (
    from_controller as network_from_controller,
)
from unifi_core.network.models.networks import (
    to_controller_update as network_to_update,
)
from unifi_core.network.models.wlans import (
    MUTABLE_FIELDS as WLAN_MUTABLE_FIELDS,
)
from unifi_core.network.models.wlans import (
    to_controller_create as wlan_to_create,
)
from unifi_core.network.models.wlans import (
    to_controller_update as wlan_to_update,
)
from unifi_network_mcp.runtime import network_manager, server

logger = logging.getLogger(__name__)


@server.tool(
    name="unifi_list_networks",
    description=(
        "Returns all configured networks (LAN, WAN, VLAN-only) with name, purpose, "
        "IP subnet, VLAN ID, DHCP settings, and enabled state. "
        "Use to understand network topology and VLAN layout. "
        "For a single network's full config, use unifi_get_network_details. "
        "For wireless SSIDs, use unifi_list_wlans."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_networks() -> Dict[str, Any]:
    """Lists all networks configured on the UniFi Network controller for the current site using the V1 API structure.

    Returns:
        A dictionary containing:
        - success (bool): Indicates if the operation was successful.
        - site (str): The identifier of the UniFi site queried.
        - count (int): The number of networks found.
        - networks (List[Dict]): A list of networks, each containing summary info based on the V1 API response, such as:
            - _id (str): The unique identifier of the network.
            - name (str): The user-defined name of the network.
            - enabled (bool): Whether the network is active.
            - purpose (str): The purpose of the network (e.g., 'corporate', 'guest', 'vlan-only', 'wan').
            - ip_subnet (str, optional): The IP subnet in CIDR notation (if applicable).
            - vlan_enabled (bool): Whether VLAN tagging is enabled.
            - vlan (int, optional): The VLAN ID (if `vlan_enabled` is true).
            - dhcpd_enabled (bool, optional): Whether DHCP server is enabled for this network.
            - dhcpd_start (str, optional): Start IP of the DHCP range.
            - dhcpd_stop (str, optional): End IP of the DHCP range.
            - site_id (str): ID of the site the network belongs to.
            # Note: Field names and availability might differ slightly based on controller version using V1 API.
        - error (str, optional): An error message if the operation failed.

    Example response (success):
    {
        "success": True,
        "site": "default",
        "count": 2,
        "networks": [
            {
                "_id": "60a8b3c4d5e6f7a8b9c0d1e2", # Example ID
                "name": "LAN",
                "enabled": True,
                "purpose": "corporate",
                "ip_subnet": "192.168.1.0/24",
                "vlan_enabled": False,
                "vlan": null,
                "dhcpd_enabled": True,
                "dhcpd_start": "192.168.1.100",
                "dhcpd_stop": "192.168.1.200",
                "site_id": "..."
            },
            {
                "_id": "60a8b3c4d5e6f7a8b9c0d1e3", # Example ID
                "name": "IoT VLAN",
                "enabled": True,
                "purpose": "corporate", # Note: Purpose might map differently in V1
                "ip_subnet": "10.10.20.0/24",
                "vlan_enabled": True,
                "vlan": 20,
                "dhcpd_enabled": True,
                "dhcpd_start": "10.10.20.100",
                "dhcpd_stop": "10.10.20.200",
                "site_id": "..."
            }
        ]
    }
    """
    try:
        networks_data = await network_manager.get_networks()
        formatted = [network_from_controller(n).model_dump(exclude_none=True) for n in networks_data]
        return {
            "success": True,
            "site": network_manager._connection.site,
            "count": len(formatted),
            "networks": formatted,
        }
    except Exception as e:
        logger.error("Error listing networks in tool: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list networks: {e}"}


@server.tool(
    name="unifi_get_network_details",
    description="Get details for a specific network by ID.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_network_details(
    network_id: Annotated[str, Field(description="Unique identifier (_id) of the network (from unifi_list_networks)")],
) -> Dict[str, Any]:
    """Gets the detailed configuration of a specific network by its ID.

    Args:
        network_id (str): The unique identifier (_id) of the network.

    Returns:
        A dictionary containing:
        - success (bool): Indicates if the operation was successful.
        - site (str): The identifier of the UniFi site queried.
        - network_id (str): The ID of the network requested.
        - details (Dict[str, Any]): A dictionary containing the raw configuration details
          of the network as returned by the UniFi controller.
        - error (str, optional): An error message if the operation failed (e.g., network not found).

    Example response (success):
    {
        "success": True,
        "site": "default",
        "network_id": "60a8b3c4d5e6f7a8b9c0d1e3",
        "details": {
            "_id": "60a8b3c4d5e6f7a8b9c0d1e3",
            "name": "IoT VLAN",
            "enabled": True,
            "purpose": "corporate",
            "ip_subnet": "10.10.20.0/24",
            "vlan_enabled": True,
            "vlan": 20,
            "dhcpd_enabled": True,
            "dhcpd_start": "10.10.20.100",
            "dhcpd_stop": "10.10.20.200",
            "site_id": "...",
            # ... other fields
        }
    }
    """
    try:
        if not network_id:
            return {"success": False, "error": "network_id is required"}
        # Assuming manager get_network_details returns the raw dict or None
        network = await network_manager.get_network_details(network_id)
        if network:
            # Ensure serializable
            return {
                "success": True,
                "site": network_manager._connection.site,
                "network_id": network_id,
                "details": json.loads(json.dumps(network, default=str)),
            }
        else:
            return {
                "success": False,
                "error": f"Network with ID '{network_id}' not found.",
            }
    except Exception as e:
        logger.error("Error getting network details for %s: %s", network_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get network details for {network_id}: {e}"}


@server.tool(
    name="unifi_update_network",
    description="Update specific fields of an existing network (LAN/VLAN). "
    "Pass only the fields you want to change — current values are automatically preserved. "
    "Basic: name, purpose ('corporate'/'guest'/'vlan-only'), vlan_enabled (bool), vlan (str), "
    "ip_subnet (CIDR), enabled (bool), network_isolation_enabled (bool, corporate only), "
    "internet_access_enabled (bool), upnp_lan_enabled (bool). "
    "DHCP: dhcpd_enabled (bool), dhcpd_start (IP), dhcpd_stop (IP), dhcpd_leasetime (int seconds), "
    "dhcpd_gateway (IP), dhcpd_gateway_enabled (bool), dhcp_relay_enabled (bool), "
    "dhcpd_conflict_checking (bool), dhcpguard_enabled (bool, requires dhcpd_ip_1), dhcpd_ip_1 (IP, trusted DHCP server for guard), dhcpd_boot_enabled (bool), dhcpd_boot_server (IP), dhcpd_boot_filename (str), dhcpd_tftp_server (str, DHCP opt 150). "
    "DHCP options: dhcpd_dns_1 (IP), dhcpd_dns_2 (IP), dhcpd_dns_enabled (bool), "
    "dhcpd_ntp_1 (IPv4), dhcpd_ntp_2 (IPv4), dhcpd_ntp_enabled (bool), "
    "dhcpd_wins_1 (IP), dhcpd_wins_2 (IP), dhcpd_wins_enabled (bool), dhcpd_unifi_controller (IP). "
    "DNS: domain_name (str). "
    "Multicast: igmp_snooping (bool), igmp_querier_switches (list of {switch_mac, querier_address}), "
    "igmp_flood_unknown_multicast (bool), mdns_enabled (bool). "
    "Requires confirmation.",
    permission_category="networks",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_network(
    network_id: Annotated[
        str, Field(description="Unique identifier (_id) of the network to update (from unifi_list_networks)")
    ],
    update_data: Annotated[
        Dict[str, Any],
        Field(description="Dictionary of fields to update. See tool description for all supported fields."),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the update. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Updates specific fields of an existing network.

    Allows modifying properties like name, purpose, VLAN settings, DHCP settings, etc.
    Only provided fields are updated. Requires confirmation.

    Args:
        network_id (str): The unique identifier (_id) of the network to update.
        update_data (Dict[str, Any]): Dictionary of fields to update.
            Allowed fields (all optional):
            - name (string): New network name.
            - purpose (string): New purpose ("corporate", "guest", "vlan-only").
            - vlan_enabled (boolean): Enable/disable VLAN tagging.
            - vlan (integer): New VLAN ID (1-4094).
            - ip_subnet (string): New IP subnet (CIDR format).
            - enabled (boolean): Enable/disable the entire network.
            - network_isolation_enabled (boolean): Enable network isolation (corporate networks only).
            - internet_access_enabled (boolean): Allow this network to access the internet.
            - upnp_lan_enabled (boolean): Enable UPnP on this network.
            - dhcpd_enabled (boolean): Enable the DHCP server.
            - dhcpd_start (string): DHCP range start IP.
            - dhcpd_stop (string): DHCP range end IP.
            - dhcpd_leasetime (integer): DHCP lease time in seconds.
            - dhcpd_gateway (string): Custom DHCP gateway IP.
            - dhcpd_gateway_enabled (boolean): Use custom gateway instead of default.
            - dhcpd_dns_1 (string): Primary DNS server for DHCP clients.
            - dhcpd_dns_2 (string): Secondary DNS server for DHCP clients.
            - dhcpd_dns_enabled (boolean): Enable custom DNS servers in DHCP.
            - dhcpd_ntp_1 (string): Primary NTP server IPv4 (controller rejects hostnames).
            - dhcpd_ntp_2 (string): Secondary NTP server IPv4 (controller rejects hostnames).
            - dhcpd_ntp_enabled (boolean): Enable NTP option in DHCP.
            - dhcpd_wins_1 (string): Primary WINS server for DHCP clients.
            - dhcpd_wins_2 (string): Secondary WINS server for DHCP clients.
            - dhcpd_wins_enabled (boolean): Enable WINS option in DHCP.
            - dhcpd_unifi_controller (string): UniFi controller IP for DHCP option 43.
            - dhcpd_tftp_server (string): TFTP server for DHCP option 150 (Cisco TFTP, independent of PXE).
            - dhcpd_boot_server (string): PXE boot server IP (BOOTP siaddr).
            - dhcpd_boot_filename (string): PXE boot filename (option 67, required if dhcpd_boot_enabled).
            - dhcpd_boot_enabled (boolean): Enable PXE boot options (requires dhcpd_boot_server + dhcpd_boot_filename).
            - dhcpd_conflict_checking (boolean): Ping before assigning DHCP IP.
            - dhcp_relay_enabled (boolean): Use DHCP relay instead of local server.
            - dhcpguard_enabled (boolean): Block rogue DHCP servers. Requires dhcpd_ip_1 set in same update.
            - dhcpd_ip_1 (string): Trusted DHCP server IP for DHCP guard (typically the gateway).
            - domain_name (string): DNS domain for the network.
            - igmp_snooping (boolean): Enable IGMP snooping.
            - igmp_querier_switches (list): IGMP querier assignment.
            - igmp_flood_unknown_multicast (boolean): Flood unknown multicast.
            - mdns_enabled (boolean): Enable mDNS reflection.
        confirm (bool): Must be set to `True` to execute. Defaults to `False`.

    Important Constraints:
        - Network isolation (network_isolation_enabled) is ONLY supported on networks with purpose="corporate".
        - Attempting to enable isolation on "guest" or other network types will fail with an API error.
        - To isolate a guest network: (1) Change its purpose from "guest" to "corporate", then (2) enable network_isolation_enabled.

    Returns:
        Dict: Success status, ID, updated fields, details, or error message.
        Example (success):
        {
            "success": True,
            "network_id": "60a8b3c4d5e6f7a8b9c0d1e3",
            "updated_fields": ["name", "enabled"],
            "details": { ... updated network details ... }
        }
    """
    logger.info("unifi_update_network tool called (network_id=%s, confirm=%s)", network_id, confirm)
    if not network_id:
        return {"success": False, "error": "network_id is required"}
    if not update_data:
        return {"success": False, "error": "update_data cannot be empty"}

    # Translate to controller-safe mutable fields
    validated_data = network_to_update(update_data)
    if not validated_data:
        logger.warning("Network update data for ID %s is empty after filtering.", network_id)
        return {
            "success": False,
            "error": "No valid mutable fields provided for update.",
        }

    # Fetch current state for preview
    current = await network_manager.get_network_details(network_id)
    if not current:
        return {"success": False, "error": "Network not found"}

    if not confirm:
        return update_preview(
            resource_type="network",
            resource_id=network_id,
            resource_name=current.get("name"),
            current_state=current,
            updates=validated_data,
        )

    # Basic cross-field validation (more complex logic might need Pydantic models)
    if "vlan_enabled" in validated_data and validated_data["vlan_enabled"] and "vlan" not in validated_data:
        # Check if existing network already has VLAN ID if only enabling
        pass  # Let manager handle fetching existing state for merge
    if "vlan" in validated_data and (int(validated_data["vlan"]) < 1 or int(validated_data["vlan"]) > 4094):
        return {"success": False, "error": "'vlan' must be between 1 and 4094."}

    updated_fields_list = list(validated_data.keys())
    logger.info("Attempting to update network '%s' with fields: %s", network_id, ", ".join(updated_fields_list))
    try:
        success, error_detail = await network_manager.update_network(network_id, validated_data)

        if success:
            updated_network = await network_manager.get_network_details(network_id)
            logger.info("Successfully updated network (%s)", network_id)
            return {
                "success": True,
                "network_id": network_id,
                "updated_fields": updated_fields_list,
                "details": json.loads(json.dumps(updated_network, default=str)),
            }
        else:
            logger.error("Failed to update network (%s): %s", network_id, error_detail)
            network_after_update = await network_manager.get_network_details(network_id)
            return {
                "success": False,
                "network_id": network_id,
                "error": f"Failed to update network ({network_id}): {error_detail}",
                "details_after_attempt": json.loads(json.dumps(network_after_update, default=str)),
            }

    except Exception as e:
        logger.error("Error updating network %s: %s", network_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update network {network_id}: {e}"}


@server.tool(
    name="unifi_create_network",
    description="Create a new network (LAN/VLAN) with schema validation. Requires confirmation.",
    permission_category="networks",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_network(
    network_data: Annotated[
        Dict[str, Any],
        Field(
            description="Network configuration dict. Required: name (str), purpose (str: 'corporate', 'guest', 'wan', 'vlan-only', 'vpn-client', 'vpn-server'). Required if purpose != 'vlan-only': ip_subnet (CIDR, e.g. '192.168.1.0/24'). Required if purpose == 'vlan-only': vlan (int 1-4094). Optional: vlan_enabled, vlan, dhcpd_enabled, dhcpd_start, dhcpd_stop, dhcpd_leasetime, domain_name, enabled, network_isolation_enabled, upnp_lan_enabled. See update_network for the full list of supported DHCP/DNS fields."
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, creates the network. When false (default), validates and returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Create a new network (LAN/VLAN) with comprehensive validation.

    Args:
        network_data (Dict[str, Any]): Network configuration data
        confirm (bool): Must be set to `True` to execute. Defaults to `False`.

    Required parameters in network_data:
    - name (string): Network name
    - purpose (string): Network purpose/type ("corporate", "guest", "wan", "vlan-only", "vpn-client", "vpn-server")

    If purpose is not "vlan-only":
    - ip_subnet (string): IP subnet in CIDR notation (e.g., "192.168.1.0/24") is required

    If purpose is "vlan-only":
    - vlan (integer): VLAN ID (1-4094) is required

    If purpose is not "vlan-only" and dhcpd_enabled is true:
    - dhcpd_start (string): Start of DHCP range is required
    - dhcpd_stop (string): End of DHCP range is required

    Optional parameters:
    - vlan_enabled (boolean): Whether VLAN is enabled (default: false)
    - vlan (integer): VLAN ID (required if vlan_enabled is true)
    - dhcpd_enabled (boolean): Whether DHCP is enabled (default: true)
    - dhcpd_leasetime (integer): DHCP lease time in seconds
    - domain_name (string): DNS domain name
    - enabled (boolean): Whether the network is enabled (default: true)
    - network_isolation_enabled (boolean): Enable network isolation (IMPORTANT: Only works on networks with purpose="corporate")
    - upnp_lan_enabled (boolean): Enable UPnP on this network
    (see update_network for the full list of additional DHCP/DNS fields that can
    also be supplied at creation time)

    Important Constraints:
    - Network isolation (network_isolation_enabled) is ONLY supported on networks with purpose="corporate".
    - It cannot be enabled on "guest" networks.
    - All DHCP fields use the `dhcpd_*` prefix (the UniFi API field names); the
      legacy `dhcp_enabled`/`dhcp_start`/`dhcp_stop` names are NOT accepted.

    Example:
    {
        "name": "IoT Network",
        "purpose": "corporate",
        "ip_subnet": "10.20.0.0/24",
        "vlan_enabled": true,
        "vlan": 20,
        "dhcpd_enabled": true,
        "dhcpd_start": "10.20.0.100",
        "dhcpd_stop": "10.20.0.254"
    }

    Returns:
    - success (boolean): Whether the operation succeeded
    - network_id (string): ID of the created network if successful
    - details (object): Details of the created network
    - error (string): Error message if unsuccessful
    """
    # Filter input to known mutable fields
    validated_data = network_to_update(network_data) if network_data else {}
    # Supplement with any required-on-create fields that to_controller_update might drop
    # (to_controller_update drops None; required fields must still be present)
    for k in ("name", "purpose", "ip_subnet", "vlan", "vlan_enabled", "dhcpd_start", "dhcpd_stop"):
        if k in network_data and k not in validated_data and network_data[k] is not None:
            validated_data[k] = network_data[k]
    if not validated_data:
        return {"success": False, "error": "network_data cannot be empty"}

    # Required fields check
    required_fields = ["name", "purpose"]
    missing_fields = [field for field in required_fields if field not in validated_data]
    if missing_fields:
        error = f"Missing required fields: {', '.join(missing_fields)}"
        logger.warning(error)
        return {"success": False, "error": error}

    # Additional validation for purpose type
    purpose = validated_data.get("purpose")
    # Ensure purpose is one of the allowed values
    allowed_purposes = [
        "corporate",
        "guest",
        "wan",
        "vlan-only",
        "vpn-client",
        "vpn-server",
    ]  # Consider adding "bridge"? Check schema
    if purpose not in allowed_purposes:
        return {
            "success": False,
            "error": f"Invalid 'purpose': {purpose}. Must be one of {allowed_purposes}.",
        }

    # Validation based on purpose
    if purpose != "vlan-only" and not validated_data.get("ip_subnet"):
        return {
            "success": False,
            "error": f"'ip_subnet' is required for network purpose '{purpose}'",
        }

    if purpose == "vlan-only" and not validated_data.get("vlan"):
        return {
            "success": False,
            "error": "'vlan' is required for network purpose 'vlan-only'.",
        }

    # Validation for DHCP — UniFi API uses dhcpd_* field names
    dhcpd_enabled = validated_data.get("dhcpd_enabled", True)
    if (
        purpose != "vlan-only"
        and dhcpd_enabled
        and (not validated_data.get("dhcpd_start") or not validated_data.get("dhcpd_stop"))
    ):
        return {
            "success": False,
            "error": "'dhcpd_start' and 'dhcpd_stop' are required if dhcpd_enabled is true (and purpose is not vlan-only).",
        }

    # Validation for VLAN
    vlan_enabled = validated_data.get("vlan_enabled", False)
    vlan_id = validated_data.get("vlan")
    if vlan_enabled and not vlan_id:
        return {
            "success": False,
            "error": "'vlan' is required when vlan_enabled is true",
        }

    if vlan_id is not None and (int(vlan_id) < 1 or int(vlan_id) > 4094):
        return {"success": False, "error": "'vlan' must be between 1 and 4094."}

    if not confirm:
        return create_preview(
            resource_type="network",
            resource_data=validated_data,
            resource_name=validated_data.get("name"),
            warnings=["Creating a network may temporarily disrupt connectivity"],
        )

    logger.info("Attempting to create network '%s' with purpose '%s'", validated_data["name"], purpose)
    try:
        # Use validated data directly
        network_data = validated_data
        network_data.setdefault("enabled", True)

        # Assume manager returns the created dict or None/False
        created_network = await network_manager.create_network(network_data)
        if created_network and created_network.get("_id"):
            new_network_id = created_network.get("_id")
            logger.info("Successfully created network '%s' with ID %s", validated_data["name"], new_network_id)
            return {
                "success": True,
                "site": network_manager._connection.site,
                "message": f"Network '{validated_data['name']}' created successfully.",
                "network_id": new_network_id,
                "details": json.loads(json.dumps(created_network, default=str)),
            }
        else:
            error_msg = (
                created_network.get("error", "Manager returned failure")
                if isinstance(created_network, dict)
                else "Manager returned non-dict or failure"
            )
            logger.error("Failed to create network '%s'. Reason: %s", validated_data["name"], error_msg)
            return {
                "success": False,
                "error": f"Failed to create network '{validated_data['name']}'. {error_msg}",
            }
    except Exception as e:
        logger.error(
            "Error creating network '%s': %s",
            validated_data.get("name", "unknown"),
            e,
            exc_info=True,
        )
        return {"success": False, "error": str(e)}


@server.tool(
    name="unifi_list_wlans",
    description="List all configured Wireless LANs (WLANs) on the Unifi Network controller.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_wlans() -> Dict[str, Any]:
    """Lists all WLANs (Wireless SSIDs) configured on the UniFi Network controller.

    Returns:
        A dictionary containing:
        - success (bool): Indicates if the operation was successful.
        - site (str): The identifier of the UniFi site queried.
        - count (int): The number of WLANs found.
        - wlans (List[Dict]): A list of WLANs, each containing summary info:
            - id (str): The unique identifier (_id) of the WLAN.
            - name (str): The SSID (name) of the WLAN.
            - enabled (bool): Whether the WLAN is currently active.
            - security (str): The security mode (e.g., 'wpapsk', 'open').
            - network_id (str, optional): The ID of the network this WLAN is associated with.
            - usergroup_id (str, optional): The ID of the user group associated with this WLAN.
        - error (str, optional): An error message if the operation failed.

    Example response (success):
    {
        "success": True,
        "site": "default",
        "count": 1,
        "wlans": [
            {
                "id": "60c7d8e9f0a1b2c3d4e5f6a7",
                "name": "MyWiFi",
                "enabled": True,
                "security": "wpapsk",
                "network_id": "60a8b3c4d5e6f7a8b9c0d1e2",
                "usergroup_id": "_default_"
            }
        ]
    }
    """
    try:
        wlans = await network_manager.get_wlans()
        # Ensure wlans are dictionaries
        wlans_raw = [w.raw if hasattr(w, "raw") else w for w in wlans]
        formatted_wlans = [
            {
                "id": w.get("_id"),
                "name": w.get("name"),
                "enabled": w.get("enabled"),
                "security": w.get("security"),
                "network_id": w.get("networkconf_id"),  # Map internal key
                "usergroup_id": w.get("usergroup_id"),
            }
            for w in wlans_raw
        ]
        return {
            "success": True,
            "site": network_manager._connection.site,
            "count": len(formatted_wlans),
            "wlans": formatted_wlans,
        }
    except Exception as e:
        logger.error("Error listing WLANs: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list WLANs: {e}"}


@server.tool(
    name="unifi_get_wlan_details",
    description="Get details for a specific WLAN by ID.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_wlan_details(
    wlan_id: Annotated[str, Field(description="Unique identifier (_id) of the WLAN/SSID (from unifi_list_wlans)")],
) -> Dict[str, Any]:
    """Gets the detailed configuration of a specific WLAN (SSID) by its ID.

    Args:
        wlan_id (str): The unique identifier (_id) of the WLAN.

    Returns:
        A dictionary containing:
        - success (bool): Indicates if the operation was successful.
        - site (str): The identifier of the UniFi site queried.
        - wlan_id (str): The ID of the WLAN requested.
        - details (Dict[str, Any]): A dictionary containing the raw configuration details
          of the WLAN as returned by the UniFi controller.
        - error (str, optional): An error message if the operation failed (e.g., WLAN not found).

    Example response (success):
    {
        "success": True,
        "site": "default",
        "wlan_id": "60c7d8e9f0a1b2c3d4e5f6a7",
        "details": {
            "_id": "60c7d8e9f0a1b2c3d4e5f6a7",
            "name": "MyWiFi",
            "enabled": True,
            "security": "wpapsk",
            "x_passphrase": "secretpassword",
            "hide_ssid": False,
            "networkconf_id": "60a8b3c4d5e6f7a8b9c0d1e2",
            "usergroup_id": "_default_",
            "site_id": "...",
            # ... other fields
        }
    }
    """
    try:
        if not wlan_id:
            return {"success": False, "error": "wlan_id is required"}
        wlan = await network_manager.get_wlan_details(wlan_id)
        if wlan:
            return {
                "success": True,
                "site": network_manager._connection.site,
                "wlan_id": wlan_id,
                "details": json.loads(json.dumps(wlan, default=str)),
            }
        else:
            return {"success": False, "error": f"WLAN with ID '{wlan_id}' not found."}
    except Exception as e:
        logger.error("Error getting WLAN details for %s: %s", wlan_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get WLAN details for {wlan_id}: {e}"}


@server.tool(
    name="unifi_update_wlan",
    description="Update specific fields of an existing WLAN (SSID). "
    "Pass only the fields you want to change — current values are automatically preserved. "
    "Basic: name (str), security ('open'/'wpapsk'/'wpa2-psk'), x_passphrase (str), "
    "enabled (bool), hide_ssid (bool), guest_policy (bool), usergroup_id (str), networkconf_id (str). "
    "Security: wpa3_support (bool), wpa3_transition (bool), pmf_mode ('disabled'/'optional'/'required'), "
    "fast_roaming_enabled (bool), group_rekey (int seconds, 0=disabled). "
    "Access control: mac_filter_enabled (bool), mac_filter_policy ('allow'/'deny'), "
    "mac_filter_list (list of MAC strings), l2_isolation (bool). "
    "Radio: wlan_band ('both'/'2g'/'5g'), multicast_enhance_enabled (bool), "
    "dtim_mode ('default'/'custom'), dtim_na (int 1-255), dtim_ng (int 1-255), "
    "minrate_ng_enabled (bool), minrate_ng_data_rate_kbps (int), "
    "minrate_na_enabled (bool), minrate_na_data_rate_kbps (int). "
    "Other: schedule_enabled (bool), uapsd_enabled (bool), proxy_arp (bool), iapp_enabled (bool). "
    "Requires confirmation.",
    permission_category="wlans",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_wlan(
    wlan_id: Annotated[str, Field(description="Unique identifier (_id) of the WLAN to update (from unifi_list_wlans)")],
    update_data: Annotated[
        Dict[str, Any],
        Field(description="Dictionary of fields to update. See tool description for all supported fields."),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the update. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Updates specific fields of an existing WLAN (Wireless SSID).

    Only provided fields are updated — current values are automatically preserved.
    Supported fields are defined by the WLAN pydantic model in unifi_core.network.models.wlans.
    Requires confirmation.

    Args:
        wlan_id (str): The unique identifier (_id) of the WLAN to update.
        update_data (Dict[str, Any]): Dictionary of fields to update. See tool description
            for all supported fields.
        confirm (bool): Must be set to `True` to execute. Defaults to `False`.

    Returns:
        Dict: Success status, ID, updated fields, details, or error message.
        Example (success):
        {
            "success": True,
            "wlan_id": "60c7d8e9f0a1b2c3d4e5f6a7",
            "updated_fields": ["name", "enabled", "x_passphrase"],
            "details": { ... updated WLAN details ... }
        }
    """
    if not wlan_id:
        return {"success": False, "error": "wlan_id is required"}
    if not update_data:
        return {"success": False, "error": "update_data cannot be empty"}

    # Translate to controller-compatible update payload via pydantic model
    validated_data = wlan_to_update(update_data)

    if not validated_data:
        logger.warning("WLAN update data for ID %s is empty after validation.", wlan_id)
        return {
            "success": False,
            "error": "Update data is effectively empty or invalid.",
        }

    # Fetch current state for preview
    current = await network_manager.get_wlan_details(wlan_id)
    if not current:
        return {"success": False, "error": "WLAN not found"}

    if not confirm:
        return update_preview(
            resource_type="wlan",
            resource_id=wlan_id,
            resource_name=current.get("name"),
            current_state=current,
            updates=validated_data,
        )

    # Basic cross-field validation for password
    if "security" in validated_data and validated_data["security"] != "open" and "x_passphrase" not in validated_data:
        # Check existing state? Or require passphrase if changing security?
        pass  # Let manager handle merge/API requirements

    updated_fields_list = list(validated_data.keys())
    logger.info("Attempting to update WLAN '%s' with fields: %s", wlan_id, ", ".join(updated_fields_list))
    try:
        success, error_detail = await network_manager.update_wlan(wlan_id, validated_data)

        if success:
            updated_wlan = await network_manager.get_wlan_details(wlan_id)
            logger.info("Successfully updated WLAN (%s)", wlan_id)
            return {
                "success": True,
                "wlan_id": wlan_id,
                "updated_fields": updated_fields_list,
                "details": json.loads(json.dumps(updated_wlan, default=str)),
            }
        else:
            logger.error("Failed to update WLAN (%s): %s", wlan_id, error_detail)
            wlan_after_update = await network_manager.get_wlan_details(wlan_id)
            return {
                "success": False,
                "wlan_id": wlan_id,
                "error": f"Failed to update WLAN ({wlan_id}): {error_detail}",
                "details_after_attempt": json.loads(json.dumps(wlan_after_update, default=str)),
            }

    except Exception as e:
        logger.error("Error updating WLAN %s: %s", wlan_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update WLAN {wlan_id}: {e}"}


@server.tool(
    name="unifi_create_wlan",
    description=("Create a new Wireless LAN (WLAN/SSID) with schema validation. Requires confirmation."),
    permission_category="wlans",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_wlan(
    wlan_data: Annotated[
        Dict[str, Any],
        Field(
            description="WLAN configuration dict. Required: name (SSID string), security ('open'/'wpa-psk'/'wpa2-psk'). Required if security != 'open': x_passphrase (password). Optional: enabled (bool, default true), hide_ssid (bool), guest_policy (bool), usergroup_id, networkconf_id (network to associate)"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, creates the WLAN. When false (default), validates and returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Create a new WLAN (SSID) with comprehensive validation.

    Args:
        wlan_data (Dict[str, Any]): WLAN configuration data
        confirm (bool): Must be set to `True` to execute. Defaults to `False`.

    Required parameters in wlan_data:
    - name (string): Name of the wireless network (SSID)
    - security (string): Security protocol ("open", "wpa-psk", "wpa2-psk", etc.)

    If security is not "open":
    - x_passphrase (string): Password for the wireless network

    Optional parameters in wlan_data:
    - enabled (boolean): Whether the network is enabled (default: true)
    - hide_ssid (boolean): Whether to hide the SSID (default: false)
    - guest_policy (boolean): Whether this is a guest network (default: false)
    - usergroup_id (string): User group ID (default: default group)
    - networkconf_id (string): Network configuration ID to associate with (default: default LAN)

    Example:
    {
        "name": "GuestWiFi",
        "security": "open",
        "enabled": true,
        "guest_policy": true,
        "networkconf_id": "60a8b3c4d5e6f7a8b9c0d1e4" # Associate with guest network
    }

    Returns:
    - success (boolean): Whether the operation succeeded
    - wlan_id (string): ID of the created WLAN if successful
    - details (object): Details of the created WLAN
    - error (string): Error message if unsuccessful
    """
    # Filter input to known mutable fields via pydantic model
    from unifi_core.network.models.wlans import Wlan as WlanModel

    try:
        wlan_model = WlanModel(**{k: v for k, v in wlan_data.items() if k in WLAN_MUTABLE_FIELDS})
    except Exception as exc:
        return {"success": False, "error": f"Invalid WLAN data: {exc}"}
    validated_data = wlan_to_create(wlan_model)

    # Required fields check
    required_fields = ["name", "security"]
    missing_fields = [field for field in required_fields if field not in validated_data]
    if missing_fields:
        error = f"Missing required fields: {', '.join(missing_fields)}"
        logger.warning(error)
        return {"success": False, "error": error}

    # Check passphrase requirement
    if validated_data.get("security") != "open" and not validated_data.get("x_passphrase"):
        return {
            "success": False,
            "error": "'x_passphrase' is required when security is not 'open'",
        }

    if not confirm:
        return create_preview(
            resource_type="wlan",
            resource_data=validated_data,
            resource_name=validated_data.get("name"),
            warnings=["Creating a WLAN may temporarily affect wireless connectivity"],
        )

    logger.info("Attempting to create WLAN '%s' with security '%s'", validated_data["name"], validated_data["security"])
    try:
        # Pass validated data directly to manager
        wlan_payload = validated_data
        wlan_payload.setdefault("enabled", True)

        created_wlan = await network_manager.create_wlan(wlan_payload)

        if created_wlan and created_wlan.get("_id"):
            new_wlan_id = created_wlan.get("_id")
            logger.info("Successfully created WLAN '%s' with ID %s", validated_data["name"], new_wlan_id)
            return {
                "success": True,
                "site": network_manager._connection.site,
                "message": f"WLAN '{validated_data['name']}' created successfully.",
                "wlan_id": new_wlan_id,
                "details": json.loads(json.dumps(created_wlan, default=str)),
            }
        else:
            error_msg = (
                created_wlan.get("error", "Manager returned failure")
                if isinstance(created_wlan, dict)
                else "Manager returned non-dict or failure"
            )
            logger.error("Failed to create WLAN '%s'. Reason: %s", validated_data["name"], error_msg)
            return {
                "success": False,
                "error": f"Failed to create WLAN '{validated_data['name']}'. {error_msg}",
            }

    except Exception as e:
        logger.error(
            "Error creating WLAN '%s': %s",
            validated_data.get("name", "unknown"),
            e,
            exc_info=True,
        )
        return {"success": False, "error": str(e)}


@server.tool(
    name="unifi_delete_wlan",
    description=(
        "Delete a WLAN/SSID by ID. Requires confirmation. WARNING: All devices using this SSID will be disconnected."
    ),
    permission_category="wlans",
    permission_action="delete",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def delete_wlan(
    wlan_id: Annotated[
        str, Field(description="Unique identifier (_id) of the WLAN/SSID to delete (from unifi_list_wlans)")
    ],
    confirm: Annotated[
        bool,
        Field(
            description="When true, deletes the WLAN. When false (default), returns a preview. "
            "WARNING: All devices using this SSID will be disconnected"
        ),
    ] = False,
) -> Dict[str, Any]:
    """Delete a WLAN/SSID. All devices using this SSID will be disconnected."""
    if not confirm:
        # Fetch current WLAN details to show what will be deleted
        try:
            wlan = await network_manager.get_wlan_details(wlan_id)
            resource_data = (
                {
                    "wlan_id": wlan_id,
                    "name": wlan.get("name", "Unknown"),
                    "enabled": wlan.get("enabled"),
                    "security": wlan.get("security"),
                }
                if wlan
                else {"wlan_id": wlan_id}
            )
            resource_name = wlan.get("name", wlan_id) if wlan else wlan_id
        except Exception:
            resource_data = {"wlan_id": wlan_id}
            resource_name = wlan_id

        return create_preview(
            resource_type="wlan",
            resource_data=resource_data,
            resource_name=resource_name,
            warnings=["All devices using this SSID will be disconnected"],
        )

    try:
        success = await network_manager.delete_wlan(wlan_id)
        if success:
            return {"success": True, "message": f"WLAN '{wlan_id}' deleted successfully."}
        return {"success": False, "error": f"Failed to delete WLAN '{wlan_id}'."}
    except Exception as e:
        logger.error("Error deleting WLAN %s: %s", wlan_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to delete WLAN '{wlan_id}': {e}"}


@server.tool(
    name="unifi_toggle_wlan",
    description="Toggle a WLAN/SSID on or off. Requires confirmation.",
    permission_category="wlans",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def toggle_wlan(
    wlan_id: Annotated[
        str, Field(description="Unique identifier (_id) of the WLAN/SSID to toggle (from unifi_list_wlans)")
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, executes the toggle. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Toggle a WLAN/SSID on or off."""
    try:
        # Fetch current state to show toggle preview
        wlan = await network_manager.get_wlan_details(wlan_id)
        if not wlan:
            return {"success": False, "error": f"WLAN with ID '{wlan_id}' not found."}

        current_enabled = wlan.get("enabled", False)
        wlan_name = wlan.get("name", wlan_id)
        new_state = not current_enabled

        if not confirm:
            return toggle_preview(
                resource_type="wlan",
                resource_id=wlan_id,
                resource_name=wlan_name,
                current_enabled=current_enabled,
                additional_info={
                    "security": wlan.get("security"),
                    "network_id": wlan.get("networkconf_id"),
                },
            )

        logger.info("Attempting to toggle WLAN '%s' (%s) to %s", wlan_name, wlan_id, new_state)

        success = await network_manager.toggle_wlan(wlan_id)

        if success:
            # Re-fetch to confirm final state
            updated_wlan = await network_manager.get_wlan_details(wlan_id)
            final_state = updated_wlan.get("enabled", new_state) if updated_wlan else new_state
            state_str = "enabled" if final_state else "disabled"
            logger.info("Successfully toggled WLAN '%s' (%s) to %s", wlan_name, wlan_id, state_str)
            return {
                "success": True,
                "wlan_id": wlan_id,
                "enabled": final_state,
                "message": f"WLAN '{wlan_name}' ({wlan_id}) toggled to {state_str}.",
            }
        return {"success": False, "error": f"Failed to toggle WLAN '{wlan_id}'."}
    except Exception as e:
        logger.error("Error toggling WLAN %s: %s", wlan_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to toggle WLAN '{wlan_id}': {e}"}


# ---- AP Group Tools ----


@server.tool(
    name="unifi_list_ap_groups",
    description=(
        "List all AP groups configured on the controller. "
        "AP groups control which access points broadcast which SSIDs. "
        "Returns group names, IDs, and associated AP/WLAN memberships."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_ap_groups() -> Dict[str, Any]:
    """List all AP groups."""
    try:
        groups = await network_manager.list_ap_groups()
        formatted = [ap_group_from_controller(g).model_dump(exclude_none=True) for g in groups]
        return {
            "success": True,
            "site": network_manager._connection.site,
            "count": len(formatted),
            "ap_groups": formatted,
        }
    except Exception as e:
        logger.error("Error listing AP groups: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list AP groups: {e}"}


@server.tool(
    name="unifi_get_ap_group_details",
    description="Get details of a specific AP group by ID, including member APs and WLANs.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_ap_group_details(
    group_id: Annotated[str, Field(description="Unique identifier of the AP group (from unifi_list_ap_groups)")],
) -> Dict[str, Any]:
    """Get details of a specific AP group."""
    try:
        if not group_id:
            return {"success": False, "error": "group_id is required"}
        group = await network_manager.get_ap_group_details(group_id)
        if group:
            return {
                "success": True,
                "site": network_manager._connection.site,
                "group_id": group_id,
                "details": ap_group_from_controller(group).model_dump(exclude_none=True),
            }
        return {"success": False, "error": f"AP group with ID '{group_id}' not found."}
    except Exception as e:
        logger.error("Error getting AP group details for %s: %s", group_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get AP group details for {group_id}: {e}"}


@server.tool(
    name="unifi_create_ap_group",
    description="Create a new AP group to control which APs broadcast which SSIDs. Requires confirmation.",
    permission_category="wlans",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_ap_group(
    group_data: Annotated[
        Dict[str, Any],
        Field(
            description="AP group configuration dict. Typical fields: name (str), "
            "device_macs (list of AP MAC addresses), wlan_group_ids (list of WLAN group IDs)"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, creates the AP group. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Create a new AP group."""
    from unifi_core.network.models.ap_group import ApGroup

    try:
        model = ApGroup(**{k: v for k, v in group_data.items() if k in ("name", "device_macs", "wlan_group_ids")})
    except Exception as exc:
        return {"success": False, "error": f"Invalid AP group data: {exc}"}
    validated_data = ap_group_to_create(model)
    if not validated_data.get("name"):
        return {"success": False, "error": "Invalid AP group data: 'name' is required"}

    if not confirm:
        return create_preview(
            resource_type="ap_group",
            resource_data=validated_data,
            resource_name=validated_data.get("name", "unnamed"),
        )

    try:
        created = await network_manager.create_ap_group(validated_data)
        if created:
            group_id = created.get("_id") or created.get("id")
            return {
                "success": True,
                "site": network_manager._connection.site,
                "message": f"AP group '{group_data.get('name')}' created successfully.",
                "group_id": group_id,
                "details": json.loads(json.dumps(created, default=str)),
            }
        return {"success": False, "error": f"Failed to create AP group '{group_data.get('name')}'."}
    except Exception as e:
        logger.error("Error creating AP group: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to create AP group: {e}"}


@server.tool(
    name="unifi_update_ap_group",
    description=(
        "Update an existing AP group's configuration. "
        "Pass only the fields you want to change — current values are automatically preserved. "
        "Requires confirmation."
    ),
    permission_category="wlans",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_ap_group(
    group_id: Annotated[
        str, Field(description="Unique identifier of the AP group to update (from unifi_list_ap_groups)")
    ],
    update_data: Annotated[
        Dict[str, Any],
        Field(
            description="Dictionary of fields to update. Pass only the fields you want to change — "
            "current values are automatically preserved. "
            "Common fields: name (str), device_macs (list), wlan_group_ids (list)"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the update. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Update an existing AP group."""
    if not group_id:
        return {"success": False, "error": "group_id is required"}
    if not update_data:
        return {"success": False, "error": "update_data cannot be empty"}

    # Translate to controller-safe mutable fields
    validated_data = ap_group_to_update(update_data)
    if not validated_data:
        return {"success": False, "error": "No valid mutable fields provided for update."}

    # Fetch current state for preview
    current = await network_manager.get_ap_group_details(group_id)
    if not current:
        return {"success": False, "error": f"AP group with ID '{group_id}' not found."}

    if not confirm:
        return update_preview(
            resource_type="ap_group",
            resource_id=group_id,
            resource_name=current.get("name", group_id),
            current_state=current,
            updates=validated_data,
        )

    try:
        success = await network_manager.update_ap_group(group_id, validated_data)
        if success:
            updated = await network_manager.get_ap_group_details(group_id)
            return {
                "success": True,
                "group_id": group_id,
                "updated_fields": list(validated_data.keys()),
                "details": json.loads(json.dumps(updated, default=str)),
            }
        return {"success": False, "error": f"Failed to update AP group '{group_id}'."}
    except Exception as e:
        logger.error("Error updating AP group %s: %s", group_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update AP group {group_id}: {e}"}


@server.tool(
    name="unifi_delete_ap_group",
    description=(
        "Delete an AP group by ID. Requires confirmation. WARNING: APs in this group may lose their SSID assignments."
    ),
    permission_category="wlans",
    permission_action="delete",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def delete_ap_group(
    group_id: Annotated[
        str, Field(description="Unique identifier of the AP group to delete (from unifi_list_ap_groups)")
    ],
    confirm: Annotated[
        bool,
        Field(
            description="When true, deletes the AP group. When false (default), returns a preview. "
            "WARNING: APs in this group may lose their SSID assignments"
        ),
    ] = False,
) -> Dict[str, Any]:
    """Delete an AP group."""
    if not confirm:
        try:
            group = await network_manager.get_ap_group_details(group_id)
            resource_data = (
                {
                    "group_id": group_id,
                    "name": group.get("name", "Unknown"),
                }
                if group
                else {"group_id": group_id}
            )
            resource_name = group.get("name", group_id) if group else group_id
        except Exception:
            resource_data = {"group_id": group_id}
            resource_name = group_id

        return create_preview(
            resource_type="ap_group",
            resource_data=resource_data,
            resource_name=resource_name,
            warnings=["APs in this group may lose their SSID assignments"],
        )

    try:
        success = await network_manager.delete_ap_group(group_id)
        if success:
            return {"success": True, "message": f"AP group '{group_id}' deleted successfully."}
        return {"success": False, "error": f"Failed to delete AP group '{group_id}'."}
    except Exception as e:
        logger.error("Error deleting AP group %s: %s", group_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to delete AP group '{group_id}': {e}"}
