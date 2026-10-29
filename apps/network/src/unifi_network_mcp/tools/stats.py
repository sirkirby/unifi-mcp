"""
Unifi Network MCP statistics tools.

This module provides MCP tools to fetch statistics from a Unifi Network Controller.
"""

import logging
from typing import Annotated, Any, Dict, Literal, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.network.models.sessions import (
    client_session_from_controller,
    client_wifi_details_from_controller,
)
from unifi_core.network.models.stats import dpi_stats_from_controller
from unifi_core.network.models.system import speedtest_result_from_controller, top_client_from_controller
from unifi_core.network.read_views import shape_alerts, shape_dashboard
from unifi_core.network.time_window import duration_hours as _duration_hours
from unifi_core.network.time_window import parse_window_bound as _epoch_ms
from unifi_network_mcp.runtime import client_manager, device_manager, server, stats_manager

logger = logging.getLogger(__name__)

_WINDOW_DESCRIPTION = (
    "Absolute window bound: ISO 8601 with a UTC offset, Z or +/-HH:MM (e.g. '2026-10-02T02:15:00-04:00'; "
    "a time without an offset is rejected as ambiguous), or epoch seconds/milliseconds. "
    "Omit it rather than passing an empty string. Takes precedence over duration."
)


@server.tool(
    name="unifi_get_network_stats",
    description="Get network statistics from the Unifi Network controller",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_network_stats(
    duration: Annotated[
        str,
        Field(
            description="Time period for stats: 'hourly' (last 1h, default), 'daily' (24h), 'weekly' (7d), or 'monthly' (30d)"
        ),
    ] = "hourly",
    granularity: Annotated[
        str,
        Field(
            description="Time resolution: '5minutes' (~12h retention), 'hourly' (default, ~7d), 'daily' (~1yr), 'monthly' (~1yr)"
        ),
    ] = "hourly",
) -> Dict[str, Any]:
    """Implementation for getting network stats."""
    try:
        duration_hours = _duration_hours(duration)
        stats = await stats_manager.get_network_stats(duration_hours=duration_hours, granularity=granularity)

        def _first_non_none(*values):
            for v in values:
                if v is not None:
                    return v
            return 0

        summary = {
            "total_rx_bytes": sum(int(e.get("rx_bytes", 0) or 0) for e in stats),
            "total_tx_bytes": sum(int(e.get("tx_bytes", 0) or 0) for e in stats),
            "total_bytes": sum(
                int(
                    (
                        e.get("bytes")
                        if e.get("bytes") is not None
                        else (e.get("rx_bytes", 0) or 0) + (e.get("tx_bytes", 0) or 0)
                    )
                )
                for e in stats
            ),
            "avg_clients": int(
                sum(_first_non_none(e.get("num_user"), e.get("num_active_user"), e.get("num_sta")) for e in stats)
                / max(1, len(stats))
            )
            if stats
            else 0,
        }
        return {
            "success": True,
            "site": stats_manager._connection.site,
            "duration": duration,
            "granularity": granularity,
            "summary": summary,
            "stats": stats,
        }
    except Exception as e:
        logger.error("Error getting network stats: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get network stats: {e}"}


@server.tool(
    name="unifi_get_client_stats",
    description=(
        "Get a client's traffic time-series from the controller's per-client report. "
        "summary.upload_bytes is what the client sent and summary.download_bytes what it received "
        "(the report's rx_bytes/tx_bytes, counted from the network side). Pass start/end to inspect "
        "a past incident window. Wired clients are not metered per client in this report on current "
        "gateways, so an empty series for a wired client means 'not reported', not 'no traffic'."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_client_stats(
    client_id: Annotated[str, Field(description="Client MAC address or _id (from unifi_list_clients)")],
    duration: Annotated[
        str,
        Field(
            description="Time period for stats: 'hourly' (last 1h, default), 'daily' (24h), 'weekly' (7d), or 'monthly' (30d)"
        ),
    ] = "hourly",
    granularity: Annotated[
        str,
        Field(
            description="Time resolution: '5minutes' (~12h retention), 'hourly' (default, ~7d), 'daily' (~1yr), 'monthly' (~1yr)"
        ),
    ] = "hourly",
    start: Annotated[Optional[str], Field(description="Window start. " + _WINDOW_DESCRIPTION)] = None,
    end: Annotated[Optional[str], Field(description="Window end (default now). " + _WINDOW_DESCRIPTION)] = None,
) -> Dict[str, Any]:
    """Implementation for getting client stats."""
    try:
        duration_hours = _duration_hours(duration)
        client_details = await client_manager.get_client_details(client_id)
        if not client_details:
            return {"success": False, "error": f"Client '{client_id}' not found"}

        # Support aiounifi Client objects as well as dicts
        client_raw = client_details.raw if hasattr(client_details, "raw") else client_details
        client_mac = client_raw.get("mac", client_id)
        client_name = client_raw.get("name") or client_raw.get("hostname") or client_mac

        # Stats endpoint expects MAC, not _id
        start_ms, end_ms = _epoch_ms(start), _epoch_ms(end)
        stats = await stats_manager.get_client_stats(
            client_mac,
            duration_hours=duration_hours,
            granularity=granularity,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        total_rx = sum(e.get("rx_bytes", 0) or 0 for e in stats)
        total_tx = sum(e.get("tx_bytes", 0) or 0 for e in stats)
        summary = {
            "total_rx_bytes": total_rx,
            "total_tx_bytes": total_tx,
            "total_bytes": sum(
                e.get("bytes", (e.get("rx_bytes", 0) or 0) + (e.get("tx_bytes", 0) or 0)) for e in stats
            ),
            "upload_bytes": total_rx,
            "download_bytes": total_tx,
        }
        return {
            "success": True,
            "site": stats_manager._connection.site,
            "client_id": client_id,
            "client_name": client_name,
            "duration": duration,
            "start": start_ms,
            "end": end_ms,
            "granularity": granularity,
            "summary": summary,
            "stats": stats,
        }
    except Exception as e:
        logger.error("Error getting client stats for %s: %s", client_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get client stats for {client_id}: {e}"}


@server.tool(
    name="unifi_get_device_stats",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    description=(
        "Returns historical traffic time-series (rx/tx bytes, client counts) for one "
        "device by MAC or _id. Duration: hourly/daily/weekly/monthly. "
        "For APs, includes avg/max client counts and WiFi quality metrics. "
        "For current device status instead of stats, use unifi_get_device_details."
    ),
)
async def get_device_stats(
    device_id: Annotated[str, Field(description="Device MAC address or _id (from unifi_list_devices)")],
    duration: Annotated[
        str,
        Field(
            description="Time period for stats: 'hourly' (last 1h, default), 'daily' (24h), 'weekly' (7d), or 'monthly' (30d)"
        ),
    ] = "hourly",
    granularity: Annotated[
        str,
        Field(
            description="Time resolution: '5minutes' (~12h retention), 'hourly' (default, ~7d), 'daily' (~1yr), 'monthly' (~1yr)"
        ),
    ] = "hourly",
) -> Dict[str, Any]:
    """Implementation for getting device stats."""
    try:
        duration_hours = _duration_hours(duration)
        device_details = await device_manager.get_device_details(device_id)
        if not device_details:
            return {"success": False, "error": f"Device '{device_id}' not found"}

        device_raw = device_details.raw if hasattr(device_details, "raw") else device_details
        device_name = device_raw.get("name") or device_raw.get("model", "Unknown")
        device_mac = device_raw.get("mac", device_id)
        device_type = device_raw.get("type", "unknown")

        # Auto-detect device type for the stats endpoint
        device_type_map = {"uap": "ap", "ugw": "gw", "udm": "gw"}
        stats_device_type = device_type_map.get(device_type, "dev")

        stats = await stats_manager.get_device_stats(
            device_mac,
            duration_hours=duration_hours,
            granularity=granularity,
            device_type=stats_device_type,
        )
        summary = {
            "total_rx_bytes": sum(e.get("rx_bytes", 0) for e in stats),
            "total_tx_bytes": sum(e.get("tx_bytes", 0) for e in stats),
            "total_bytes": sum(e.get("bytes", e.get("rx_bytes", 0) + e.get("tx_bytes", 0)) for e in stats),
        }
        if device_type == "uap" and stats:
            summary["avg_clients"] = int(sum(e.get("num_sta", 0) for e in stats) / max(1, len(stats)))
            summary["max_clients"] = max(e.get("num_sta", 0) for e in stats)
            # WiFi quality metrics when available from .ap endpoint
            satisfaction_vals = [e.get("satisfaction") for e in stats if e.get("satisfaction") is not None]
            if satisfaction_vals:
                summary["avg_satisfaction"] = round(sum(satisfaction_vals) / len(satisfaction_vals), 1)
            tx_retries_vals = [e.get("tx_retries") for e in stats if e.get("tx_retries") is not None]
            if tx_retries_vals:
                summary["total_tx_retries"] = sum(tx_retries_vals)

        return {
            "success": True,
            "site": stats_manager._connection.site,
            "device_id": device_id,
            "device_name": device_name,
            "device_type": device_type,
            "duration": duration,
            "granularity": granularity,
            "summary": summary,
            "stats": stats,
        }
    except Exception as e:
        logger.error("Error getting device stats for %s: %s", device_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get device stats for {device_id}: {e}"}


@server.tool(
    name="unifi_get_top_clients",
    description=(
        "Rank clients by traffic inside a time window — the first call when working an upload or "
        "egress spike ('who sent data between 02:00 and 05:00?'). Sums the controller's per-client "
        "report over the window; upload_bytes is what each client sent, download_bytes what it "
        "received. Use sort_by='upload' for exfiltration questions. Network 11 covers every client; "
        "older controllers cover only clients they meter individually (wireless on current "
        "gateways), so wired clients, cluster nodes included, are absent there. Entries with source='live_counters' are a fallback for controllers without the "
        "report and are cumulative since association, not scoped to the window."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_top_clients(
    duration: Annotated[
        str,
        Field(
            description="Time period for stats: 'hourly' (1h), 'daily' (24h, default), 'weekly' (7d), or 'monthly' (30d)"
        ),
    ] = "daily",
    limit: Annotated[int, Field(description="Maximum number of top clients to return (default 10)")] = 10,
    start: Annotated[Optional[str], Field(description="Window start. " + _WINDOW_DESCRIPTION)] = None,
    end: Annotated[Optional[str], Field(description="Window end (default now). " + _WINDOW_DESCRIPTION)] = None,
    granularity: Annotated[
        Optional[str],
        Field(
            description="Report resolution: '5minutes', 'hourly', 'daily', 'monthly'. Default: the finest "
            "the controller still retains for the window start"
        ),
    ] = None,
    sort_by: Annotated[
        Literal["total", "upload", "download"],
        Field(description="Rank by 'total' (default), 'upload' (client sent) or 'download' (client received)"),
    ] = "total",
) -> Dict[str, Any]:
    """Implementation for getting top clients by usage."""
    try:
        duration_hours = _duration_hours(duration)
        start_ms, end_ms = _epoch_ms(start), _epoch_ms(end)
        top_client_stats = await stats_manager.get_top_clients(
            duration_hours=duration_hours,
            limit=limit,
            start_ms=start_ms,
            end_ms=end_ms,
            granularity=granularity,
            sort_by=sort_by,
        )

        enriched = []
        for entry in top_client_stats:
            entry = dict(entry)
            mac = entry.get("mac")
            if mac and not entry.get("name") and not entry.get("hostname"):
                # Report rows carry no name. A client from a historical window may have
                # left inventory since, so the lookup is best-effort per row: on failure
                # the row keeps its MAC and byte counts rather than sinking the ranking.
                try:
                    details = await client_manager.get_client_details(mac, existence_only=True)
                except Exception as lookup_error:
                    logger.debug("Top client name lookup failed (%s)", type(lookup_error).__name__)
                    details = None
                if details:
                    raw = details.raw if hasattr(details, "raw") else details
                    entry["name"] = raw.get("name") or raw.get("hostname") or mac
            enriched.append(entry)

        shaped = [top_client_from_controller(e).model_dump(exclude_none=False) for e in enriched]
        first = enriched[0] if enriched else {}
        return {
            "success": True,
            "site": stats_manager._connection.site,
            "duration": duration,
            "start": first.get("start", start_ms),
            "end": first.get("end", end_ms),
            "granularity": first.get("granularity", granularity),
            "sort_by": sort_by,
            "limit": limit,
            "top_clients": shaped,
        }
    except Exception as e:
        logger.error("Error getting top clients: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get top clients: {e}"}


@server.tool(
    name="unifi_get_dpi_stats",
    description="Get Deep Packet Inspection (DPI) statistics (applications and categories)",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_dpi_stats() -> Dict[str, Any]:
    """Implementation for getting DPI stats."""
    try:
        dpi_stats_result = await stats_manager.get_dpi_stats()
        shaped = dpi_stats_from_controller(dpi_stats_result)

        return {
            "success": True,
            "site": stats_manager._connection.site,
            "dpi_stats": shaped.model_dump(exclude_none=True),
        }
    except Exception as e:
        logger.error("Error getting DPI stats: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to get DPI stats: {type(e).__name__}"}


@server.tool(
    name="unifi_get_alerts",
    description="Get recent alerts from the Unifi Network controller",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_alerts(
    limit: Annotated[int, Field(description="Maximum number of alerts to return (default 10)")] = 10,
    include_archived: Annotated[
        bool, Field(description="When true, includes previously archived/resolved alerts. Default false")
    ] = False,
) -> Dict[str, Any]:
    """Implementation for getting alerts."""
    try:
        alerts = await stats_manager.get_alerts(include_archived=include_archived)
        return shape_alerts(
            alerts,
            site=stats_manager._connection.site,
            limit=limit,
            include_archived=include_archived,
        )
    except Exception as e:
        logger.error("Error getting alerts: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get alerts: {e}"}


# ---------------------------------------------------------------------------
# New tools
# ---------------------------------------------------------------------------


@server.tool(
    name="unifi_get_gateway_stats",
    description="Get gateway WAN/LAN performance history including bandwidth, CPU, and memory utilization.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_gateway_stats(
    duration: Annotated[
        str,
        Field(description="Time period: 'hourly' (1h, default), 'daily' (24h), 'weekly' (7d), or 'monthly' (30d)"),
    ] = "hourly",
    granularity: Annotated[
        str,
        Field(
            description="Time resolution: '5minutes' (~12h retention), 'hourly' (default, ~7d), 'daily' (~1yr), 'monthly' (~1yr)"
        ),
    ] = "hourly",
) -> Dict[str, Any]:
    """Implementation for getting gateway stats."""
    try:
        duration_hours = _duration_hours(duration)
        stats = await stats_manager.get_gateway_stats(duration_hours=duration_hours, granularity=granularity)
        summary: Dict[str, Any] = {
            "total_wan_rx_bytes": sum(int(e.get("wan-rx_bytes", 0) or 0) for e in stats),
            "total_wan_tx_bytes": sum(int(e.get("wan-tx_bytes", 0) or 0) for e in stats),
        }
        cpu_vals = [e.get("cpu") for e in stats if e.get("cpu") is not None]
        if cpu_vals:
            summary["avg_cpu_pct"] = round(sum(cpu_vals) / len(cpu_vals), 1)
        mem_vals = [e.get("mem") for e in stats if e.get("mem") is not None]
        if mem_vals:
            summary["avg_mem_pct"] = round(sum(mem_vals) / len(mem_vals), 1)

        return {
            "success": True,
            "site": stats_manager._connection.site,
            "duration": duration,
            "granularity": granularity,
            "summary": summary,
            "stats": stats,
        }
    except Exception as e:
        logger.error("Error getting gateway stats: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get gateway stats: {e}"}


@server.tool(
    name="unifi_get_speedtest_results",
    description="Get historical speedtest results including download, upload (Mbps), and latency (ms).",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_speedtest_results(
    duration: Annotated[
        str,
        Field(description="Time period: 'hourly' (1h, default), 'daily' (24h), 'weekly' (7d), or 'monthly' (30d)"),
    ] = "daily",
) -> Dict[str, Any]:
    """Implementation for getting historical speedtest results."""
    try:
        duration_hours = _duration_hours(duration)
        results = await stats_manager.get_speedtest_results(duration_hours=duration_hours)

        shaped = [speedtest_result_from_controller(r).model_dump(exclude_none=False) for r in results]
        return {
            "success": True,
            "site": stats_manager._connection.site,
            "duration": duration,
            "count": len(shaped),
            "results": shaped,
        }
    except Exception as e:
        logger.error("Error getting speedtest results: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get speedtest results: {e}"}


@server.tool(
    name="unifi_get_site_dpi_traffic",
    description=(
        "Get actual DPI traffic data by application or category for the entire site. "
        "Shows real bandwidth usage per app/category, NOT restriction configuration. "
        "Use unifi_get_dpi_stats for restriction config instead. "
        "On Network 9.x+ this reads the v2 traffic aggregate for the window (default: last 24h); "
        "older controllers fall back to the legacy per-site/per-client DPI endpoint, which has no window. "
        "upload_bytes is what the client sent. application/category are numeric DPI IDs — resolve names "
        "with unifi_list_dpi_applications / unifi_list_dpi_categories; 65535/255 means unidentified "
        "(typically encrypted QUIC/TLS). The controller aggregates DPI in coarse buckets, so totals for "
        "windows that cut through a bucket are approximate: use DPI for what kind of traffic, and "
        "unifi_get_top_clients / unifi_get_client_stats for how much. "
        "Note: requires Traffic Identification to be enabled on the controller, "
        "which is separate from Device Identification."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_site_dpi_traffic(
    group_by: Annotated[
        str,
        Field(description="Group results: 'by_app' (default) for per-application or 'by_cat' for per-category"),
    ] = "by_app",
    duration: Annotated[
        str,
        Field(description="Time period: 'hourly' (1h), 'daily' (24h, default), 'weekly' (7d), or 'monthly' (30d)"),
    ] = "daily",
    start: Annotated[Optional[str], Field(description="Window start. " + _WINDOW_DESCRIPTION)] = None,
    end: Annotated[Optional[str], Field(description="Window end (default now). " + _WINDOW_DESCRIPTION)] = None,
) -> Dict[str, Any]:
    """Implementation for getting site-wide DPI traffic data."""
    try:
        start_ms, end_ms = _epoch_ms(start), _epoch_ms(end)
        traffic = await stats_manager.get_site_dpi_traffic(
            by=group_by, duration_hours=_duration_hours(duration), start_ms=start_ms, end_ms=end_ms
        )
        return {
            "success": True,
            "site": stats_manager._connection.site,
            "group_by": group_by,
            "duration": duration,
            "start": start_ms,
            "end": end_ms,
            "traffic": traffic,
        }
    except Exception as e:
        logger.error("Error getting site DPI traffic: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get site DPI traffic: {e}"}


@server.tool(
    name="unifi_get_client_dpi_traffic",
    description=(
        "Get per-client DPI traffic data by application or category. "
        "On Network 9.x+ this reads the v2 traffic aggregate for the window (default: last 24h); "
        "older controllers fall back to the legacy per-site/per-client DPI endpoint, which has no window. "
        "upload_bytes is what the client sent. application/category are numeric DPI IDs — resolve names "
        "with unifi_list_dpi_applications / unifi_list_dpi_categories; 65535/255 means unidentified "
        "(typically encrypted QUIC/TLS). The controller aggregates DPI in coarse buckets, so totals for "
        "windows that cut through a bucket are approximate: use DPI for what kind of traffic, and "
        "unifi_get_top_clients / unifi_get_client_stats for how much. "
        "Note: requires Traffic Identification to be enabled on the controller, "
        "which is separate from Device Identification."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_client_dpi_traffic(
    mac_address: Annotated[str, Field(description="Client MAC address")],
    group_by: Annotated[
        str,
        Field(description="Group results: 'by_app' (default) for per-application or 'by_cat' for per-category"),
    ] = "by_app",
    duration: Annotated[
        str,
        Field(description="Time period: 'hourly' (1h), 'daily' (24h, default), 'weekly' (7d), or 'monthly' (30d)"),
    ] = "daily",
    start: Annotated[Optional[str], Field(description="Window start. " + _WINDOW_DESCRIPTION)] = None,
    end: Annotated[Optional[str], Field(description="Window end (default now). " + _WINDOW_DESCRIPTION)] = None,
) -> Dict[str, Any]:
    """Implementation for getting per-client DPI traffic data."""
    try:
        duration_hours = _duration_hours(duration)
        start_ms, end_ms = _epoch_ms(start), _epoch_ms(end)
    except ValueError as e:
        # Argument errors carry no client data, so they are safe to return verbatim.
        return {"success": False, "error": f"Failed to get client DPI traffic: {e}"}
    try:
        traffic = await stats_manager.get_client_dpi_traffic(
            client_mac=mac_address, by=group_by, duration_hours=duration_hours, start_ms=start_ms, end_ms=end_ms
        )
        return {
            "success": True,
            "site": stats_manager._connection.site,
            "client_mac": mac_address,
            "group_by": group_by,
            "duration": duration,
            "start": start_ms,
            "end": end_ms,
            "traffic": traffic,
        }
    except Exception as e:
        logger.error("Error getting client DPI traffic: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to get client DPI traffic: {type(e).__name__}"}


@server.tool(
    name="unifi_get_ips_events",
    description=(
        "Get IPS/IDS security events (intrusion detection/prevention alerts). "
        "Reads the legacy IPS endpoint and, when it is empty or gone (Network 10.x), the SECURITY "
        "category of the v2 system log, where threat blocks are recorded. For other security "
        "event types use unifi_list_events with categories=['SECURITY']."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_ips_events(
    duration: Annotated[
        str,
        Field(description="Time period: 'hourly' (1h, default), 'daily' (24h), 'weekly' (7d), or 'monthly' (30d)"),
    ] = "daily",
    limit: Annotated[int, Field(description="Maximum number of events to return (default 50)")] = 50,
) -> Dict[str, Any]:
    """Implementation for getting IPS/IDS events."""
    try:
        duration_hours = _duration_hours(duration)
        events = await stats_manager.get_ips_events(duration_hours=duration_hours, limit=limit)
        return {
            "success": True,
            "site": stats_manager._connection.site,
            "duration": duration,
            "limit": limit,
            "count": len(events),
            "events": events,
        }
    except Exception as e:
        logger.error("Error getting IPS events: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get IPS events: {e}"}


@server.tool(
    name="unifi_get_client_sessions",
    description=(
        "Get client session history. Note: this endpoint tracks hotspot/captive portal "
        "authorization sessions, not general WiFi connect/disconnect events. "
        "Returns empty without a guest portal configured. "
        "For WiFi roaming events, use the event log instead."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_client_sessions(
    mac_address: Annotated[
        Optional[str],
        Field(description="Client MAC address. If omitted, returns sessions for all clients."),
    ] = None,
    duration: Annotated[
        str,
        Field(description="Time period: 'hourly' (1h, default), 'daily' (24h), 'weekly' (7d), or 'monthly' (30d)"),
    ] = "daily",
    limit: Annotated[int, Field(description="Maximum number of sessions to return (default 50)")] = 50,
) -> Dict[str, Any]:
    """Implementation for getting client session history."""
    try:
        duration_hours = _duration_hours(duration)
        sessions = await stats_manager.get_client_sessions(
            client_mac=mac_address, duration_hours=duration_hours, limit=limit
        )
        shaped = [client_session_from_controller(s).model_dump(exclude_none=True) for s in sessions]
        result: Dict[str, Any] = {
            "success": True,
            "site": stats_manager._connection.site,
            "duration": duration,
            "limit": limit,
            "count": len(shaped),
            "sessions": shaped,
        }
        if mac_address:
            result["client_mac"] = mac_address
        return result
    except Exception as e:
        logger.error("Error getting client sessions: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to get client sessions: {type(e).__name__}"}


@server.tool(
    name="unifi_get_dashboard",
    description=(
        "Get the pre-aggregated site dashboard. Defaults to a compact summary that omits "
        "high-volume activity/history series; pass summary=false to preserve raw dashboard entries."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_dashboard(
    summary: Annotated[
        bool,
        Field(description="Omit high-volume activity/history series; default true"),
    ] = True,
    history_seconds: Annotated[
        int,
        Field(ge=300, le=2_592_000, description="Dashboard history window in seconds"),
    ] = 86400,
) -> Dict[str, Any]:
    """Implementation for getting the site dashboard summary."""
    try:
        dashboard = await stats_manager.get_dashboard(history_seconds=history_seconds)
        return shape_dashboard(
            dashboard,
            site=stats_manager._connection.site,
            summary=summary,
            history_seconds=history_seconds,
        )
    except Exception as e:
        logger.error("Error getting dashboard: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get dashboard: {e}"}


@server.tool(
    name="unifi_get_anomalies",
    description="Get network anomaly detection events.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_anomalies(
    duration: Annotated[
        str,
        Field(description="Time period: 'hourly' (1h, default), 'daily' (24h), 'weekly' (7d), or 'monthly' (30d)"),
    ] = "daily",
) -> Dict[str, Any]:
    """Implementation for getting anomaly events."""
    try:
        duration_hours = _duration_hours(duration)
        anomalies = await stats_manager.get_anomalies(duration_hours=duration_hours)
        return {
            "success": True,
            "site": stats_manager._connection.site,
            "duration": duration,
            "count": len(anomalies),
            "anomalies": anomalies,
        }
    except Exception as e:
        logger.error("Error getting anomalies: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get anomalies: {e}"}


@server.tool(
    name="unifi_get_client_wifi_details",
    description=(
        "Get detailed WiFi statistics for a single wireless client including signal, noise, "
        "satisfaction, tx/rx rates, retries, roam count, channel, radio, ESSID, and more."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_client_wifi_details(
    mac_address: Annotated[str, Field(description="Client MAC address")],
) -> Dict[str, Any]:
    """Implementation for getting detailed WiFi stats for a wireless client."""
    try:
        wifi_details = await stats_manager.get_client_wifi_details(mac_address)
        if not wifi_details:
            return {"success": False, "error": f"Client '{mac_address}' not found or is not wireless."}

        shaped = client_wifi_details_from_controller(wifi_details)
        return {
            "success": True,
            "site": stats_manager._connection.site,
            "client_mac": mac_address,
            "wifi_details": shaped.model_dump(exclude_none=True),
        }
    except Exception as e:
        logger.error("Error getting WiFi details: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to get WiFi details: {type(e).__name__}"}
