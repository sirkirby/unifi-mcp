"""
Unifi Network MCP statistics tools.

This module provides MCP tools to fetch statistics from a Unifi Network Controller.
"""

import logging
from typing import Annotated, Any, Dict, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.network.models.sessions import (
    client_session_from_controller,
    client_wifi_details_from_controller,
)
from unifi_network_mcp.runtime import client_manager, device_manager, server, stats_manager

logger = logging.getLogger(__name__)


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
        duration_hours = {"hourly": 1, "daily": 24, "weekly": 168, "monthly": 720}.get(duration, 1)
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
    description="Get statistics for a specific client/device",
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
) -> Dict[str, Any]:
    """Implementation for getting client stats."""
    try:
        duration_hours = {"hourly": 1, "daily": 24, "weekly": 168, "monthly": 720}.get(duration, 1)
        client_details = await client_manager.get_client_details(client_id)
        if not client_details:
            return {"success": False, "error": f"Client '{client_id}' not found"}

        # Support aiounifi Client objects as well as dicts
        client_raw = client_details.raw if hasattr(client_details, "raw") else client_details
        client_mac = client_raw.get("mac", client_id)
        client_name = client_raw.get("name") or client_raw.get("hostname") or client_mac

        # Stats endpoint expects MAC, not _id
        stats = await stats_manager.get_client_stats(client_mac, duration_hours=duration_hours, granularity=granularity)
        summary = {
            "total_rx_bytes": sum(e.get("rx_bytes", 0) for e in stats),
            "total_tx_bytes": sum(e.get("tx_bytes", 0) for e in stats),
            "total_bytes": sum(e.get("bytes", e.get("rx_bytes", 0) + e.get("tx_bytes", 0)) for e in stats),
        }
        return {
            "success": True,
            "site": stats_manager._connection.site,
            "client_id": client_id,
            "client_name": client_name,
            "duration": duration,
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
        duration_hours = {"hourly": 1, "daily": 24, "weekly": 168, "monthly": 720}.get(duration, 1)
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
    description="Get a list of top clients by usage (sorted by total bytes)",
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
) -> Dict[str, Any]:
    """Implementation for getting top clients by usage."""
    try:
        duration_hours = {"hourly": 1, "daily": 24, "weekly": 168, "monthly": 720}.get(duration, 1)
        top_client_stats = await stats_manager.get_top_clients(duration_hours=duration_hours, limit=limit)

        enhanced_clients = []
        for entry in top_client_stats:
            mac = entry.get("mac")
            name = "Unknown"
            if mac:
                details = await client_manager.get_client_details(mac)
                if details:
                    raw = details.raw if hasattr(details, "raw") else details
                    name = raw.get("name") or raw.get("hostname") or mac
            entry["name"] = name
            enhanced_clients.append(entry)

        return {
            "success": True,
            "site": stats_manager._connection.site,
            "duration": duration,
            "limit": limit,
            "top_clients": enhanced_clients,
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

        def serialize_dpi(item):
            return item.raw if hasattr(item, "raw") else item

        serialized_apps = [serialize_dpi(app) for app in dpi_stats_result.get("applications", [])]
        serialized_cats = [serialize_dpi(cat) for cat in dpi_stats_result.get("categories", [])]

        return {
            "success": True,
            "site": stats_manager._connection.site,
            "dpi_stats": {
                "applications": serialized_apps,
                "categories": serialized_cats,
            },
        }
    except Exception as e:
        logger.error("Error getting DPI stats: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get DPI stats: {e}"}


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
        alerts = alerts[:limit]
        return {
            "success": True,
            "site": stats_manager._connection.site,
            "limit": limit,
            "include_archived": include_archived,
            "alerts": alerts,
        }
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
        duration_hours = {"hourly": 1, "daily": 24, "weekly": 168, "monthly": 720}.get(duration, 1)
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
        duration_hours = {"hourly": 1, "daily": 24, "weekly": 168, "monthly": 720}.get(duration, 24)
        results = await stats_manager.get_speedtest_results(duration_hours=duration_hours)

        formatted = []
        for r in results:
            entry: Dict[str, Any] = {}
            if "xput_download" in r:
                entry["download_mbps"] = round(r["xput_download"], 2)
            if "xput_upload" in r:
                entry["upload_mbps"] = round(r["xput_upload"], 2)
            if "latency" in r:
                entry["latency_ms"] = r["latency"]
            if "datetime" in r:
                entry["datetime"] = r["datetime"]
            elif "time" in r:
                entry["datetime"] = r["time"]
            # Preserve any extra fields
            for k, v in r.items():
                if k not in ("xput_download", "xput_upload", "latency", "datetime", "time"):
                    entry[k] = v
            formatted.append(entry)

        return {
            "success": True,
            "site": stats_manager._connection.site,
            "duration": duration,
            "count": len(formatted),
            "results": formatted,
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
) -> Dict[str, Any]:
    """Implementation for getting site-wide DPI traffic data."""
    try:
        traffic = await stats_manager.get_site_dpi_traffic(by=group_by)
        return {
            "success": True,
            "site": stats_manager._connection.site,
            "group_by": group_by,
            "traffic": traffic,
        }
    except Exception as e:
        logger.error("Error getting site DPI traffic: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get site DPI traffic: {e}"}


@server.tool(
    name="unifi_get_client_dpi_traffic",
    description=(
        "Get per-client DPI traffic data by application or category. "
        "Note: requires Traffic Identification to be enabled on the controller, "
        "which is separate from Device Identification."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_client_dpi_traffic(
    client_mac: Annotated[str, Field(description="Client MAC address")],
    group_by: Annotated[
        str,
        Field(description="Group results: 'by_app' (default) for per-application or 'by_cat' for per-category"),
    ] = "by_app",
) -> Dict[str, Any]:
    """Implementation for getting per-client DPI traffic data."""
    try:
        traffic = await stats_manager.get_client_dpi_traffic(client_mac=client_mac, by=group_by)
        return {
            "success": True,
            "site": stats_manager._connection.site,
            "client_mac": client_mac,
            "group_by": group_by,
            "traffic": traffic,
        }
    except Exception as e:
        logger.error("Error getting client DPI traffic for %s: %s", client_mac, e, exc_info=True)
        return {"success": False, "error": f"Failed to get client DPI traffic for {client_mac}: {e}"}


@server.tool(
    name="unifi_get_ips_events",
    description=(
        "Get IPS/IDS security events (intrusion detection/prevention alerts). "
        "Note: on newer UniFi OS / Network Application versions, IPS events may not populate "
        "this legacy endpoint. Check the controller's traffic flows for threat data instead."
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
        duration_hours = {"hourly": 1, "daily": 24, "weekly": 168, "monthly": 720}.get(duration, 24)
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
    client_mac: Annotated[
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
        duration_hours = {"hourly": 1, "daily": 24, "weekly": 168, "monthly": 720}.get(duration, 24)
        sessions = await stats_manager.get_client_sessions(
            client_mac=client_mac, duration_hours=duration_hours, limit=limit
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
        if client_mac:
            result["client_mac"] = client_mac
        return result
    except Exception as e:
        logger.error("Error getting client sessions: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get client sessions: {e}"}


@server.tool(
    name="unifi_get_dashboard",
    description="Get the pre-aggregated site dashboard summary (health, device counts, client counts, ISP status).",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_dashboard() -> Dict[str, Any]:
    """Implementation for getting the site dashboard summary."""
    try:
        dashboard = await stats_manager.get_dashboard()
        return {
            "success": True,
            "site": stats_manager._connection.site,
            "dashboard": dashboard,
        }
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
        duration_hours = {"hourly": 1, "daily": 24, "weekly": 168, "monthly": 720}.get(duration, 24)
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
    client_mac: Annotated[str, Field(description="Client MAC address")],
) -> Dict[str, Any]:
    """Implementation for getting detailed WiFi stats for a wireless client."""
    try:
        wifi_details = await stats_manager.get_client_wifi_details(client_mac)
        if not wifi_details:
            return {"success": False, "error": f"Client '{client_mac}' not found or is not wireless."}

        shaped = client_wifi_details_from_controller(wifi_details)
        return {
            "success": True,
            "site": stats_manager._connection.site,
            "client_mac": client_mac,
            "wifi_details": shaped.model_dump(exclude_none=True),
        }
    except Exception as e:
        logger.error("Error getting WiFi details for %s: %s", client_mac, e, exc_info=True)
        return {"success": False, "error": f"Failed to get WiFi details for {client_mac}: {e}"}
