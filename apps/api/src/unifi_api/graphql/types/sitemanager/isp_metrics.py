"""Explicit Site Manager isp_metrics read shapes."""

import strawberry
from strawberry.scalars import JSON

from unifi_api.graphql.types.sitemanager._base import DESCRIPTION, Projection


@strawberry.type(description=DESCRIPTION)
class SiteManagerIspMetricPeriod(Projection):
    time: JSON | None = strawberry.field(description="Start of the interval")
    avg_latency_ms: float | None = strawberry.field(description="Average latency in milliseconds")
    max_latency_ms: float | None = strawberry.field(description="Maximum latency in milliseconds")
    packet_loss: float | None = strawberry.field(description="Packet loss as reported by the API")
    download_kbps: float | None = strawberry.field(description="Download throughput in kbps")
    upload_kbps: float | None = strawberry.field(description="Upload throughput in kbps")
    uptime: float | None = strawberry.field(description="Uptime within the interval as reported")
    downtime: float | None = strawberry.field(description="Downtime within the interval as reported")
    isp_name: str | None = strawberry.field(description="ISP name")
    isp_asn: str | None = strawberry.field(description="ISP autonomous system number")
    _columns = []


@strawberry.type(description=DESCRIPTION)
class SiteManagerIspMetricSummary(Projection):
    period_count: int = strawberry.field(description="Number of periods in the window")
    first_time: JSON | None = strawberry.field(description="Time of the earliest period")
    last_time: JSON | None = strawberry.field(description="Time of the latest period")
    avg_latency_ms: float | None = strawberry.field(description="Mean of the periods' average latency")
    max_latency_ms: float | None = strawberry.field(description="Highest latency in the window")
    avg_packet_loss: float | None = strawberry.field(description="Mean packet loss")
    avg_download_kbps: float | None = strawberry.field(description="Mean download throughput in kbps")
    avg_upload_kbps: float | None = strawberry.field(description="Mean upload throughput in kbps")
    total_downtime: float | None = strawberry.field(description="Sum of reported downtime")
    periods_with_downtime: int = strawberry.field(description="Number of periods reporting any downtime")
    _columns = []


@strawberry.type(description=DESCRIPTION)
class SiteManagerIspMetricSeries(Projection):
    host_id: str | None = strawberry.field(description="Site Manager host id")
    site_id: str | None = strawberry.field(description="Site Manager site id")
    metric_type: str | None = strawberry.field(description="Interval of the series: 5m or 1h")
    summary: SiteManagerIspMetricSummary = strawberry.field(description="Aggregates over the window")
    periods: list[SiteManagerIspMetricPeriod] = strawberry.field(description="Most recent periods, oldest first")
    periods_truncated: bool = strawberry.field(description="Whether older periods were left out of periods")

    _nested = {"summary": (SiteManagerIspMetricSummary, False), "periods": (SiteManagerIspMetricPeriod, True)}
    _columns = ["host_id", "site_id", "metric_type"]


@strawberry.type(description=DESCRIPTION)
class SiteManagerIspMetrics(Projection):
    items: list[SiteManagerIspMetricSeries]
    next_cursor: str | None
    count: int
    _nested = {"items": (SiteManagerIspMetricSeries, True)}


@strawberry.type(description=DESCRIPTION)
class SiteManagerIspMetricsQueryResult(Projection):
    _columns = ["partial", "count"]
    items: list[SiteManagerIspMetricSeries]
    next_cursor: str | None
    count: int
    partial: bool
    message: str | None
    _nested = {"items": (SiteManagerIspMetricSeries, True)}

    @classmethod
    def from_manager_output(cls, obj, *, redact_sensitive=True):
        from unifi_api.graphql.types.sitemanager._base import plain

        value = plain(obj)
        if "series" in value:
            value = {
                "items": value["series"],
                "next_cursor": None,
                "count": len(value["series"]),
                "partial": value["partial"],
                "message": value["message"],
            }
        return super().from_manager_output(value, redact_sensitive=redact_sensitive)
