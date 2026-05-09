"""NetworkQuery — read-only GraphQL resolvers for the UniFi Network product.

Phase 6 PR2.5 Cluster A — adds DETAIL counterparts and remaining LIST
resolvers for the client / device / network type domains. Builds on the
foundation laid by Task 25a (PR2):

- Fetch helpers route through the request-scoped ``RequestCache`` so
  multi-resolver queries dedupe.
- Page wrappers carry pagination cursors per LIST resolver.
- DETAIL resolvers reuse the cached LIST snapshots where the manager
  exposes a snapshot method; per-id manager calls (``get_device_radio``,
  ``get_lldp_neighbors``, ``get_speedtest_status``) get their own keyed
  cache entries so distinct macs don't collide.

Cluster B+ (vpn/dns/routes/firewall/etc.) and relationship edges land in
follow-up dispatches.
"""

from __future__ import annotations

from typing import Any

import strawberry
from strawberry.types import Info

from unifi_api.graphql.context import GraphQLContext
from unifi_api.graphql.permissions import IsRead
from unifi_api.graphql.types.network.client import (
    BlockedClient,
    Client,
    ClientLookup,
)
from unifi_api.graphql.types.network.device import (
    AvailableChannel,
    Device,
    DeviceRadio,
    LldpNeighbors,
    PduOutlets,
    RfScanResult,
    RogueAp,
    SpeedtestStatus,
)
from unifi_api.graphql.types.network.acl import AclRule
from unifi_api.graphql.types.network.ap_group import ApGroup
from unifi_api.graphql.types.network.client_group import ClientGroup, UserGroup
from unifi_api.graphql.types.network.content_filter import ContentFilter
from unifi_api.graphql.types.network.dns import DnsRecord
from unifi_api.graphql.types.network.dpi import DpiApplication, DpiCategory
from unifi_api.graphql.types.network.firewall import (
    FirewallGroup,
    FirewallRule,
    FirewallZone,
)
from unifi_api.graphql.types.network.network import Network
from unifi_api.graphql.types.network.oon import OonPolicy
from unifi_api.graphql.types.network.port_forward import PortForward
from unifi_api.graphql.types.network.qos import QosRule
from unifi_api.graphql.types.network.route import (
    ActiveRoute,
    Route,
    TrafficRoute,
)
from unifi_api.graphql.types.network.event import EventLog
from unifi_api.graphql.types.network.session import (
    ClientSession,
    ClientWifiDetails,
)
from unifi_api.graphql.types.network.stat import DpiStats, StatPoint
from unifi_api.graphql.types.network.switch import (
    PortProfile,
    PortStats,
    SwitchCapabilities,
    SwitchPorts,
)
from unifi_api.graphql.types.network.system import (
    Alarm,
    AutoBackupSettings,
    Backup,
    EventTypes,
    NetworkHealth,
    SiteSettings,
    SnmpSettings,
    SpeedtestResult,
    SystemInfo,
    TopClient,
)
from unifi_api.graphql.types.network.voucher import Voucher
from unifi_api.graphql.types.network.vpn import VpnClient, VpnServer
from unifi_api.graphql.types.network.wlan import Wlan


# ---------------------------------------------------------------------------
# Fetch helpers — each goes through ctx.cache.get_or_fetch so concurrent
# resolvers in the same request share a single manager round-trip.
# ---------------------------------------------------------------------------


