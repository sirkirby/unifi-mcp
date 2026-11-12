"""Bounded account ISP metric reads, including the read-only POST query."""

from fastapi import APIRouter, Query, Request
from unifi_core.sitemanager.models.isp_metrics import SiteManagerMetricsQueryInput

from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.sitemanager._base import DESCRIPTION
from unifi_api.graphql.types.sitemanager.isp_metrics import SiteManagerIspMetrics, SiteManagerIspMetricsQueryResult
from unifi_api.routes.resources.sitemanager._common import AccountReadRoute, read

router = APIRouter(prefix="/sitemanager", route_class=AccountReadRoute, tags=["sitemanager/isp-metrics"])


@router.get("/isp-metrics", description=DESCRIPTION, response_model=to_pydantic_model(SiteManagerIspMetrics))
async def get_sitemanager_isp_metrics(
    request: Request,
    metric_type: str = "1h",
    duration: str | None = None,
    begin_timestamp: str | None = None,
    end_timestamp: str | None = None,
    period_limit: int = Query(12, ge=0, le=720),
):
    return await read(
        request,
        "sitemanager_get_isp_metrics",
        {
            "metric_type": metric_type,
            "duration": duration,
            "begin_timestamp": begin_timestamp,
            "end_timestamp": end_timestamp,
            "period_limit": period_limit,
        },
        query_fields={"metric_type", "duration", "begin_timestamp", "end_timestamp", "period_limit"},
    )


@router.post(
    "/isp-metrics/query", description=DESCRIPTION, response_model=to_pydantic_model(SiteManagerIspMetricsQueryResult)
)
async def query_sitemanager_isp_metrics(request: Request, body: SiteManagerMetricsQueryInput):
    return await read(request, "sitemanager_query_isp_metrics", body.model_dump(exclude_none=True), query_fields=set())
