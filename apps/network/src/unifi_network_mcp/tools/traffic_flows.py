"""Traffic Flows reader tool for the UniFi Network MCP server.

Read-only. Queries the private v2 /traffic-flows endpoint with a historical
time window, server-side filters, and pagination. Returns one page of flows
plus pagination metadata. Stateless — no caching.
"""

import logging
import time
from typing import Annotated, Any, Dict, List, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.network.models.traffic_flows import TrafficFlowQuery
from unifi_network_mcp.runtime import server, traffic_flow_manager

logger = logging.getLogger(__name__)


def _as_list(value: Optional[str]) -> Optional[List[str]]:
    return [value] if value else None


@server.tool(
    name="unifi_get_traffic_flows",
    description=(
        "Query historical UniFi Traffic Flows (Insights > Flows). Returns completed flow "
        "records — source/destination (incl. resolved destination domains), service, risk, "
        "action, bytes, and timestamps — for a time window, with server-side filtering and "
        "pagination. Supply both time_from and time_to (epoch ms) for an explicit window, or "
        "use within_hours. Read-only; one page per call (use page/total_page_count to paginate)."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_traffic_flows(
    within_hours: Annotated[
        int, Field(ge=1, le=8760, description="Look-back window in hours (used when time_from/time_to absent)")
    ] = 24,
    time_from: Annotated[Optional[int], Field(description="Explicit window start, epoch ms")] = None,
    time_to: Annotated[Optional[int], Field(description="Explicit window end, epoch ms")] = None,
    source_mac: Annotated[Optional[str], Field(description="Filter by source MAC")] = None,
    source_ip: Annotated[Optional[str], Field(description="Filter by source IP")] = None,
    source_name: Annotated[Optional[str], Field(description="Filter by source host/client name")] = None,
    source_network_id: Annotated[Optional[str], Field(description="Filter by source network ID")] = None,
    destination_domain: Annotated[Optional[str], Field(description="Filter by destination domain")] = None,
    destination_ip: Annotated[Optional[str], Field(description="Filter by destination IP")] = None,
    destination_region: Annotated[Optional[str], Field(description="Filter by destination region/country")] = None,
    risk: Annotated[Optional[str], Field(description="Filter by risk (low/medium/high)")] = None,
    action: Annotated[Optional[str], Field(description="Filter by action (allowed/blocked)")] = None,
    service: Annotated[Optional[str], Field(description="Filter by service")] = None,
    protocol: Annotated[Optional[str], Field(description="Filter by protocol")] = None,
    direction: Annotated[Optional[str], Field(description="Filter by direction")] = None,
    search_text: Annotated[Optional[str], Field(description="Free-text match (destination domain/host aware)")] = None,
    page: Annotated[int, Field(ge=0, description="0-based page number")] = 0,
    page_size: Annotated[int, Field(description="Rows per page (<=1000)")] = 100,
) -> Dict[str, Any]:
    """Query historical traffic flows."""
    if (time_from is None) != (time_to is None):
        return {"success": False, "error": "provide both time_from and time_to, or use within_hours"}
    if time_from is None:
        if within_hours <= 0:
            return {"success": False, "error": "within_hours must be a positive integer"}
        now_ms = int(time.time() * 1000)
        time_from = now_ms - within_hours * 3600 * 1000
        time_to = now_ms

    try:
        query = TrafficFlowQuery(
            time_from=time_from,
            time_to=time_to,
            page_number=page,
            page_size=max(1, min(page_size, 1000)),
            search_text=search_text,
            risk=_as_list(risk),
            action=_as_list(action),
            direction=_as_list(direction),
            protocol=_as_list(protocol),
            service=_as_list(service),
            source_mac=_as_list(source_mac),
            source_ip=_as_list(source_ip),
            source_host=_as_list(source_name),
            source_network_id=_as_list(source_network_id),
            destination_domain=_as_list(destination_domain),
            destination_ip=_as_list(destination_ip),
            destination_region=_as_list(destination_region),
        )
        result = await traffic_flow_manager.get_traffic_flows(query)
        return {"success": True, "site": traffic_flow_manager._connection.site, **result}
    except Exception as e:
        logger.error("Error getting traffic flows: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get traffic flows: {e}"}


@server.tool(
    name="unifi_get_traffic_flow_statistics",
    description=(
        "Aggregated UniFi Traffic Flows summary (Insights > Flows 'Flow Summary'). Returns risk and "
        "region count breakdowns plus Top-Talker rankings for a preset period: top clients, top "
        "destinations, top applications (by bytes), top blocked clients, and top blocking policies. "
        "Risk bands are low/medium/high (the UI labels these Low/Suspicious/Concerning). Application "
        "entries carry DPI application_id/category_id and bytes; application_name/category_name are "
        "null (DPI-catalog name resolution is not yet wired). Read-only."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_traffic_flow_statistics(
    period: Annotated[str, Field(description="Time window: HOUR, DAY, WEEK, or MONTH")] = "DAY",
    top: Annotated[int, Field(description="Entries per ranking (1-100)")] = 10,
) -> Dict[str, Any]:
    """Query aggregated traffic-flow statistics."""
    try:
        result = await traffic_flow_manager.get_traffic_flow_statistics(period=period, top=top)
        return {"success": True, "site": traffic_flow_manager._connection.site, **result}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting traffic flow statistics: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get traffic flow statistics: {e}"}
