"""Shared field model for Network LAN/VLAN network definitions.

Mirrors the Strawberry type in
``unifi_api.graphql.types.network.network`` (class ``Network``).

- ``Network`` — list_networks + get_network_details +
  create_network + update_network

Factory helpers:
- ``from_controller``      — normalise the raw controller dict → Network
- ``to_controller_create`` — translate a Network → create payload
- ``to_controller_update`` — filter a partial dict to mutable keys only

``MUTABLE_FIELDS`` drives the cross-layer symmetry test: the Strawberry
type must expose every field listed here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Pydantic domain model
# ---------------------------------------------------------------------------


class Network(BaseModel):
    """Canonical Network (LAN/VLAN) model (read + mutable create/update fields)."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="Network UUID (assigned by controller)",
        json_schema_extra={"mutable": False},
    )
    site_id: Optional[str] = Field(
        default=None,
        description="Site ID this network belongs to",
        json_schema_extra={"mutable": False},
    )

    # --- mutable (accepted by create and update) ---
    name: Optional[str] = Field(
        default=None,
        description="Network name",
    )
    purpose: Optional[str] = Field(
        default=None,
        description="Network purpose/type: corporate, guest, wan, vlan-only, vpn-client, vpn-server",
    )
    enabled: Optional[bool] = Field(
        default=None,
        description="Whether the network is enabled",
    )
    vlan_enabled: Optional[bool] = Field(
        default=None,
        description="Whether VLAN tagging is enabled",
    )
    vlan: Optional[str] = Field(
        default=None,
        description="VLAN ID (if VLAN is enabled)",
    )
    ip_subnet: Optional[str] = Field(
        default=None,
        description="IP subnet in host-address-form CIDR (e.g., '192.168.1.1/24')",
    )
    domain_name: Optional[str] = Field(
        default=None,
        description="DNS domain name for the network",
    )
    # DHCP
    dhcpd_enabled: Optional[bool] = Field(
        default=None,
        description="Enable the DHCP server on this network",
    )
    dhcpd_start: Optional[str] = Field(
        default=None,
        description="DHCP range start IP address",
    )
    dhcpd_stop: Optional[str] = Field(
        default=None,
        description="DHCP range end IP address",
    )
    dhcpd_leasetime: Optional[int] = Field(
        default=None,
        description="DHCP lease time in seconds",
    )
    dhcpd_gateway: Optional[str] = Field(
        default=None,
        description="Custom DHCP gateway IP",
    )
    dhcpd_gateway_enabled: Optional[bool] = Field(
        default=None,
        description="Enable custom DHCP gateway",
    )
    dhcpd_dns_1: Optional[str] = Field(
        default=None,
        description="Primary DNS server IP for DHCP clients",
    )
    dhcpd_dns_2: Optional[str] = Field(
        default=None,
        description="Secondary DNS server IP for DHCP clients",
    )
    dhcpd_dns_enabled: Optional[bool] = Field(
        default=None,
        description="Enable custom DNS servers in DHCP",
    )
    dhcpd_ntp_1: Optional[str] = Field(
        default=None,
        description="Primary NTP server IPv4 address for DHCP clients",
    )
    dhcpd_ntp_2: Optional[str] = Field(
        default=None,
        description="Secondary NTP server IPv4 address for DHCP clients",
    )
    dhcpd_ntp_enabled: Optional[bool] = Field(
        default=None,
        description="Enable NTP server option in DHCP responses",
    )
    dhcpd_wins_1: Optional[str] = Field(
        default=None,
        description="Primary WINS server IP for DHCP clients",
    )
    dhcpd_wins_2: Optional[str] = Field(
        default=None,
        description="Secondary WINS server IP for DHCP clients",
    )
    dhcpd_wins_enabled: Optional[bool] = Field(
        default=None,
        description="Enable WINS server option in DHCP responses",
    )
    dhcpd_unifi_controller: Optional[str] = Field(
        default=None,
        description="UniFi controller IP for DHCP option 43",
    )
    dhcpd_tftp_server: Optional[str] = Field(
        default=None,
        description="TFTP server name/IP for DHCP option 150",
    )
    dhcpd_boot_server: Optional[str] = Field(
        default=None,
        description="PXE boot server IP",
    )
    dhcpd_boot_filename: Optional[str] = Field(
        default=None,
        description="PXE boot filename",
    )
    dhcpd_boot_enabled: Optional[bool] = Field(
        default=None,
        description="Enable PXE network boot options in DHCP",
    )
    dhcpd_conflict_checking: Optional[bool] = Field(
        default=None,
        description="Enable DHCP conflict checking",
    )
    dhcp_relay_enabled: Optional[bool] = Field(
        default=None,
        description="Enable DHCP relay instead of local DHCP server",
    )
    dhcpd_ip_1: Optional[str] = Field(
        default=None,
        description="Trusted DHCP server IP for DHCP guard",
    )
    dhcpguard_enabled: Optional[bool] = Field(
        default=None,
        description="Enable DHCP guard (blocks rogue DHCP servers)",
    )
    # Multicast / mDNS
    igmp_snooping: Optional[bool] = Field(
        default=None,
        description="Enable IGMP snooping",
    )
    igmp_querier_switches: Optional[List[Any]] = Field(
        default=None,
        description="List of switches assigned as IGMP queriers",
    )
    igmp_flood_unknown_multicast: Optional[bool] = Field(
        default=None,
        description="Flood unknown multicast traffic to all ports",
    )
    mdns_enabled: Optional[bool] = Field(
        default=None,
        description="Enable mDNS reflection on this network",
    )
    # Access control
    network_isolation_enabled: Optional[bool] = Field(
        default=None,
        description="Enable network isolation (corporate networks only)",
    )
    internet_access_enabled: Optional[bool] = Field(
        default=None,
        description="Allow this network to access the internet",
    )
    upnp_lan_enabled: Optional[bool] = Field(
        default=None,
        description="Enable UPnP on this network",
    )
    # --- WAN uplink (gateway interface; networkconf entries with purpose=wan) ---
    # NOTE: changing connectivity-critical WAN fields can interrupt internet access;
    # the update tool surfaces a warning in its confirm-preview for these.
    wan_type: Optional[str] = Field(
        default=None,
        description="WAN IPv4 addressing type: 'dhcp', 'static', 'pppoe', or 'disabled'",
    )
    wan_networkgroup: Optional[str] = Field(
        default=None,
        description="Physical WAN port group: 'WAN' (primary) or 'WAN2' (secondary)",
    )
    wan_dns_preference: Optional[str] = Field(
        default=None,
        description="WAN DNS source: 'auto' (from ISP) or 'manual'",
    )
    wan_load_balance_type: Optional[str] = Field(
        default=None,
        description="Dual-WAN mode: 'failover-only' or 'weighted' (load balance)",
    )
    wan_load_balance_weight: Optional[int] = Field(
        default=None,
        description="Load-balance weight for this WAN (0-100; used when type is 'weighted')",
    )
    wan_failover_priority: Optional[int] = Field(
        default=None,
        description="Failover priority (lower value = higher priority)",
    )
    wan_smartq_enabled: Optional[bool] = Field(
        default=None,
        description="Enable Smart Queues (QoS / bufferbloat shaping) on this WAN",
    )
    wan_vlan_enabled: Optional[bool] = Field(
        default=None,
        description="Enable VLAN tagging on the WAN uplink (some ISPs require it)",
    )
    igmp_proxy_upstream: Optional[bool] = Field(
        default=None,
        description="Enable IGMP proxy on this WAN (upstream side, for IPTV multicast)",
    )
    igmp_proxy_for: Optional[Any] = Field(
        default=None,
        description="IGMP proxy downstream scope: 'none' (disabled) or a list of network refs (configured)",
    )
    mac_override_enabled: Optional[bool] = Field(
        default=None,
        description="Enable MAC-address clone/override on the WAN interface",
    )
    wan_ip_aliases: Optional[List[Any]] = Field(
        default=None,
        description="Secondary IP aliases on the WAN interface",
    )
    # --- WAN uplink — IPv6 (dual-stack; changing these does not drop IPv4 internet) ---
    ipv6_enabled: Optional[bool] = Field(
        default=None,
        description="Enable IPv6 on the WAN uplink",
    )
    wan_type_v6: Optional[str] = Field(
        default=None,
        description="WAN IPv6 addressing type (e.g. 'disabled', 'dhcpv6', 'slaac', 'static', 'pppoe')",
    )
    ipv6_setting_preference: Optional[str] = Field(
        default=None,
        description="IPv6 settings source: 'auto' or 'manual'",
    )
    ipv6_wan_delegation_type: Optional[str] = Field(
        default=None,
        description="IPv6 prefix-delegation type (e.g. 'none', 'dhcpv6', 'static')",
    )
    wan_dhcpv6_pd_size: Optional[int] = Field(
        default=None,
        description="DHCPv6 prefix-delegation size (prefix length, e.g. 64)",
    )
    wan_dhcpv6_pd_size_auto: Optional[bool] = Field(
        default=None,
        description="Auto-negotiate the DHCPv6 prefix-delegation size",
    )
    wan_ipv6_dns_preference: Optional[str] = Field(
        default=None,
        description="WAN IPv6 DNS source: 'auto' (from ISP) or 'manual'",
    )
    wan_ipv6_dns1: Optional[str] = Field(
        default=None,
        description="Primary WAN IPv6 DNS server (when wan_ipv6_dns_preference='manual')",
    )
    wan_ipv6_dns2: Optional[str] = Field(
        default=None,
        description="Secondary WAN IPv6 DNS server (when wan_ipv6_dns_preference='manual')",
    )


# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------

MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in Network.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in Network.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True) is False
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ---------------------------------------------------------------------------
# Public factory helpers
# ---------------------------------------------------------------------------


def from_controller(raw: Any) -> Network:
    """Build a Network from a controller API response dict."""
    return Network(
        id=_get(raw, "_id") or _get(raw, "id"),
        site_id=_get(raw, "site_id"),
        name=_get(raw, "name"),
        purpose=_get(raw, "purpose"),
        enabled=_get(raw, "enabled"),
        vlan_enabled=_get(raw, "vlan_enabled"),
        vlan=str(_get(raw, "vlan")) if _get(raw, "vlan") is not None else None,
        ip_subnet=_get(raw, "ip_subnet"),
        domain_name=_get(raw, "domain_name"),
        dhcpd_enabled=_get(raw, "dhcpd_enabled"),
        dhcpd_start=_get(raw, "dhcpd_start"),
        dhcpd_stop=_get(raw, "dhcpd_stop"),
        dhcpd_leasetime=_get(raw, "dhcpd_leasetime"),
        dhcpd_gateway=_get(raw, "dhcpd_gateway"),
        dhcpd_gateway_enabled=_get(raw, "dhcpd_gateway_enabled"),
        dhcpd_dns_1=_get(raw, "dhcpd_dns_1"),
        dhcpd_dns_2=_get(raw, "dhcpd_dns_2"),
        dhcpd_dns_enabled=_get(raw, "dhcpd_dns_enabled"),
        dhcpd_ntp_1=_get(raw, "dhcpd_ntp_1"),
        dhcpd_ntp_2=_get(raw, "dhcpd_ntp_2"),
        dhcpd_ntp_enabled=_get(raw, "dhcpd_ntp_enabled"),
        dhcpd_wins_1=_get(raw, "dhcpd_wins_1"),
        dhcpd_wins_2=_get(raw, "dhcpd_wins_2"),
        dhcpd_wins_enabled=_get(raw, "dhcpd_wins_enabled"),
        dhcpd_unifi_controller=_get(raw, "dhcpd_unifi_controller"),
        dhcpd_tftp_server=_get(raw, "dhcpd_tftp_server"),
        dhcpd_boot_server=_get(raw, "dhcpd_boot_server"),
        dhcpd_boot_filename=_get(raw, "dhcpd_boot_filename"),
        dhcpd_boot_enabled=_get(raw, "dhcpd_boot_enabled"),
        dhcpd_conflict_checking=_get(raw, "dhcpd_conflict_checking"),
        dhcp_relay_enabled=_get(raw, "dhcp_relay_enabled"),
        dhcpd_ip_1=_get(raw, "dhcpd_ip_1"),
        dhcpguard_enabled=_get(raw, "dhcpguard_enabled"),
        igmp_snooping=_get(raw, "igmp_snooping"),
        igmp_querier_switches=_get(raw, "igmp_querier_switches"),
        igmp_flood_unknown_multicast=_get(raw, "igmp_flood_unknown_multicast"),
        mdns_enabled=_get(raw, "mdns_enabled"),
        network_isolation_enabled=_get(raw, "network_isolation_enabled"),
        internet_access_enabled=_get(raw, "internet_access_enabled"),
        upnp_lan_enabled=_get(raw, "upnp_lan_enabled"),
        wan_type=_get(raw, "wan_type"),
        wan_networkgroup=_get(raw, "wan_networkgroup"),
        wan_dns_preference=_get(raw, "wan_dns_preference"),
        wan_load_balance_type=_get(raw, "wan_load_balance_type"),
        wan_load_balance_weight=_get(raw, "wan_load_balance_weight"),
        wan_failover_priority=_get(raw, "wan_failover_priority"),
        wan_smartq_enabled=_get(raw, "wan_smartq_enabled"),
        wan_vlan_enabled=_get(raw, "wan_vlan_enabled"),
        igmp_proxy_upstream=_get(raw, "igmp_proxy_upstream"),
        igmp_proxy_for=_get(raw, "igmp_proxy_for"),
        mac_override_enabled=_get(raw, "mac_override_enabled"),
        wan_ip_aliases=_get(raw, "wan_ip_aliases"),
        ipv6_enabled=_get(raw, "ipv6_enabled"),
        wan_type_v6=_get(raw, "wan_type_v6"),
        ipv6_setting_preference=_get(raw, "ipv6_setting_preference"),
        ipv6_wan_delegation_type=_get(raw, "ipv6_wan_delegation_type"),
        wan_dhcpv6_pd_size=_get(raw, "wan_dhcpv6_pd_size"),
        wan_dhcpv6_pd_size_auto=_get(raw, "wan_dhcpv6_pd_size_auto"),
        wan_ipv6_dns_preference=_get(raw, "wan_ipv6_dns_preference"),
        wan_ipv6_dns1=_get(raw, "wan_ipv6_dns1"),
        wan_ipv6_dns2=_get(raw, "wan_ipv6_dns2"),
    )


def to_controller_create(model: Network) -> Dict[str, Any]:
    """Produce a controller create payload from a Network model."""
    payload: Dict[str, Any] = {}
    for field_name in MUTABLE_FIELDS:
        value = getattr(model, field_name, None)
        if value is not None:
            payload[field_name] = value
    return payload


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to only mutable, recognised keys.

    Read-only fields and unrecognised keys are dropped.
    ``None`` values are dropped; boolean ``False`` is preserved.
    """
    return {k: v for k, v in fields.items() if k in MUTABLE_FIELDS and v is not None}
