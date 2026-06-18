"""Strawberry types for network/networks (LAN/VLAN definitions).

Phase 6 PR2 Task 21 migration target. One type per read serializer that used
to live in ``unifi_api.serializers.network.networks``:

- ``Network`` — list_networks + get_network_details

Each type's ``from_manager_output(raw)`` classmethod replaces the dict-shaping
logic that used to live in serializers/network/networks.py. ``to_dict()``
exposes the same dict contract the REST routes return today.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Annotated, Any

import strawberry
from strawberry.types import Info

if TYPE_CHECKING:
    from unifi_api.graphql.types.network.client import Client


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


@strawberry.type(description="A UniFi LAN/VLAN network configuration.")
class Network:
    id: strawberry.ID | None
    name: str | None
    purpose: str | None
    enabled: bool
    vlan_enabled: bool | None
    vlan: str | None
    ip_subnet: str | None
    subnet: str | None  # alias kept for backward compat (mapped from ip_subnet)
    domain_name: str | None
    # DHCP
    dhcpd_enabled: bool | None
    dhcpd_start: str | None
    dhcpd_stop: str | None
    dhcpd_leasetime: int | None
    dhcpd_gateway: str | None
    dhcpd_gateway_enabled: bool | None
    dhcpd_dns_1: str | None
    dhcpd_dns_2: str | None
    dhcpd_dns_enabled: bool | None
    dhcpd_ntp_1: str | None
    dhcpd_ntp_2: str | None
    dhcpd_ntp_enabled: bool | None
    dhcpd_wins_1: str | None
    dhcpd_wins_2: str | None
    dhcpd_wins_enabled: bool | None
    dhcpd_unifi_controller: str | None
    dhcpd_tftp_server: str | None
    dhcpd_boot_server: str | None
    dhcpd_boot_filename: str | None
    dhcpd_boot_enabled: bool | None
    dhcpd_conflict_checking: bool | None
    dhcp_relay_enabled: bool | None
    dhcpd_ip_1: str | None
    dhcpguard_enabled: bool | None
    # Multicast / mDNS
    igmp_snooping: bool | None
    igmp_querier_switches: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    igmp_flood_unknown_multicast: bool | None
    mdns_enabled: bool | None
    # Access control
    network_isolation_enabled: bool | None
    internet_access_enabled: bool | None
    upnp_lan_enabled: bool | None
    # WAN uplink (purpose='wan' networks)
    wan_type: str | None
    wan_networkgroup: str | None
    wan_dns_preference: str | None
    wan_load_balance_type: str | None
    wan_load_balance_weight: int | None
    wan_failover_priority: int | None
    wan_smartq_enabled: bool | None
    wan_vlan_enabled: bool | None
    igmp_proxy_upstream: bool | None
    igmp_proxy_for: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    mac_override_enabled: bool | None
    wan_ip_aliases: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    # WAN uplink — IPv6
    ipv6_enabled: bool | None
    wan_type_v6: str | None
    ipv6_setting_preference: str | None
    ipv6_wan_delegation_type: str | None
    wan_dhcpv6_pd_size: int | None
    wan_dhcpv6_pd_size_auto: bool | None
    wan_ipv6_dns_preference: str | None
    wan_ipv6_dns1: str | None
    wan_ipv6_dns2: str | None

    # Context for relationship edges — NOT in SDL, NOT in to_dict().
    _controller_id: strawberry.Private[str | None] = None
    _site: strawberry.Private[str | None] = None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "purpose", "vlan", "subnet", "enabled"],
            "sort_default": "name:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "Network":
        raw = getattr(obj, "raw", obj if isinstance(obj, dict) else {})
        ip_subnet = raw.get("ip_subnet") or raw.get("subnet")
        vlan_raw = raw.get("vlan")
        return cls(
            id=raw.get("_id") or raw.get("id"),
            name=raw.get("name"),
            purpose=raw.get("purpose"),
            enabled=bool(raw.get("enabled", False)),
            vlan_enabled=raw.get("vlan_enabled"),
            vlan=str(vlan_raw) if vlan_raw is not None else None,
            ip_subnet=ip_subnet,
            subnet=ip_subnet,
            domain_name=raw.get("domain_name"),
            dhcpd_enabled=raw.get("dhcpd_enabled"),
            dhcpd_start=raw.get("dhcpd_start"),
            dhcpd_stop=raw.get("dhcpd_stop"),
            dhcpd_leasetime=raw.get("dhcpd_leasetime"),
            dhcpd_gateway=raw.get("dhcpd_gateway"),
            dhcpd_gateway_enabled=raw.get("dhcpd_gateway_enabled"),
            dhcpd_dns_1=raw.get("dhcpd_dns_1"),
            dhcpd_dns_2=raw.get("dhcpd_dns_2"),
            dhcpd_dns_enabled=raw.get("dhcpd_dns_enabled"),
            dhcpd_ntp_1=raw.get("dhcpd_ntp_1"),
            dhcpd_ntp_2=raw.get("dhcpd_ntp_2"),
            dhcpd_ntp_enabled=raw.get("dhcpd_ntp_enabled"),
            dhcpd_wins_1=raw.get("dhcpd_wins_1"),
            dhcpd_wins_2=raw.get("dhcpd_wins_2"),
            dhcpd_wins_enabled=raw.get("dhcpd_wins_enabled"),
            dhcpd_unifi_controller=raw.get("dhcpd_unifi_controller"),
            dhcpd_tftp_server=raw.get("dhcpd_tftp_server"),
            dhcpd_boot_server=raw.get("dhcpd_boot_server"),
            dhcpd_boot_filename=raw.get("dhcpd_boot_filename"),
            dhcpd_boot_enabled=raw.get("dhcpd_boot_enabled"),
            dhcpd_conflict_checking=raw.get("dhcpd_conflict_checking"),
            dhcp_relay_enabled=raw.get("dhcp_relay_enabled"),
            dhcpd_ip_1=raw.get("dhcpd_ip_1"),
            dhcpguard_enabled=raw.get("dhcpguard_enabled"),
            igmp_snooping=raw.get("igmp_snooping"),
            igmp_querier_switches=raw.get("igmp_querier_switches"),
            igmp_flood_unknown_multicast=raw.get("igmp_flood_unknown_multicast"),
            mdns_enabled=raw.get("mdns_enabled"),
            network_isolation_enabled=raw.get("network_isolation_enabled"),
            internet_access_enabled=raw.get("internet_access_enabled"),
            upnp_lan_enabled=raw.get("upnp_lan_enabled"),
            wan_type=raw.get("wan_type"),
            wan_networkgroup=raw.get("wan_networkgroup"),
            wan_dns_preference=raw.get("wan_dns_preference"),
            wan_load_balance_type=raw.get("wan_load_balance_type"),
            wan_load_balance_weight=raw.get("wan_load_balance_weight"),
            wan_failover_priority=raw.get("wan_failover_priority"),
            wan_smartq_enabled=raw.get("wan_smartq_enabled"),
            wan_vlan_enabled=raw.get("wan_vlan_enabled"),
            igmp_proxy_upstream=raw.get("igmp_proxy_upstream"),
            igmp_proxy_for=raw.get("igmp_proxy_for"),
            mac_override_enabled=raw.get("mac_override_enabled"),
            wan_ip_aliases=raw.get("wan_ip_aliases"),
            ipv6_enabled=raw.get("ipv6_enabled"),
            wan_type_v6=raw.get("wan_type_v6"),
            ipv6_setting_preference=raw.get("ipv6_setting_preference"),
            ipv6_wan_delegation_type=raw.get("ipv6_wan_delegation_type"),
            wan_dhcpv6_pd_size=raw.get("wan_dhcpv6_pd_size"),
            wan_dhcpv6_pd_size_auto=raw.get("wan_dhcpv6_pd_size_auto"),
            wan_ipv6_dns_preference=raw.get("wan_ipv6_dns_preference"),
            wan_ipv6_dns1=raw.get("wan_ipv6_dns1"),
            wan_ipv6_dns2=raw.get("wan_ipv6_dns2"),
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: v for k, v in out.items() if not k.startswith("_") and not callable(v)}

    @strawberry.field(description="Clients on this network.")
    async def clients(
        self,
        info: Info,
    ) -> list[Annotated["Client", strawberry.lazy("unifi_api.graphql.types.network.client")]]:
        """Resolves to clients whose network_id matches this network's id."""
        from unifi_api.graphql.resolvers.network import _fetch_clients
        from unifi_api.graphql.types.network.client import Client

        if not self._controller_id:
            return []
        site = self._site or "default"
        raw_clients = await _fetch_clients(info.context, self._controller_id, site)
        out: list[Client] = []
        for c in raw_clients:
            if isinstance(c, dict):
                net_id = c.get("network_id")
            else:
                raw = getattr(c, "raw", None)
                net_id = raw.get("network_id") if isinstance(raw, dict) else getattr(c, "network_id", None)
            if net_id == self.id:
                inst = Client.from_manager_output(c)
                inst._controller_id = self._controller_id
                inst._site = site
                out.append(inst)
        return out
