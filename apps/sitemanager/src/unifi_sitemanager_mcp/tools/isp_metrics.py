"""ISP metrics tools: WAN latency, speed, uptime and packet loss per site."""

import logging
from typing import Annotated, Any, Dict, Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_sitemanager_mcp.runtime import isp_metrics_manager, server, tool_failure, tool_success

logger = logging.getLogger(__name__)

MetricType = Annotated[
    Literal["5m", "1h"],
    Field(description="Interval of each period: 5m (kept for 24 hours) or 1h (kept for 30 days)."),
]
PeriodLimit = Annotated[
    int,
    Field(
        description=(
            "How many of the most recent periods to return per site (0-720). The summary always covers the "
            "whole window. Raise it for the full series; 0 returns the summary alone."
        )
    ),
]


@server.tool(
    name="sitemanager_get_isp_metrics",
    title="Get ISP Metrics",
    description=(
        "Returns WAN performance for every site the account can see: latency, download and upload speed, "
        "uptime, downtime and packet loss. Each site gets a summary over the window plus its most recent "
        "periods. Give duration, or begin_timestamp with end_timestamp, not both."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="isp_metrics",
    permission_action="read",
    auth="api_key_only",
)
async def sitemanager_get_isp_metrics(
    metric_type: MetricType = "1h",
    duration: Annotated[
        Literal["24h", "7d", "30d"] | None,
        Field(description="Window ending now: 24h for 5m metrics; 7d or 30d for 1h metrics. Omit for the shortest."),
    ] = None,
    begin_timestamp: Annotated[
        str | None, Field(description="RFC 3339 start of the window. Requires end_timestamp.")
    ] = None,
    end_timestamp: Annotated[
        str | None, Field(description="RFC 3339 end of the window. Requires begin_timestamp.")
    ] = None,
    period_limit: PeriodLimit = 12,
) -> Dict[str, Any]:
    """Get ISP metrics for every site."""
    logger.info("sitemanager_get_isp_metrics tool called")
    try:
        series = await isp_metrics_manager.get_metrics(
            metric_type,
            duration=duration,
            begin_timestamp=begin_timestamp,
            end_timestamp=end_timestamp,
            period_limit=period_limit,
        )
        return tool_success({"sites": [entry.model_dump(exclude_none=True) for entry in series], "count": len(series)})
    except Exception as e:
        return tool_failure("get ISP metrics", e)


@server.tool(
    name="sitemanager_query_isp_metrics",
    title="Query ISP Metrics",
    description=(
        "Returns WAN performance for named sites, each optionally with its own time range. Read-only: it "
        "changes nothing. Take host_id and site_id from sitemanager_list_sites. partial is true when some "
        "requested sites were left out."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="isp_metrics",
    permission_action="read",
    auth="api_key_only",
)
async def sitemanager_query_isp_metrics(
    sites: Annotated[
        list[dict[str, Any]],
        Field(
            description=(
                "1-50 sites. Each entry needs host_id and site_id (Site Manager ids) and may give "
                "begin_timestamp and end_timestamp as RFC 3339 strings."
            )
        ),
    ],
    metric_type: MetricType = "1h",
    period_limit: PeriodLimit = 12,
) -> Dict[str, Any]:
    """Get ISP metrics for named sites."""
    logger.info("sitemanager_query_isp_metrics tool called")
    try:
        result = await isp_metrics_manager.query_metrics(metric_type, sites, period_limit=period_limit)
        data: Dict[str, Any] = {
            "sites": [entry.model_dump(exclude_none=True) for entry in result.series],
            "count": len(result.series),
            "partial": result.partial,
        }
        if result.message:
            data["message"] = result.message
        return tool_success(data)
    except Exception as e:
        return tool_failure("query ISP metrics", e)