async def _fetch_clients(ctx: GraphQLContext, controller: str, site: str) -> list:
    key = f"network/clients/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "client_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_clients())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_devices(ctx: GraphQLContext, controller: str, site: str) -> list:
    key = f"network/devices/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "device_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_devices())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_networks(ctx: GraphQLContext, controller: str, site: str) -> list:
    key = f"network/networks/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "network_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_networks())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_blocked_clients(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/blocked-clients/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "client_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_blocked_clients())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_client_by_ip(
    ctx: GraphQLContext, controller: str, site: str, ip: str,
) -> Any:
    key = f"network/client-by-ip/{controller}/{site}/{ip}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "client_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return await mgr.get_client_by_ip(ip)

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_device_radio(
    ctx: GraphQLContext, controller: str, site: str, mac: str,
) -> Any:
    key = f"network/device-radio/{controller}/{site}/{mac}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "device_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return await mgr.get_device_radio(mac)

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_lldp_neighbors(
    ctx: GraphQLContext, controller: str, site: str, device_mac: str,
) -> Any:
    key = f"network/lldp-neighbors/{controller}/{site}/{device_mac}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "switch_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return await mgr.get_lldp_neighbors(device_mac)

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_pdu_outlets(
    ctx: GraphQLContext, controller: str, site: str, mac: str,
) -> Any:
    key = f"network/pdu-outlets/{controller}/{site}/{mac}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "device_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return await mgr.get_pdu_outlets(mac)

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_rogue_aps(
    ctx: GraphQLContext, controller: str, site: str, within_hours: int = 24,
) -> list:
    key = f"network/rogue-aps/{controller}/{site}/{within_hours}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "device_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.list_rogue_aps(within_hours))

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_rf_scan_results(
    ctx: GraphQLContext, controller: str, site: str, ap_mac: str,
) -> list:
    key = f"network/rf-scan-results/{controller}/{site}/{ap_mac}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "device_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_rf_scan_results(ap_mac) or [])

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_available_channels(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/available-channels/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "device_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.list_available_channels() or [])

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_speedtest_status(
    ctx: GraphQLContext, controller: str, site: str, gateway_mac: str,
) -> Any:
    key = f"network/speedtest-status/{controller}/{site}/{gateway_mac}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "device_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return await mgr.get_speedtest_status(gateway_mac)

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_network_health(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/network-health/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "system_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_network_health() or [])

    return await ctx.cache.get_or_fetch(key, _do)


# ---- Cluster B fetch helpers (wlan / vpn / dns / routes) -----------------


async def _fetch_wlans(ctx: GraphQLContext, controller: str, site: str) -> list:
    key = f"network/wlans/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "network_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_wlans())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_vpn_clients(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/vpn-clients/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "vpn_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_vpn_clients())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_vpn_servers(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/vpn-servers/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "vpn_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_vpn_servers())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_dns_records(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/dns-records/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "dns_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.list_dns_records())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_routes(ctx: GraphQLContext, controller: str, site: str) -> list:
    key = f"network/routes/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "routing_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_routes())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_active_routes(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/active-routes/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "routing_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_active_routes())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_traffic_routes(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/traffic-routes/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "traffic_route_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_traffic_routes())

    return await ctx.cache.get_or_fetch(key, _do)


# ---- Cluster C fetch helpers (firewall / qos / dpi / cf / acl / oon / pf) -


async def _fetch_firewall_policies(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/firewall-policies/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "firewall_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_firewall_policies(include_predefined=True))

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_firewall_groups(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/firewall-groups/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "firewall_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_firewall_groups())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_firewall_zones(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/firewall-zones/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "firewall_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_firewall_zones())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_qos_rules(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/qos-rules/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "qos_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_qos_rules())

    return await ctx.cache.get_or_fetch(key, _do)


def _unwrap_dpi(result: Any) -> list:
    """Extract bare list from a paginated DPI wrapper or pass through."""
    if isinstance(result, dict) and "data" in result:
        data = result.get("data") or []
        return list(data) if isinstance(data, list) else []
    if isinstance(result, list):
        return result
    return []


async def _fetch_dpi_applications(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/dpi-applications/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "dpi_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            result = await mgr.get_dpi_applications(limit=2500, offset=0)
            return _unwrap_dpi(result)

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_dpi_categories(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/dpi-categories/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "dpi_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            result = await mgr.get_dpi_categories(limit=500, offset=0)
            return _unwrap_dpi(result)

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_content_filters(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/content-filters/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "content_filter_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_content_filters())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_acl_rules(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/acl-rules/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "acl_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_acl_rules())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_oon_policies(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/oon-policies/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "oon_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_oon_policies())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_port_forwards(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/port-forwards/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "firewall_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_port_forwards())

    return await ctx.cache.get_or_fetch(key, _do)


# ---- Cluster D fetch helpers (stats / events / system / vouchers / sessions) ---


async def _stats_mgr_fetch(
    ctx: GraphQLContext,
    controller: str,
    site: str,
    cache_key: str,
    method: str,
    *args: Any,
):
    async def _do():
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "stats_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return await getattr(mgr, method)(*args)

    return await ctx.cache.get_or_fetch(cache_key, _do)


async def _fetch_dashboard_stats(
    ctx: GraphQLContext, controller: str, site: str, duration_hours: int,
) -> list:
    key = f"network/dashboard-stats/{controller}/{site}/{duration_hours}"
    return await _stats_mgr_fetch(ctx, controller, site, key, "get_dashboard")


async def _fetch_network_stats(
    ctx: GraphQLContext, controller: str, site: str, duration_hours: int,
) -> list:
    key = f"network/network-stats/{controller}/{site}/{duration_hours}"
    return await _stats_mgr_fetch(
        ctx, controller, site, key, "get_network_stats", duration_hours,
    )


async def _fetch_gateway_stats(
    ctx: GraphQLContext, controller: str, site: str, duration_hours: int,
) -> list:
    key = f"network/gateway-stats/{controller}/{site}/{duration_hours}"
    return await _stats_mgr_fetch(
        ctx, controller, site, key, "get_gateway_stats", duration_hours,
    )


async def _fetch_client_stats(
    ctx: GraphQLContext, controller: str, site: str, mac: str, duration_hours: int,
) -> list:
    key = f"network/client-stats/{controller}/{site}/{mac}/{duration_hours}"
    return await _stats_mgr_fetch(
        ctx, controller, site, key, "get_client_stats", mac, duration_hours,
    )


async def _fetch_device_stats(
    ctx: GraphQLContext, controller: str, site: str, mac: str, duration_hours: int,
) -> list:
    key = f"network/device-stats/{controller}/{site}/{mac}/{duration_hours}"
    return await _stats_mgr_fetch(
        ctx, controller, site, key, "get_device_stats", mac, duration_hours,
    )


async def _fetch_client_dpi_traffic(
    ctx: GraphQLContext, controller: str, site: str, mac: str,
) -> list:
    key = f"network/client-dpi-traffic/{controller}/{site}/{mac}"
    return await _stats_mgr_fetch(
        ctx, controller, site, key, "get_client_dpi_traffic", mac,
    )


async def _fetch_site_dpi_traffic(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/site-dpi-traffic/{controller}/{site}"
    return await _stats_mgr_fetch(
        ctx, controller, site, key, "get_site_dpi_traffic",
    )


async def _fetch_dpi_stats(
    ctx: GraphQLContext, controller: str, site: str,
) -> Any:
    key = f"network/dpi-stats/{controller}/{site}"
    return await _stats_mgr_fetch(ctx, controller, site, key, "get_dpi_stats")


async def _fetch_alerts(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/alerts/{controller}/{site}"
    return await _stats_mgr_fetch(ctx, controller, site, key, "get_alerts")


async def _fetch_anomalies(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/anomalies/{controller}/{site}"
    return await _stats_mgr_fetch(ctx, controller, site, key, "get_anomalies")


async def _fetch_ips_events(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/ips-events/{controller}/{site}"
    return await _stats_mgr_fetch(ctx, controller, site, key, "get_ips_events")


async def _fetch_top_clients(
    ctx: GraphQLContext, controller: str, site: str, duration_hours: int,
) -> list:
    key = f"network/top-clients/{controller}/{site}/{duration_hours}"
    return await _stats_mgr_fetch(
        ctx, controller, site, key, "get_top_clients", duration_hours,
    )


async def _fetch_speedtest_results(
    ctx: GraphQLContext, controller: str, site: str, duration_hours: int,
) -> list:
    key = f"network/speedtest-results/{controller}/{site}/{duration_hours}"
    return await _stats_mgr_fetch(
        ctx, controller, site, key, "get_speedtest_results", duration_hours,
    )


async def _fetch_client_sessions(
    ctx: GraphQLContext,
    controller: str,
    site: str,
    mac: str | None,
    duration_hours: int,
) -> list:
    mac_part = mac or "all"
    key = f"network/client-sessions/{controller}/{site}/{mac_part}/{duration_hours}"
    return await _stats_mgr_fetch(
        ctx, controller, site, key, "get_client_sessions", mac, duration_hours,
    )


async def _fetch_client_wifi_details(
    ctx: GraphQLContext, controller: str, site: str, mac: str,
) -> Any:
    key = f"network/client-wifi-details/{controller}/{site}/{mac}"
    return await _stats_mgr_fetch(
        ctx, controller, site, key, "get_client_wifi_details", mac,
    )


async def _event_mgr_fetch(
    ctx: GraphQLContext,
    controller: str,
    site: str,
    cache_key: str,
    method: str,
    *args: Any,
):
    async def _do():
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "event_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return await getattr(mgr, method)(*args)

    return await ctx.cache.get_or_fetch(cache_key, _do)


async def _fetch_event_log(
    ctx: GraphQLContext, controller: str, site: str, fetch_limit: int,
) -> list:
    key = f"network/event-log/{controller}/{site}/{fetch_limit}"

    async def _do():
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "event_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_events(limit=fetch_limit))

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_alarms(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/alarms/{controller}/{site}"
    return await _event_mgr_fetch(ctx, controller, site, key, "get_alarms")


async def _fetch_event_types(
    ctx: GraphQLContext, controller: str, site: str,
) -> Any:
    key = f"network/event-types/{controller}/{site}"

    async def _do():
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "event_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            import inspect as _inspect

            result = mgr.get_event_type_prefixes()
            if _inspect.isawaitable(result):
                result = await result
            return result

    return await ctx.cache.get_or_fetch(key, _do)


async def _system_mgr_fetch(
    ctx: GraphQLContext,
    controller: str,
    site: str,
    cache_key: str,
    method: str,
    *args: Any,
):
    async def _do():
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "system_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return await getattr(mgr, method)(*args)

    return await ctx.cache.get_or_fetch(cache_key, _do)


async def _fetch_system_info(
    ctx: GraphQLContext, controller: str, site: str,
) -> Any:
    key = f"network/system-info/{controller}/{site}"
    return await _system_mgr_fetch(ctx, controller, site, key, "get_system_info")


async def _fetch_site_settings(
    ctx: GraphQLContext, controller: str, site: str,
) -> Any:
    key = f"network/site-settings/{controller}/{site}"
    return await _system_mgr_fetch(ctx, controller, site, key, "get_site_settings")


async def _fetch_snmp_settings(
    ctx: GraphQLContext, controller: str, site: str,
) -> Any:
    key = f"network/snmp-settings/{controller}/{site}"
    return await _system_mgr_fetch(
        ctx, controller, site, key, "get_settings", "snmp",
    )


async def _fetch_autobackup_settings(
    ctx: GraphQLContext, controller: str, site: str,
) -> Any:
    key = f"network/autobackup-settings/{controller}/{site}"
    return await _system_mgr_fetch(
        ctx, controller, site, key, "get_autobackup_settings",
    )


async def _fetch_backups(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/backups/{controller}/{site}"
    return await _system_mgr_fetch(ctx, controller, site, key, "list_backups")


async def _hotspot_mgr_fetch(
    ctx: GraphQLContext,
    controller: str,
    site: str,
    cache_key: str,
    method: str,
    *args: Any,
):
    async def _do():
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "hotspot_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return await getattr(mgr, method)(*args)

    return await ctx.cache.get_or_fetch(cache_key, _do)


async def _fetch_vouchers(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/vouchers/{controller}/{site}"

    async def _do():
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "hotspot_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_vouchers())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_voucher_details(
    ctx: GraphQLContext, controller: str, site: str, voucher_id: str,
) -> Any:
    key = f"network/voucher-details/{controller}/{site}/{voucher_id}"
    return await _hotspot_mgr_fetch(
        ctx, controller, site, key, "get_voucher_details", voucher_id,
    )


# ---- Switch / AP groups / Client groups domain (Cluster E) -----------------


async def _fetch_port_profiles(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/port-profiles/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "switch_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_port_profiles())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_switch_ports(
    ctx: GraphQLContext, controller: str, site: str, device_mac: str,
) -> Any:
    key = f"network/switch-ports/{controller}/{site}/{device_mac}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "switch_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return await mgr.get_switch_ports(device_mac)

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_port_stats(
    ctx: GraphQLContext, controller: str, site: str, device_mac: str,
) -> Any:
    key = f"network/port-stats/{controller}/{site}/{device_mac}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "switch_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return await mgr.get_port_stats(device_mac)

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_switch_capabilities(
    ctx: GraphQLContext, controller: str, site: str, device_mac: str,
) -> Any:
    key = f"network/switch-capabilities/{controller}/{site}/{device_mac}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "switch_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return await mgr.get_switch_capabilities(device_mac)

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_ap_groups(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/ap-groups/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "network_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.list_ap_groups())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_client_groups(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/client-groups/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "client_group_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_client_groups())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_user_groups(
    ctx: GraphQLContext, controller: str, site: str,
) -> list:
    key = f"network/user-groups/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "usergroup_manager",
            )
            cm = await ctx.manager_factory.get_connection_manager(
                session, controller, "network",
            )
            if cm.site != site:
                await cm.set_site(site)
            return list(await mgr.get_usergroups())

    return await ctx.cache.get_or_fetch(key, _do)


# ---------------------------------------------------------------------------
# Page wrappers
# ---------------------------------------------------------------------------


@strawberry.type(description="Paginated page of clients.")
class ClientPage:
    items: list[Client]
    next_cursor: str | None


@strawberry.type(description="Paginated page of devices.")
class DevicePage:
    items: list[Device]
    next_cursor: str | None


@strawberry.type(description="Paginated page of network configurations.")
class NetworkPage:
    items: list[Network]
    next_cursor: str | None


@strawberry.type(description="Paginated page of blocked clients.")
class BlockedClientPage:
    items: list[BlockedClient]
    next_cursor: str | None


@strawberry.type(description="Paginated page of detected rogue APs.")
class RogueApPage:
    items: list[RogueAp]
    next_cursor: str | None


@strawberry.type(description="Paginated page of WLAN/SSID configurations.")
class WlanPage:
    items: list[Wlan]
    next_cursor: str | None


@strawberry.type(description="Paginated page of VPN clients.")
class VpnClientPage:
    items: list[VpnClient]
    next_cursor: str | None


@strawberry.type(description="Paginated page of VPN servers.")
class VpnServerPage:
    items: list[VpnServer]
    next_cursor: str | None


@strawberry.type(description="Paginated page of DNS records.")
class DnsRecordPage:
    items: list[DnsRecord]
    next_cursor: str | None


@strawberry.type(description="Paginated page of static routes.")
class RoutePage:
    items: list[Route]
    next_cursor: str | None


@strawberry.type(description="Paginated page of active kernel routes.")
class ActiveRoutePage:
    items: list[ActiveRoute]
    next_cursor: str | None


@strawberry.type(description="Paginated page of traffic-route policies.")
class TrafficRoutePage:
    items: list[TrafficRoute]
    next_cursor: str | None


@strawberry.type(description="Paginated page of firewall policies/rules.")
class FirewallRulePage:
    items: list[FirewallRule]
    next_cursor: str | None


@strawberry.type(description="Paginated page of firewall groups.")
class FirewallGroupPage:
    items: list[FirewallGroup]
    next_cursor: str | None


@strawberry.type(description="Paginated page of QoS rules.")
class QosRulePage:
    items: list[QosRule]
    next_cursor: str | None


@strawberry.type(description="Paginated page of DPI applications.")
class DpiApplicationPage:
    items: list[DpiApplication]
    next_cursor: str | None


@strawberry.type(description="Paginated page of DPI categories.")
class DpiCategoryPage:
    items: list[DpiCategory]
    next_cursor: str | None


@strawberry.type(description="Paginated page of content filters.")
class ContentFilterPage:
    items: list[ContentFilter]
    next_cursor: str | None


@strawberry.type(description="Paginated page of ACL rules.")
class AclRulePage:
    items: list[AclRule]
    next_cursor: str | None


@strawberry.type(description="Paginated page of OON (out-of-network) policies.")
class OonPolicyPage:
    items: list[OonPolicy]
    next_cursor: str | None


@strawberry.type(description="Paginated page of port forwards.")
class PortForwardPage:
    items: list[PortForward]
    next_cursor: str | None


@strawberry.type(description="Paginated page of event-log entries.")
class EventLogPage:
    items: list[EventLog]
    next_cursor: str | None


@strawberry.type(description="Paginated page of controller alarms.")
class AlarmPage:
    items: list[Alarm]
    next_cursor: str | None


@strawberry.type(description="Paginated page of controller backup descriptors.")
class BackupPage:
    items: list[Backup]
    next_cursor: str | None


@strawberry.type(description="Paginated page of speedtest result entries.")
class SpeedtestResultPage:
    items: list[SpeedtestResult]
    next_cursor: str | None


@strawberry.type(description="Paginated page of hotspot vouchers.")
class VoucherPage:
    items: list[Voucher]
    next_cursor: str | None


@strawberry.type(description="Paginated page of client association sessions.")
class ClientSessionPage:
    items: list[ClientSession]
    next_cursor: str | None


@strawberry.type(description="Paginated page of switch port profiles.")
class PortProfilePage:
    items: list[PortProfile]
    next_cursor: str | None


@strawberry.type(description="Paginated page of AP groups.")
class ApGroupPage:
    items: list[ApGroup]
    next_cursor: str | None


@strawberry.type(description="Paginated page of network member client groups.")
class ClientGroupPage:
    items: list[ClientGroup]
    next_cursor: str | None


@strawberry.type(description="Paginated page of QoS user groups.")
class UserGroupPage:
    items: list[UserGroup]
    next_cursor: str | None


# ---------------------------------------------------------------------------
# Key extractors — operate on raw manager outputs (objects or dicts).
# Each returns (timestamp_or_zero, secondary_id) for stable descending sort.
# ---------------------------------------------------------------------------


def _raw(obj: Any) -> Any:
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw
    if isinstance(obj, dict):
        return obj
    return obj


def _client_key(c: Any) -> tuple:
    raw = _raw(c)
    if isinstance(raw, dict):
        ts = raw.get("last_seen")
        mac = raw.get("mac")
    else:
        ts = getattr(raw, "last_seen", None)
        mac = getattr(raw, "mac", None)
    return (int(ts or 0), str(mac or ""))


def _device_key(d: Any) -> tuple:
    raw = _raw(d)
    if isinstance(raw, dict):
        mac = raw.get("mac")
        name = raw.get("name")
    else:
        mac = getattr(raw, "mac", None)
        name = getattr(raw, "name", None)
    # Devices have no natural timestamp; sort by name desc with mac as tiebreaker.
    # Use 0 for the ts slot so paginate's ordering remains deterministic.
    return (0, f"{name or ''}|{mac or ''}")


def _network_key(n: Any) -> tuple:
    raw = _raw(n)
    if isinstance(raw, dict):
        nid = raw.get("_id") or raw.get("id")
        name = raw.get("name")
    else:
        nid = getattr(raw, "_id", None) or getattr(raw, "id", None)
        name = getattr(raw, "name", None)
    return (0, f"{name or ''}|{nid or ''}")


def _blocked_key(c: Any) -> tuple:
    raw = _raw(c)
    if isinstance(raw, dict):
        ts = raw.get("last_seen")
        mac = raw.get("mac")
    else:
        ts = getattr(raw, "last_seen", None)
        mac = getattr(raw, "mac", None)
    return (int(ts or 0), str(mac or ""))


def _id_key(obj: Any) -> tuple:
    raw = _raw(obj)
    if isinstance(raw, dict):
        oid = raw.get("_id") or raw.get("id")
    else:
        oid = getattr(raw, "_id", None) or getattr(raw, "id", None)
    return (0, str(oid or ""))


def _active_route_key(row: Any) -> tuple:
    raw = _raw(row)
    if isinstance(raw, dict):
        pfx = raw.get("pfx") or raw.get("target_subnet") or raw.get("network")
    else:
        pfx = (
            getattr(raw, "pfx", None)
            or getattr(raw, "target_subnet", None)
            or getattr(raw, "network", None)
        )
    return (0, str(pfx or ""))


def _bssid_key(row: Any) -> tuple:
    raw = _raw(row)
    if isinstance(raw, dict):
        ts = raw.get("last_seen")
        bssid = raw.get("bssid")
    else:
        ts = getattr(raw, "last_seen", None)
        bssid = getattr(raw, "bssid", None)
    return (int(ts or 0), str(bssid or ""))


def _event_key(row: Any) -> tuple:
    """Sort key for event/alarm rows: time desc, id tiebreaker."""
    raw = _raw(row)
    if isinstance(raw, dict):
        ts = raw.get("time") or raw.get("timestamp")
        rid = raw.get("_id") or raw.get("id") or raw.get("key") or ""
    else:
        ts = getattr(raw, "time", None) or getattr(raw, "timestamp", None)
        rid = (
            getattr(raw, "_id", None)
            or getattr(raw, "id", None)
            or getattr(raw, "key", None)
            or ""
        )
    return (int(ts or 0), str(rid))


def _backup_key(row: Any) -> tuple:
    raw = _raw(row)
    if isinstance(raw, dict):
        ts = raw.get("time") or raw.get("datetime") or raw.get("timestamp")
        name = raw.get("filename") or raw.get("name") or raw.get("_id") or ""
    else:
        ts = (
            getattr(raw, "time", None)
            or getattr(raw, "datetime", None)
            or getattr(raw, "timestamp", None)
        )
        name = (
            getattr(raw, "filename", None)
            or getattr(raw, "name", None)
            or getattr(raw, "_id", None)
            or ""
        )
    return (int(ts or 0), str(name))


def _voucher_key(row: Any) -> tuple:
    raw = _raw(row)
    if isinstance(raw, dict):
        ts = raw.get("create_time") or raw.get("created_at")
        vid = raw.get("_id") or raw.get("id") or raw.get("code") or ""
    else:
        ts = getattr(raw, "create_time", None) or getattr(raw, "created_at", None)
        vid = (
            getattr(raw, "_id", None)
            or getattr(raw, "id", None)
            or getattr(raw, "code", None)
            or ""
        )
    return (int(ts or 0), str(vid))


def _session_key(row: Any) -> tuple:
    raw = _raw(row)
    if isinstance(raw, dict):
        ts = raw.get("assoc_time") or raw.get("connected_at") or raw.get("first_seen")
        mac = raw.get("mac") or ""
    else:
        ts = (
            getattr(raw, "assoc_time", None)
            or getattr(raw, "connected_at", None)
            or getattr(raw, "first_seen", None)
        )
        mac = getattr(raw, "mac", None) or ""
    return (int(ts or 0), str(mac))


def _speedtest_key(row: Any) -> tuple:
    raw = _raw(row)
    if isinstance(raw, dict):
        ts = raw.get("time") or raw.get("timestamp") or raw.get("ts")
        rid = raw.get("_id") or raw.get("id") or ""
    else:
        ts = (
            getattr(raw, "time", None)
            or getattr(raw, "timestamp", None)
            or getattr(raw, "ts", None)
        )
        rid = getattr(raw, "_id", None) or getattr(raw, "id", None) or ""
    return (int(ts or 0), str(rid))


# ---------------------------------------------------------------------------
# NetworkQuery
# ---------------------------------------------------------------------------


def _decode_cursor(cursor: str | None):
    """Translate an opaque cursor string to a Cursor (or raise ValueError)."""
    from unifi_api.services.pagination import Cursor, InvalidCursor

    if not cursor:
        return None
    try:
        return Cursor.decode(cursor)
    except InvalidCursor:
        raise ValueError("invalid cursor")


@strawberry.type(description="Read-only access to UniFi Network resources.")
class NetworkQuery:
    # ---- Client domain ---------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List clients on the given controller/site (paginated).",
    )
    async def clients(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> ClientPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_clients(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_client_key,
        )
        items = []
        for c in page:
            inst = Client.from_manager_output(c)
            inst._controller_id = controller
            inst._site = site
            items.append(inst)
        return ClientPage(
            items=items,
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single client by MAC address.",
    )
    async def client(
        self,
        info: Info,
        controller: strawberry.ID,
        mac: strawberry.ID,
        site: str = "default",
    ) -> Client | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_clients(ctx, controller, site)
        for c in raw:
            r = _raw(c)
            c_mac = r.get("mac") if isinstance(r, dict) else getattr(r, "mac", None)
            if c_mac == mac:
                inst = Client.from_manager_output(c)
                inst._controller_id = controller
                inst._site = site
                return inst
        return None

    @strawberry.field(
        permission_classes=[IsRead],
        description="List clients currently blocked from the network (paginated).",
    )
    async def blocked_clients(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> BlockedClientPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_blocked_clients(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_blocked_key,
        )
        return BlockedClientPage(
            items=[BlockedClient.from_manager_output(c) for c in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a client by IP address (online-presence check).",
    )
    async def client_by_ip(
        self,
        info: Info,
        controller: strawberry.ID,
        ip: str,
        site: str = "default",
    ) -> ClientLookup | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_client_by_ip(ctx, controller, site, ip)
        if raw is None:
            return None
        return ClientLookup.from_manager_output(raw)

    # ---- Device domain ---------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List devices on the given controller/site (paginated).",
    )
    async def devices(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> DevicePage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_devices(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_device_key,
        )
        items = []
        for d in page:
            inst = Device.from_manager_output(d)
            inst._controller_id = controller
            inst._site = site
            items.append(inst)
        return DevicePage(
            items=items,
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single device by MAC address.",
    )
    async def device(
        self,
        info: Info,
        controller: strawberry.ID,
        mac: strawberry.ID,
        site: str = "default",
    ) -> Device | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_devices(ctx, controller, site)
        for d in raw:
            r = _raw(d)
            d_mac = r.get("mac") if isinstance(r, dict) else getattr(r, "mac", None)
            if d_mac == mac:
                inst = Device.from_manager_output(d)
                inst._controller_id = controller
                inst._site = site
                return inst
        return None

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get the radio configuration for a UniFi access point.",
    )
    async def device_radio(
        self,
        info: Info,
        controller: strawberry.ID,
        mac: strawberry.ID,
        site: str = "default",
    ) -> DeviceRadio | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_device_radio(ctx, controller, site, mac)
        if raw is None:
            return None
        return DeviceRadio.from_manager_output(raw)

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get LLDP neighbors reported by a switch.",
    )
    async def lldp_neighbors(
        self,
        info: Info,
        controller: strawberry.ID,
        device_mac: strawberry.ID,
        site: str = "default",
    ) -> LldpNeighbors | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_lldp_neighbors(ctx, controller, site, device_mac)
        if raw is None:
            return None
        return LldpNeighbors.from_manager_output(raw)

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get per-outlet state for a UniFi Smart Power PDU (UP6 / USP-Strip).",
    )
    async def pdu_outlets(
        self,
        info: Info,
        controller: strawberry.ID,
        mac: strawberry.ID,
        site: str = "default",
    ) -> PduOutlets | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_pdu_outlets(ctx, controller, site, mac)
        if raw is None:
            return None
        return PduOutlets.from_manager_output(raw)

    @strawberry.field(
        permission_classes=[IsRead],
        description="List rogue (unknown) APs detected within a window (paginated).",
    )
    async def rogue_aps(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        within_hours: int = 24,
        limit: int = 50,
        cursor: str | None = None,
    ) -> RogueApPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_rogue_aps(ctx, controller, site, within_hours)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_bssid_key,
        )
        return RogueApPage(
            items=[RogueAp.from_manager_output(r) for r in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="List RF-scan results for a specific access point.",
    )
    async def rf_scan_results(
        self,
        info: Info,
        controller: strawberry.ID,
        ap_mac: strawberry.ID,
        site: str = "default",
    ) -> list[RfScanResult]:
        ctx: GraphQLContext = info.context
        raw = await _fetch_rf_scan_results(ctx, controller, site, ap_mac)
        return [RfScanResult.from_manager_output(r) for r in raw]

    @strawberry.field(
        permission_classes=[IsRead],
        description="List wireless channels allowed by the regulatory domain.",
    )
    async def available_channels(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
    ) -> list[AvailableChannel]:
        ctx: GraphQLContext = info.context
        raw = await _fetch_available_channels(ctx, controller, site)
        return [AvailableChannel.from_manager_output(r) for r in raw]

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get the gateway speedtest status (idle/running + last results).",
    )
    async def speedtest_status(
        self,
        info: Info,
        controller: strawberry.ID,
        gateway_mac: strawberry.ID,
        site: str = "default",
    ) -> SpeedtestStatus | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_speedtest_status(ctx, controller, site, gateway_mac)
        if raw is None:
            return None
        return SpeedtestStatus.from_manager_output(raw)

    # ---- Network domain --------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List configured LAN/VLAN networks on the given controller/site (paginated).",
    )
    async def networks(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> NetworkPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_networks(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_network_key,
        )
        items = []
        for n in page:
            inst = Network.from_manager_output(n)
            inst._controller_id = controller
            inst._site = site
            items.append(inst)
        return NetworkPage(
            items=items,
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single LAN/VLAN network by id. (Named "
        "``networkDetail`` because ``network`` is reserved for the namespace.)",
    )
    async def network_detail(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
        site: str = "default",
    ) -> Network | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_networks(ctx, controller, site)
        for n in raw:
            r = _raw(n)
            if isinstance(r, dict):
                nid = r.get("_id") or r.get("id")
            else:
                nid = getattr(r, "_id", None) or getattr(r, "id", None)
            if nid == id:
                inst = Network.from_manager_output(n)
                inst._controller_id = controller
                inst._site = site
                return inst
        return None

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get the controller's network-health subsystems list.",
    )
    async def network_health(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
    ) -> list[NetworkHealth]:
        ctx: GraphQLContext = info.context
        raw = await _fetch_network_health(ctx, controller, site)
        return [NetworkHealth.from_manager_output(r) for r in raw]

    # ---- WLAN domain -----------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List WLAN/SSID configurations on the given controller/site (paginated).",
    )
    async def wlans(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> WlanPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_wlans(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_id_key,
        )
        return WlanPage(
            items=[Wlan.from_manager_output(w) for w in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single WLAN/SSID by id.",
    )
    async def wlan(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
        site: str = "default",
    ) -> Wlan | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_wlans(ctx, controller, site)
        for w in raw:
            r = _raw(w)
            if isinstance(r, dict):
                wid = r.get("_id") or r.get("id")
            else:
                wid = getattr(r, "_id", None) or getattr(r, "id", None)
            if wid == id:
                return Wlan.from_manager_output(w)
        return None

    # ---- VPN domain ------------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List configured VPN clients (outbound tunnels) (paginated).",
    )
    async def vpn_clients(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> VpnClientPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_vpn_clients(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_id_key,
        )
        return VpnClientPage(
            items=[VpnClient.from_manager_output(v) for v in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single VPN client by id.",
    )
    async def vpn_client(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
        site: str = "default",
    ) -> VpnClient | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_vpn_clients(ctx, controller, site)
        for v in raw:
            r = _raw(v)
            if isinstance(r, dict):
                vid = r.get("_id") or r.get("id")
            else:
                vid = getattr(r, "_id", None) or getattr(r, "id", None)
            if vid == id:
                return VpnClient.from_manager_output(v)
        return None

    @strawberry.field(
        permission_classes=[IsRead],
        description="List configured VPN servers (inbound tunnels) (paginated).",
    )
    async def vpn_servers(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> VpnServerPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_vpn_servers(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_id_key,
        )
        return VpnServerPage(
            items=[VpnServer.from_manager_output(v) for v in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single VPN server by id.",
    )
    async def vpn_server(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
        site: str = "default",
    ) -> VpnServer | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_vpn_servers(ctx, controller, site)
        for v in raw:
            r = _raw(v)
            if isinstance(r, dict):
                vid = r.get("_id") or r.get("id")
            else:
                vid = getattr(r, "_id", None) or getattr(r, "id", None)
            if vid == id:
                return VpnServer.from_manager_output(v)
        return None

    # ---- DNS domain ------------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List static DNS records on the given controller/site (paginated).",
    )
    async def dns_records(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> DnsRecordPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_dns_records(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_id_key,
        )
        return DnsRecordPage(
            items=[DnsRecord.from_manager_output(d) for d in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single DNS record by id.",
    )
    async def dns_record(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
        site: str = "default",
    ) -> DnsRecord | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_dns_records(ctx, controller, site)
        for d in raw:
            r = _raw(d)
            if isinstance(r, dict):
                did = r.get("_id") or r.get("id")
            else:
                did = getattr(r, "_id", None) or getattr(r, "id", None)
            if did == id:
                return DnsRecord.from_manager_output(d)
        return None

    # ---- Routes domain ---------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List configured static routes (paginated).",
    )
    async def routes(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> RoutePage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_routes(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_id_key,
        )
        return RoutePage(
            items=[Route.from_manager_output(r) for r in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single static route by id.",
    )
    async def route(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
        site: str = "default",
    ) -> Route | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_routes(ctx, controller, site)
        for r in raw:
            rr = _raw(r)
            if isinstance(rr, dict):
                rid = rr.get("_id") or rr.get("id")
            else:
                rid = getattr(rr, "_id", None) or getattr(rr, "id", None)
            if rid == id:
                return Route.from_manager_output(r)
        return None

    @strawberry.field(
        permission_classes=[IsRead],
        description="List the gateway's active kernel routing-table entries (paginated).",
    )
    async def active_routes(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> ActiveRoutePage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_active_routes(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_active_route_key,
        )
        return ActiveRoutePage(
            items=[ActiveRoute.from_manager_output(r) for r in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="List traffic-route policies (V2 /trafficroutes) (paginated).",
    )
    async def traffic_routes(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> TrafficRoutePage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_traffic_routes(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_id_key,
        )
        return TrafficRoutePage(
            items=[TrafficRoute.from_manager_output(t) for t in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single traffic-route policy by id.",
    )
    async def traffic_route(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
        site: str = "default",
    ) -> TrafficRoute | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_traffic_routes(ctx, controller, site)
        for t in raw:
            rr = _raw(t)
            if isinstance(rr, dict):
                tid = rr.get("_id") or rr.get("id")
            else:
                tid = getattr(rr, "_id", None) or getattr(rr, "id", None)
            if tid == id:
                return TrafficRoute.from_manager_output(t)
        return None

    # ---- Firewall domain -------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List firewall policies/rules on the given controller/site (paginated).",
    )
    async def firewall_policies(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> FirewallRulePage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_firewall_policies(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_id_key,
        )
        return FirewallRulePage(
            items=[FirewallRule.from_manager_output(r) for r in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single firewall policy/rule by id.",
    )
    async def firewall_policy(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
        site: str = "default",
    ) -> FirewallRule | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_firewall_policies(ctx, controller, site)
        for r in raw:
            rr = _raw(r)
            if isinstance(rr, dict):
                rid = rr.get("_id") or rr.get("id")
            else:
                rid = getattr(rr, "_id", None) or getattr(rr, "id", None)
            if rid == id:
                return FirewallRule.from_manager_output(r)
        return None

    @strawberry.field(
        permission_classes=[IsRead],
        description="List firewall address/port groups (paginated).",
    )
    async def firewall_groups(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> FirewallGroupPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_firewall_groups(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_id_key,
        )
        return FirewallGroupPage(
            items=[FirewallGroup.from_manager_output(g) for g in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single firewall group by id.",
    )
    async def firewall_group(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
        site: str = "default",
    ) -> FirewallGroup | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_firewall_groups(ctx, controller, site)
        for g in raw:
            rr = _raw(g)
            if isinstance(rr, dict):
                gid = rr.get("_id") or rr.get("id")
            else:
                gid = getattr(rr, "_id", None) or getattr(rr, "id", None)
            if gid == id:
                return FirewallGroup.from_manager_output(g)
        return None

    @strawberry.field(
        permission_classes=[IsRead],
        description="List firewall zones (typically a small flat list — no pagination).",
    )
    async def firewall_zones(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
    ) -> list[FirewallZone]:
        ctx: GraphQLContext = info.context
        raw = await _fetch_firewall_zones(ctx, controller, site)
        return [FirewallZone.from_manager_output(z) for z in raw]

    # ---- QoS domain ------------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List QoS rules on the given controller/site (paginated).",
    )
    async def qos_rules(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> QosRulePage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_qos_rules(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_id_key,
        )
        return QosRulePage(
            items=[QosRule.from_manager_output(q) for q in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single QoS rule by id.",
    )
    async def qos_rule(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
        site: str = "default",
    ) -> QosRule | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_qos_rules(ctx, controller, site)
        for q in raw:
            rr = _raw(q)
            if isinstance(rr, dict):
                qid = rr.get("_id") or rr.get("id")
            else:
                qid = getattr(rr, "_id", None) or getattr(rr, "id", None)
            if qid == id:
                return QosRule.from_manager_output(q)
        return None

    # ---- DPI domain ------------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List DPI applications (paginated).",
    )
    async def dpi_applications(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> DpiApplicationPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_dpi_applications(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_id_key,
        )
        return DpiApplicationPage(
            items=[DpiApplication.from_manager_output(a) for a in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="List DPI categories (paginated).",
    )
    async def dpi_categories(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> DpiCategoryPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_dpi_categories(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_id_key,
        )
        return DpiCategoryPage(
            items=[DpiCategory.from_manager_output(c) for c in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    # ---- Content filter domain ------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List content filters on the given controller/site (paginated).",
    )
    async def content_filters(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> ContentFilterPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_content_filters(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_id_key,
        )
        return ContentFilterPage(
            items=[ContentFilter.from_manager_output(f) for f in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single content filter by id.",
    )
    async def content_filter(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
        site: str = "default",
    ) -> ContentFilter | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_content_filters(ctx, controller, site)
        for f in raw:
            rr = _raw(f)
            if isinstance(rr, dict):
                fid = rr.get("_id") or rr.get("id")
            else:
                fid = getattr(rr, "_id", None) or getattr(rr, "id", None)
            if fid == id:
                return ContentFilter.from_manager_output(f)
        return None

    # ---- ACL domain ------------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List ACL rules on the given controller/site (paginated).",
    )
    async def acl_rules(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> AclRulePage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_acl_rules(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_id_key,
        )
        return AclRulePage(
            items=[AclRule.from_manager_output(a) for a in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single ACL rule by id.",
    )
    async def acl_rule(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
        site: str = "default",
    ) -> AclRule | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_acl_rules(ctx, controller, site)
        for a in raw:
            rr = _raw(a)
            if isinstance(rr, dict):
                aid = rr.get("_id") or rr.get("id")
            else:
                aid = getattr(rr, "_id", None) or getattr(rr, "id", None)
            if aid == id:
                return AclRule.from_manager_output(a)
        return None

    # ---- OON domain ------------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List OON (out-of-network) policies (paginated).",
    )
    async def oon_policies(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> OonPolicyPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_oon_policies(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_id_key,
        )
        return OonPolicyPage(
            items=[OonPolicy.from_manager_output(p) for p in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single OON policy by id.",
    )
    async def oon_policy(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
        site: str = "default",
    ) -> OonPolicy | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_oon_policies(ctx, controller, site)
        for p in raw:
            rr = _raw(p)
            if isinstance(rr, dict):
                pid = rr.get("_id") or rr.get("id")
            else:
                pid = getattr(rr, "_id", None) or getattr(rr, "id", None)
            if pid == id:
                return OonPolicy.from_manager_output(p)
        return None

    # ---- Port forward domain --------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List port forwards on the given controller/site (paginated).",
    )
    async def port_forwards(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> PortForwardPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_port_forwards(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_id_key,
        )
        return PortForwardPage(
            items=[PortForward.from_manager_output(p) for p in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single port forward by id.",
    )
    async def port_forward(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
        site: str = "default",
    ) -> PortForward | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_port_forwards(ctx, controller, site)
        for p in raw:
            rr = _raw(p)
            if isinstance(rr, dict):
                pid = rr.get("_id") or rr.get("id")
            else:
                pid = getattr(rr, "_id", None) or getattr(rr, "id", None)
            if pid == id:
                return PortForward.from_manager_output(p)
        return None

    # ---- Stats domain ---------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="Site dashboard timeseries (all-points).",
    )
    async def dashboard_stats(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        duration_hours: int = 1,
    ) -> list[StatPoint]:
        ctx: GraphQLContext = info.context
        raw = await _fetch_dashboard_stats(ctx, controller, site, duration_hours)
        return [StatPoint.from_manager_output(p) for p in (raw or [])]

    @strawberry.field(
        permission_classes=[IsRead],
        description="Network-wide stats timeseries.",
    )
    async def network_stats(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        duration_hours: int = 1,
    ) -> list[StatPoint]:
        ctx: GraphQLContext = info.context
        raw = await _fetch_network_stats(ctx, controller, site, duration_hours)
        return [StatPoint.from_manager_output(p) for p in (raw or [])]

    @strawberry.field(
        permission_classes=[IsRead],
        description="Gateway stats timeseries.",
    )
    async def gateway_stats(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        duration_hours: int = 24,
    ) -> list[StatPoint]:
        ctx: GraphQLContext = info.context
        raw = await _fetch_gateway_stats(ctx, controller, site, duration_hours)
        return [StatPoint.from_manager_output(p) for p in (raw or [])]

    @strawberry.field(
        permission_classes=[IsRead],
        description="Per-client stats timeseries (by MAC).",
    )
    async def client_stats(
        self,
        info: Info,
        controller: strawberry.ID,
        mac: strawberry.ID,
        site: str = "default",
        duration_hours: int = 1,
    ) -> list[StatPoint]:
        ctx: GraphQLContext = info.context
        raw = await _fetch_client_stats(ctx, controller, site, mac, duration_hours)
        return [StatPoint.from_manager_output(p) for p in (raw or [])]

    @strawberry.field(
        permission_classes=[IsRead],
        description="Per-device stats timeseries (by MAC).",
    )
    async def device_stats(
        self,
        info: Info,
        controller: strawberry.ID,
        mac: strawberry.ID,
        site: str = "default",
        duration_hours: int = 1,
    ) -> list[StatPoint]:
        ctx: GraphQLContext = info.context
        raw = await _fetch_device_stats(ctx, controller, site, mac, duration_hours)
        return [StatPoint.from_manager_output(p) for p in (raw or [])]

    @strawberry.field(
        permission_classes=[IsRead],
        description="Per-client DPI traffic breakdown.",
    )
    async def client_dpi_traffic(
        self,
        info: Info,
        controller: strawberry.ID,
        mac: strawberry.ID,
        site: str = "default",
    ) -> list[StatPoint]:
        ctx: GraphQLContext = info.context
        raw = await _fetch_client_dpi_traffic(ctx, controller, site, mac)
        return [StatPoint.from_manager_output(p) for p in (raw or [])]

    @strawberry.field(
        permission_classes=[IsRead],
        description="Site-wide DPI traffic breakdown.",
    )
    async def site_dpi_traffic(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
    ) -> list[StatPoint]:
        ctx: GraphQLContext = info.context
        raw = await _fetch_site_dpi_traffic(ctx, controller, site)
        return [StatPoint.from_manager_output(p) for p in (raw or [])]

    @strawberry.field(
        permission_classes=[IsRead],
        description="DPI stats catalog (applications + categories).",
    )
    async def dpi_stats(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
    ) -> DpiStats | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_dpi_stats(ctx, controller, site)
        if raw is None:
            return None
        return DpiStats.from_manager_output(raw)

    # ---- Events domain --------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List recent controller events (paginated).",
    )
    async def event_log(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> EventLogPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_event_log(ctx, controller, site, max(limit, 100))

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_event_key,
        )
        return EventLogPage(
            items=[EventLog.from_manager_output(e) for e in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="List active alerts (paginated).",
    )
    async def alerts(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> EventLogPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_alerts(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw or []), limit=limit, cursor=cursor_obj, key_fn=_event_key,
        )
        return EventLogPage(
            items=[EventLog.from_manager_output(e) for e in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="List recent anomalies (paginated).",
    )
    async def anomalies(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> EventLogPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_anomalies(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw or []), limit=limit, cursor=cursor_obj, key_fn=_event_key,
        )
        return EventLogPage(
            items=[EventLog.from_manager_output(e) for e in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="List recent IPS/IDS events (paginated).",
    )
    async def ips_events(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> EventLogPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_ips_events(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw or []), limit=limit, cursor=cursor_obj, key_fn=_event_key,
        )
        return EventLogPage(
            items=[EventLog.from_manager_output(e) for e in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="List controller alarms (paginated).",
    )
    async def alarms(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> AlarmPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_alarms(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw or []), limit=limit, cursor=cursor_obj, key_fn=_event_key,
        )
        return AlarmPage(
            items=[Alarm.from_manager_output(a) for a in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    # ---- System domain --------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get controller system info (build, uptime, hardware).",
    )
    async def system_info(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
    ) -> SystemInfo | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_system_info(ctx, controller, site)
        if raw is None:
            return None
        return SystemInfo.from_manager_output(raw)

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get site-level settings (locale, timezone, advanced).",
    )
    async def site_settings(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
    ) -> SiteSettings | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_site_settings(ctx, controller, site)
        if raw is None:
            return None
        return SiteSettings.from_manager_output(raw)

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get SNMP settings.",
    )
    async def snmp_settings(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
    ) -> SnmpSettings | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_snmp_settings(ctx, controller, site)
        if raw is None:
            return None
        return SnmpSettings.from_manager_output(raw)

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get the controller's event-type prefix catalog.",
    )
    async def event_types(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
    ) -> EventTypes | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_event_types(ctx, controller, site)
        if raw is None:
            return None
        return EventTypes.from_manager_output(raw)

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get auto-backup schedule + retention settings.",
    )
    async def autobackup_settings(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
    ) -> AutoBackupSettings | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_autobackup_settings(ctx, controller, site)
        if raw is None:
            return None
        return AutoBackupSettings.from_manager_output(raw)

    @strawberry.field(
        permission_classes=[IsRead],
        description="List controller backups (paginated).",
    )
    async def backups(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> BackupPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_backups(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw or []), limit=limit, cursor=cursor_obj, key_fn=_backup_key,
        )
        return BackupPage(
            items=[Backup.from_manager_output(b) for b in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="List recent speedtest results (paginated).",
    )
    async def speedtest_results(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        duration_hours: int = 24,
        limit: int = 50,
        cursor: str | None = None,
    ) -> SpeedtestResultPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_speedtest_results(ctx, controller, site, duration_hours)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw or []), limit=limit, cursor=cursor_obj, key_fn=_speedtest_key,
        )
        return SpeedtestResultPage(
            items=[SpeedtestResult.from_manager_output(s) for s in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="List top-traffic clients within a window.",
    )
    async def top_clients(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        within_hours: int = 24,
    ) -> list[TopClient]:
        ctx: GraphQLContext = info.context
        raw = await _fetch_top_clients(ctx, controller, site, within_hours)
        return [TopClient.from_manager_output(t) for t in (raw or [])]

    # ---- Vouchers domain ------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List hotspot vouchers on the given controller/site (paginated).",
    )
    async def vouchers(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> VoucherPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_vouchers(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_voucher_key,
        )
        return VoucherPage(
            items=[Voucher.from_manager_output(v) for v in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single hotspot voucher by id.",
    )
    async def voucher(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
        site: str = "default",
    ) -> Voucher | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_voucher_details(ctx, controller, site, id)
        if raw is None:
            return None
        return Voucher.from_manager_output(raw)

    # ---- Sessions domain ------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List a client's association sessions (paginated).",
    )
    async def client_sessions(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        mac: str | None = None,
        duration_hours: int = 24,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ClientSessionPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_client_sessions(
            ctx, controller, site, mac, duration_hours,
        )

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw or []), limit=limit, cursor=cursor_obj, key_fn=_session_key,
        )
        return ClientSessionPage(
            items=[ClientSession.from_manager_output(s) for s in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get a client's current WiFi parameters (signal, rates).",
    )
    async def client_wifi_details(
        self,
        info: Info,
        controller: strawberry.ID,
        mac: strawberry.ID,
        site: str = "default",
    ) -> ClientWifiDetails | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_client_wifi_details(ctx, controller, site, mac)
        if raw is None:
            return None
        return ClientWifiDetails.from_manager_output(raw)

    # ---- Switch domain ---------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List switch port profiles on the given controller/site (paginated).",
    )
    async def port_profiles(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> PortProfilePage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_port_profiles(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_id_key,
        )
        return PortProfilePage(
            items=[PortProfile.from_manager_output(p) for p in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single switch port profile by id.",
    )
    async def port_profile(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
        site: str = "default",
    ) -> PortProfile | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_port_profiles(ctx, controller, site)
        for p in raw:
            rr = _raw(p)
            if isinstance(rr, dict):
                pid = rr.get("_id") or rr.get("id")
            else:
                pid = getattr(rr, "_id", None) or getattr(rr, "id", None)
            if pid == id:
                return PortProfile.from_manager_output(p)
        return None

    @strawberry.field(
        permission_classes=[IsRead],
        description=(
            "Get the port-override wrapper for a switch "
            "(name/model + per-port overrides)."
        ),
    )
    async def switch_ports(
        self,
        info: Info,
        controller: strawberry.ID,
        device_mac: strawberry.ID,
        site: str = "default",
    ) -> SwitchPorts | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_switch_ports(ctx, controller, site, device_mac)
        if raw is None:
            return None
        return SwitchPorts.from_manager_output(raw)

    @strawberry.field(
        permission_classes=[IsRead],
        description=(
            "Get the per-port stats wrapper for a switch "
            "(name/model + port_table)."
        ),
    )
    async def port_stats(
        self,
        info: Info,
        controller: strawberry.ID,
        device_mac: strawberry.ID,
        site: str = "default",
    ) -> PortStats | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_port_stats(ctx, controller, site, device_mac)
        if raw is None:
            return None
        return PortStats.from_manager_output(raw)

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get switch capabilities (caps dict + STP / dot1x flags).",
    )
    async def switch_capabilities(
        self,
        info: Info,
        controller: strawberry.ID,
        device_mac: strawberry.ID,
        site: str = "default",
    ) -> SwitchCapabilities | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_switch_capabilities(ctx, controller, site, device_mac)
        if raw is None:
            return None
        return SwitchCapabilities.from_manager_output(raw)

    # ---- AP groups domain ------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List AP groups on the given controller/site (paginated).",
    )
    async def ap_groups(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> ApGroupPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_ap_groups(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_id_key,
        )
        return ApGroupPage(
            items=[ApGroup.from_manager_output(g) for g in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single AP group by id.",
    )
    async def ap_group(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
        site: str = "default",
    ) -> ApGroup | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_ap_groups(ctx, controller, site)
        for g in raw:
            rr = _raw(g)
            if isinstance(rr, dict):
                gid = rr.get("_id") or rr.get("id")
            else:
                gid = getattr(rr, "_id", None) or getattr(rr, "id", None)
            if gid == id:
                return ApGroup.from_manager_output(g)
        return None

    # ---- Client groups domain --------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description=(
            "List network member client groups on the given controller/site "
            "(paginated)."
        ),
    )
    async def client_groups(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> ClientGroupPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_client_groups(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_id_key,
        )
        return ClientGroupPage(
            items=[ClientGroup.from_manager_output(g) for g in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single network member client group by id.",
    )
    async def client_group(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
        site: str = "default",
    ) -> ClientGroup | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_client_groups(ctx, controller, site)
        for g in raw:
            rr = _raw(g)
            if isinstance(rr, dict):
                gid = rr.get("_id") or rr.get("id")
            else:
                gid = getattr(rr, "_id", None) or getattr(rr, "id", None)
            if gid == id:
                return ClientGroup.from_manager_output(g)
        return None

    @strawberry.field(
        permission_classes=[IsRead],
        description=(
            "List QoS user groups (V1 /rest/usergroup) on the given "
            "controller/site (paginated)."
        ),
    )
    async def user_groups(
        self,
        info: Info,
        controller: strawberry.ID,
        site: str = "default",
        limit: int = 50,
        cursor: str | None = None,
    ) -> UserGroupPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_user_groups(ctx, controller, site)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw), limit=limit, cursor=cursor_obj, key_fn=_id_key,
        )
        return UserGroupPage(
            items=[UserGroup.from_manager_output(g) for g in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single QoS user group by id.",
    )
    async def user_group(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
        site: str = "default",
    ) -> UserGroup | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_user_groups(ctx, controller, site)
        for g in raw:
            rr = _raw(g)
            if isinstance(rr, dict):
                gid = rr.get("_id") or rr.get("id")
            else:
                gid = getattr(rr, "_id", None) or getattr(rr, "id", None)
            if gid == id:
                return UserGroup.from_manager_output(g)
        return None
