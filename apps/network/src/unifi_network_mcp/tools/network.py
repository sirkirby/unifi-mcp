"""
Unifi Network MCP network tools.

This module provides MCP tools to interact with a Unifi Network Controller's network functions,
including managing LAN networks and WLANs.
"""

import json
import logging
from typing import Annotated, Any, Dict, Optional

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
from unifi_core.redaction import redact_sensitive_fields
from unifi_network_mcp.runtime import network_manager, server

logger = logging.getLogger(__name__)

_INCLUDE_SENSITIVE_FIELD = Field(
    description="When true, returns raw controller secret fields. Leave false for normal AI-agent use."
)


@server.tool(
    name="unifi_list_networks",
    description=(
        "Returns configured networks (LAN, WAN, VLAN-only) with name, purpose, "
        "IP subnet, VLAN ID, DHCP settings, and enabled state. "
        "Use to understand network topology and VLAN layout. "
        "Filters: search (name/VLAN substring), purpose (corporate/guest/wan/vlan-only), "
        "limit (default 25), fields (comma-separated subset). "
        "For a single network's full config, use unifi_get_network_details. "
        "For wireless SSIDs, use unifi_list_wlans."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_networks(
    search: Annotated[
        Optional[str],
        Field(description="Filter by name (case-insensitive substring) or VLAN ID (exact match, e.g. '20')"),
    ] = None,
    purpose: Annotated[
        Optional[str],
        Field(description="Filter by purpose (corporate, guest, wan, vlan-only)"),
    ] = None,
    limit: Annotated[int, Field(description="Maximum number of networks to return (default 25)")] = 25,
    fields: Annotated[
        Optional[str],
        Field(
            description=(
                "Comma-separated list of fields to return per network (default: all). "
                "Available: _id, name, enabled, purpose, ip_subnet, vlan_enabled, vlan, "
                "dhcpd_enabled, dhcpd_start, dhcpd_stop. "
                "Example: fields='_id,name,vlan,purpose' returns only those fields."
            )
        ),
    ] = None,
) -> Dict[str, Any]:
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
        if purpose and purpose.strip():
            networks_data = [n for n in networks_data if n.get("purpose") == purpose.strip().lower()]

        if search and search.strip():
            search_lower = search.strip().lower()
            networks_data = [
                n
                for n in networks_data
                if search_lower in (n.get("name") or "").lower() or search_lower == str(n.get("vlan") or "")
            ]

        total_count = len(networks_data)
        networks_data = networks_data[:limit]

        known_fields = {
            "_id",
            "name",
            "enabled",
            "purpose",
            "ip_subnet",
            "vlan_enabled",
            "vlan",
            "dhcpd_enabled",
            "dhcpd_start",
            "dhcpd_stop",
        }
        requested_fields = None
        unknown_fields: list[str] = []
        if fields and fields.strip():
            requested_fields = set(f.strip() for f in fields.split(","))
            unknown_fields = sorted(requested_fields - known_fields)

        formatted_networks = []
        for network in networks_data:
            # Source values through the typed model (validation/coercion); the list view
            # then narrows to a curated subset and honors the optional `fields` selector.
            shaped = network_from_controller(network)
            full_data = {
                "_id": shaped.id,
                "name": shaped.name,
                "enabled": shaped.enabled,
                "purpose": shaped.purpose,
                "ip_subnet": shaped.ip_subnet,
                "vlan_enabled": shaped.vlan_enabled,
                "vlan": shaped.vlan,
                "dhcpd_enabled": shaped.dhcpd_enabled,
                "dhcpd_start": shaped.dhcpd_start,
                "dhcpd_stop": shaped.dhcpd_stop,
            }

            if requested_fields:
                formatted = {k: v for k, v in full_data.items() if k in requested_fields}
            else:
                formatted = full_data

            formatted_networks.append(formatted)

        response = {
            "success": True,
            "site": network_manager._connection.site,
            "search": search,
            "purpose_filter": purpose,
            "fields": fields,
            "total_count": total_count,
            "returned_count": len(formatted_networks),
            "count": len(formatted_networks),  # back-compat alias for returned_count
            "limit": limit,
            "networks": formatted_networks,
        }
        if unknown_fields:
            response["unknown_fields"] = unknown_fields
        return response
    except Exception as e:
        logger.error("Error listing networks in tool: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list networks: {e}"}


@server.tool(
    name="unifi_get_network_details",
    description=(
        "Get details for a specific network by ID. By default (summary=false) returns the full raw "
        "network configuration. Set summary=true to trim to selected sections via include "
        "(basic, dhcp, ipv6, vpn, wan, all).\n\n"
        "Examples: <no args> (full raw); summary=true,include='basic' (minimal); "
        "summary=true,include='basic,dhcp' (adds DHCP server config); summary=true,include='all'."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_network_details(
    network_id: Annotated[str, Field(description="Unique identifier (_id) of the network (from unifi_list_networks)")],
    include: Annotated[
        str,
        Field(
            description=(
                "Comma-separated sections to return when summary=true (default 'basic'). "
                "Sections: basic, dhcp, ipv6, vpn, wan, all."
            )
        ),
    ] = "basic",
    summary: Annotated[
        bool,
        Field(
            description=(
                "When false (default), returns the full raw network object. "
                "When true, trims to the sections named in include."
            )
        ),
    ] = False,
    include_sensitive: Annotated[bool, _INCLUDE_SENSITIVE_FIELD] = False,
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
        network = await network_manager.get_network_details(network_id)
        if network:
            if not summary:
                return redact_sensitive_fields(
                    {
                        "success": True,
                        "site": network_manager._connection.site,
                        "network_id": network_id,
                        "include": "all",
                        "summary_mode": False,
                        "details": json.loads(json.dumps(network, default=str)),
                    },
                    include_sensitive=include_sensitive,
                )

            known_sections = {"basic", "dhcp", "ipv6", "vpn", "wan", "all"}
            sections = set(s.strip().lower() for s in include.split(","))
            unknown_sections = sorted(sections - known_sections)
            include_all = "all" in sections

            network_data: Dict[str, Any] = {}

            if include_all or "basic" in sections:
                network_data.update(
                    {
                        "_id": network.get("_id"),
                        "name": network.get("name"),
                        "enabled": network.get("enabled"),
                        "purpose": network.get("purpose"),
                        "ip_subnet": network.get("ip_subnet"),
                        "vlan_enabled": network.get("vlan_enabled"),
                        "vlan": network.get("vlan"),
                        "domain_name": network.get("domain_name"),
                        "is_nat": network.get("is_nat"),
                        "network_isolation_enabled": network.get("network_isolation_enabled"),
                    }
                )

            if include_all or "dhcp" in sections:
                network_data.update(
                    {
                        "dhcpd_enabled": network.get("dhcpd_enabled"),
                        "dhcpd_start": network.get("dhcpd_start"),
                        "dhcpd_stop": network.get("dhcpd_stop"),
                        "dhcpd_leasetime": network.get("dhcpd_leasetime"),
                        "dhcpd_dns_enabled": network.get("dhcpd_dns_enabled"),
                        "dhcpd_gateway_enabled": network.get("dhcpd_gateway_enabled"),
                        "dhcpd_unifi_controller": network.get("dhcpd_unifi_controller"),
                    }
                )

            if include_all or "ipv6" in sections:
                network_data.update(
                    {
                        "ipv6_interface_type": network.get("ipv6_interface_type"),
                        "ipv6_pd_start": network.get("ipv6_pd_start"),
                        "ipv6_pd_stop": network.get("ipv6_pd_stop"),
                        "ipv6_ra_enabled": network.get("ipv6_ra_enabled"),
                    }
                )

            if include_all or "vpn" in sections:
                network_data.update(
                    {
                        "vpn_type": network.get("vpn_type"),
                        "remote_site_id": network.get("remote_site_id"),
                        "remote_site_subnets": network.get("remote_site_subnets"),
                    }
                )

            if include_all or "wan" in sections:
                network_data.update(
                    {
                        "wan_networkgroup": network.get("wan_networkgroup"),
                        "wan_type": network.get("wan_type"),
                        "wan_dns_preference": network.get("wan_dns_preference"),
                        "wan_load_balance_type": network.get("wan_load_balance_type"),
                        "wan_load_balance_weight": network.get("wan_load_balance_weight"),
                        "wan_failover_priority": network.get("wan_failover_priority"),
                        "wan_smartq_enabled": network.get("wan_smartq_enabled"),
                        "wan_vlan_enabled": network.get("wan_vlan_enabled"),
                        "igmp_proxy_upstream": network.get("igmp_proxy_upstream"),
                        "igmp_proxy_for": network.get("igmp_proxy_for"),
                        "mac_override_enabled": network.get("mac_override_enabled"),
                        "wan_ip_aliases": network.get("wan_ip_aliases"),
                        "ipv6_enabled": network.get("ipv6_enabled"),
                        "wan_type_v6": network.get("wan_type_v6"),
                        "ipv6_setting_preference": network.get("ipv6_setting_preference"),
                        "ipv6_wan_delegation_type": network.get("ipv6_wan_delegation_type"),
                        "wan_dhcpv6_pd_size": network.get("wan_dhcpv6_pd_size"),
                        "wan_dhcpv6_pd_size_auto": network.get("wan_dhcpv6_pd_size_auto"),
                        "wan_ipv6_dns_preference": network.get("wan_ipv6_dns_preference"),
                        "wan_ipv6_dns1": network.get("wan_ipv6_dns1"),
                        "wan_ipv6_dns2": network.get("wan_ipv6_dns2"),
                    }
                )

            response = {
                "success": True,
                "site": network_manager._connection.site,
                "network_id": network_id,
                "include": include,
                "summary_mode": True,
                "details": network_data,
            }
            if unknown_sections:
                response["unknown_sections"] = unknown_sections
            return redact_sensitive_fields(response, include_sensitive=include_sensitive)
        else:
            return {
                "success": False,
                "error": f"Network with ID '{network_id}' not found.",
            }
    except Exception as e:
        logger.error("Error getting network details for %s: %s", network_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get network details for {network_id}: {e}"}


# WAN fields whose change can interrupt internet connectivity. When any appear in an
# update diff, the confirm-preview surfaces an explicit warning (see update_network).
CONNECTIVITY_CRITICAL_WAN_FIELDS: frozenset[str] = frozenset(
    {
        "wan_type",
        "wan_networkgroup",
        "wan_dns_preference",
        "wan_load_balance_type",
        "wan_load_balance_weight",
        "wan_failover_priority",
        "wan_vlan_enabled",
        "mac_override_enabled",
    }
)


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
    "WAN (gateway uplink, purpose='wan' networks): wan_type ('dhcp'/'static'/'pppoe'/'disabled'), "
    "wan_networkgroup ('WAN'/'WAN2'), wan_dns_preference ('auto'/'manual'), "
    "wan_load_balance_type ('failover-only'/'weighted'), wan_load_balance_weight (int 0-100), "
    "wan_failover_priority (int), wan_smartq_enabled (bool), wan_vlan_enabled (bool), "
    "igmp_proxy_upstream (bool), igmp_proxy_for (JSON: 'none' or list of network refs), "
    "mac_override_enabled (bool), wan_ip_aliases (list). "
    "WAN IPv6 (dual-stack; does not affect IPv4 internet): ipv6_enabled (bool), wan_type_v6 (str), "
    "ipv6_setting_preference ('auto'/'manual'), ipv6_wan_delegation_type (str), wan_dhcpv6_pd_size (int), "
    "wan_dhcpv6_pd_size_auto (bool), wan_ipv6_dns_preference ('auto'/'manual'), wan_ipv6_dns1 (str), wan_ipv6_dns2 (str). "
    "WARNING: changing wan_type/wan_networkgroup/DNS/VLAN/failover/load-balance/mac-override on a WAN can interrupt internet connectivity. "
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
    include_sensitive: Annotated[bool, _INCLUDE_SENSITIVE_FIELD] = False,
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
            WAN uplink fields (purpose='wan' networks — changing connectivity-critical ones
            surfaces a warning in the confirm-preview):
            - wan_type (string): WAN IPv4 type: 'dhcp', 'static', 'pppoe', 'disabled'.
            - wan_networkgroup (string): Physical WAN: 'WAN' (primary) or 'WAN2' (secondary).
            - wan_dns_preference (string): WAN DNS source: 'auto' or 'manual'.
            - wan_load_balance_type (string): Dual-WAN mode: 'failover-only' or 'weighted'.
            - wan_load_balance_weight (integer): Load-balance weight (0-100, used when 'weighted').
            - wan_failover_priority (integer): Failover priority (lower = higher priority).
            - wan_smartq_enabled (boolean): Enable Smart Queues (QoS/bufferbloat) on the WAN.
            - wan_vlan_enabled (boolean): Enable VLAN tagging on the WAN uplink.
            - igmp_proxy_upstream (boolean): Enable IGMP proxy on this WAN (IPTV multicast).
            - igmp_proxy_for (JSON): IGMP proxy downstream scope ('none' or list of network refs).
            - mac_override_enabled (boolean): Enable MAC clone/override on the WAN.
            - wan_ip_aliases (list): Secondary IP aliases on the WAN.
            WAN IPv6 uplink fields (dual-stack; changing these does not drop IPv4 internet):
            - ipv6_enabled (boolean): Enable IPv6 on the WAN uplink.
            - wan_type_v6 (string): WAN IPv6 type (e.g. 'disabled', 'dhcpv6', 'slaac', 'static').
            - ipv6_setting_preference (string): IPv6 settings source: 'auto' or 'manual'.
            - ipv6_wan_delegation_type (string): IPv6 prefix-delegation type (e.g. 'none', 'dhcpv6', 'static').
            - wan_dhcpv6_pd_size (integer): DHCPv6 prefix-delegation size (e.g. 64).
            - wan_dhcpv6_pd_size_auto (boolean): Auto-negotiate the DHCPv6 PD size.
            - wan_ipv6_dns_preference (string): WAN IPv6 DNS source: 'auto' or 'manual'.
            - wan_ipv6_dns1 (string): Primary WAN IPv6 DNS server.
            - wan_ipv6_dns2 (string): Secondary WAN IPv6 DNS server.
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

    if "wan_load_balance_weight" in validated_data:
        try:
            _weight = int(validated_data["wan_load_balance_weight"])
        except (TypeError, ValueError):
            return {"success": False, "error": "'wan_load_balance_weight' must be an integer between 0 and 100."}
        if _weight < 0 or _weight > 100:
            return {"success": False, "error": "'wan_load_balance_weight' must be between 0 and 100."}

    # Fetch current state for preview
    current = await network_manager.get_network_details(network_id)
    if not current:
        return {"success": False, "error": "Network not found"}

    if not confirm:
        wan_critical = sorted(set(validated_data) & CONNECTIVITY_CRITICAL_WAN_FIELDS)
        warnings = None
        if wan_critical and current.get("purpose") == "wan":
            wan_name = current.get("name") or network_id
            warnings = [
                "WARNING: Changing "
                + ", ".join(wan_critical)
                + f" on WAN '{wan_name}' may interrupt internet connectivity. "
                "Verify the values before setting confirm=true."
            ]
        return redact_sensitive_fields(
            update_preview(
                resource_type="network",
                resource_id=network_id,
                resource_name=current.get("name"),
                current_state=current,
                updates=validated_data,
                warnings=warnings,
            ),
            include_sensitive=include_sensitive,
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
            return redact_sensitive_fields(
                {
                    "success": True,
                    "network_id": network_id,
                    "updated_fields": updated_fields_list,
                    "details": json.loads(json.dumps(updated_network, default=str)),
                },
                include_sensitive=include_sensitive,
            )
        else:
            logger.error("Failed to update network (%s): %s", network_id, error_detail)
            network_after_update = await network_manager.get_network_details(network_id)
            return redact_sensitive_fields(
                {
                    "success": False,
                    "network_id": network_id,
                    "error": f"Failed to update network ({network_id}): {error_detail}",
                    "details_after_attempt": json.loads(json.dumps(network_after_update, default=str)),
                },
                include_sensitive=include_sensitive,
            )

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
    include_sensitive: Annotated[bool, _INCLUDE_SENSITIVE_FIELD] = False,
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
        return redact_sensitive_fields(
            create_preview(
                resource_type="network",
                resource_data=validated_data,
                resource_name=validated_data.get("name"),
                warnings=["Creating a network may temporarily disrupt connectivity"],
            ),
            include_sensitive=include_sensitive,
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
            return redact_sensitive_fields(
                {
                    "success": True,
                    "site": network_manager._connection.site,
                    "message": f"Network '{validated_data['name']}' created successfully.",
                    "network_id": new_network_id,
                    "details": json.loads(json.dumps(created_network, default=str)),
                },
                include_sensitive=include_sensitive,
            )
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
    description=(
        "List configured Wireless LANs (WLANs) on the Unifi Network controller.\n\n"
        "Filters: search (SSID name substring), enabled_only, limit (default 25)."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_wlans(
    search: Annotated[
        Optional[str],
        Field(description="Filter by SSID name (case-insensitive substring match)"),
    ] = None,
    enabled_only: Annotated[
        bool,
        Field(description="If true, only return enabled WLANs. Default false."),
    ] = False,
    limit: Annotated[int, Field(description="Maximum number of WLANs to return (default 25)")] = 25,
) -> Dict[str, Any]:
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

        # Filter by enabled_only
        if enabled_only:
            wlans_raw = [w for w in wlans_raw if w.get("enabled", False)]

        # Filter by search term (SSID name)
        if search and search.strip():
            search_lower = search.strip().lower()
            wlans_raw = [w for w in wlans_raw if search_lower in (w.get("name") or "").lower()]

        total_count = len(wlans_raw)
        wlans_raw = wlans_raw[:limit]

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
            "search": search,
            "enabled_only": enabled_only,
            "total_count": total_count,
            "returned_count": len(formatted_wlans),
            "count": len(formatted_wlans),  # back-compat alias for returned_count
            "limit": limit,
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
    include_sensitive: Annotated[bool, _INCLUDE_SENSITIVE_FIELD] = False,
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
            return redact_sensitive_fields(
                {
                    "success": True,
                    "site": network_manager._connection.site,
                    "wlan_id": wlan_id,
                    "details": json.loads(json.dumps(wlan, default=str)),
                },
                include_sensitive=include_sensitive,
            )
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
    include_sensitive: Annotated[bool, _INCLUDE_SENSITIVE_FIELD] = False,
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

    # Redaction-marker write-back is rejected centrally at the MCP dispatch
    # boundary (StrictKwargFastMCP.call_tool), so no per-field check here.

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
        return redact_sensitive_fields(
            update_preview(
                resource_type="wlan",
                resource_id=wlan_id,
                resource_name=current.get("name"),
                current_state=current,
                updates=validated_data,
            ),
            include_sensitive=include_sensitive,
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
            return redact_sensitive_fields(
                {
                    "success": True,
                    "wlan_id": wlan_id,
                    "updated_fields": updated_fields_list,
                    "details": json.loads(json.dumps(updated_wlan, default=str)),
                },
                include_sensitive=include_sensitive,
            )
        else:
            logger.error("Failed to update WLAN (%s): %s", wlan_id, error_detail)
            wlan_after_update = await network_manager.get_wlan_details(wlan_id)
            return redact_sensitive_fields(
                {
                    "success": False,
                    "wlan_id": wlan_id,
                    "error": f"Failed to update WLAN ({wlan_id}): {error_detail}",
                    "details_after_attempt": json.loads(json.dumps(wlan_after_update, default=str)),
                },
                include_sensitive=include_sensitive,
            )

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
    include_sensitive: Annotated[bool, _INCLUDE_SENSITIVE_FIELD] = False,
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
        return redact_sensitive_fields(
            create_preview(
                resource_type="wlan",
                resource_data=validated_data,
                resource_name=validated_data.get("name"),
                warnings=["Creating a WLAN may temporarily affect wireless connectivity"],
            ),
            include_sensitive=include_sensitive,
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
            return redact_sensitive_fields(
                {
                    "success": True,
                    "site": network_manager._connection.site,
                    "message": f"WLAN '{validated_data['name']}' created successfully.",
                    "wlan_id": new_wlan_id,
                    "details": json.loads(json.dumps(created_wlan, default=str)),
                },
                include_sensitive=include_sensitive,
            )
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
    include_sensitive: Annotated[bool, _INCLUDE_SENSITIVE_FIELD] = False,
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
                    "x_passphrase": wlan.get("x_passphrase"),
                }
                if wlan
                else {"wlan_id": wlan_id}
            )
            resource_name = wlan.get("name", wlan_id) if wlan else wlan_id
        except Exception:
            resource_data = {"wlan_id": wlan_id}
            resource_name = wlan_id

        return redact_sensitive_fields(
            create_preview(
                resource_type="wlan",
                resource_data=resource_data,
                resource_name=resource_name,
                warnings=["All devices using this SSID will be disconnected"],
            ),
            include_sensitive=include_sensitive,
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
