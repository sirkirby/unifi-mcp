"""Site Manager ISP metrics: per-site WAN latency, throughput, loss and uptime over time.

The API returns every period of the requested window with no paging (up to
288 five-minute or 720 one-hour periods per site), so each series carries a
summary of the whole window and only the most recent periods by default.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from unifi_core.sitemanager.models._coerce import as_dict, as_list, number, text, timestamp

MAX_PERIODS = 720
DEFAULT_PERIOD_LIMIT = 12


class IspMetricPeriod(BaseModel):
    """WAN measurements for one interval."""

    model_config = ConfigDict(extra="ignore")

    time: str | int | None = Field(default=None, description="Start of the interval")
    avg_latency_ms: int | float | None = Field(default=None, description="Average latency in milliseconds")
    max_latency_ms: int | float | None = Field(default=None, description="Maximum latency in milliseconds")
    packet_loss: int | float | None = Field(default=None, description="Packet loss as reported by the API")
    download_kbps: int | float | None = Field(default=None, description="Download throughput in kbps")
    upload_kbps: int | float | None = Field(default=None, description="Upload throughput in kbps")
    uptime: int | float | None = Field(default=None, description="Uptime within the interval as reported")
    downtime: int | float | None = Field(default=None, description="Downtime within the interval as reported")
    isp_name: str | None = Field(default=None, description="ISP name")
    isp_asn: str | None = Field(default=None, description="ISP autonomous system number")


class IspMetricSummary(BaseModel):
    """Aggregates over every period the API returned for a site, not only the periods listed."""

    model_config = ConfigDict(extra="ignore")

    period_count: int = Field(default=0, description="Number of periods in the window")
    first_time: str | int | None = Field(default=None, description="Time of the earliest period")
    last_time: str | int | None = Field(default=None, description="Time of the latest period")
    avg_latency_ms: float | None = Field(default=None, description="Mean of the periods' average latency")
    max_latency_ms: int | float | None = Field(default=None, description="Highest latency in the window")
    avg_packet_loss: float | None = Field(default=None, description="Mean packet loss")
    avg_download_kbps: float | None = Field(default=None, description="Mean download throughput in kbps")
    avg_upload_kbps: float | None = Field(default=None, description="Mean upload throughput in kbps")
    total_downtime: int | float | None = Field(default=None, description="Sum of reported downtime")
    periods_with_downtime: int = Field(default=0, description="Number of periods reporting any downtime")


class IspMetricSeries(BaseModel):
    """ISP metrics for one site."""

    model_config = ConfigDict(extra="ignore")

    host_id: str | None = Field(default=None, description="Site Manager host id")
    site_id: str | None = Field(default=None, description="Site Manager site id")
    metric_type: str | None = Field(default=None, description="Interval of the series: 5m or 1h")
    summary: IspMetricSummary = Field(default_factory=IspMetricSummary, description="Aggregates over the window")
    periods: list[IspMetricPeriod] = Field(default_factory=list, description="Most recent periods, oldest first")
    periods_truncated: bool = Field(default=False, description="Whether older periods were left out of periods")


def _period(raw: Any) -> IspMetricPeriod:
    entry = as_dict(raw)
    wan = as_dict(as_dict(entry.get("data")).get("wan"))
    return IspMetricPeriod(
        time=timestamp(entry.get("metricTime")),
        avg_latency_ms=number(wan.get("avgLatency")),
        max_latency_ms=number(wan.get("maxLatency")),
        packet_loss=number(wan.get("packetLoss")),
        download_kbps=number(wan.get("download_kbps")),
        upload_kbps=number(wan.get("upload_kbps")),
        uptime=number(wan.get("uptime")),
        downtime=number(wan.get("downtime")),
        isp_name=text(wan.get("ispName")),
        isp_asn=text(wan.get("ispAsn")),
    )


def _mean(values: list[int | float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _present(periods: list[IspMetricPeriod], field: str) -> list[int | float]:
    return [value for period in periods if (value := getattr(period, field)) is not None]


def _summary(periods: list[IspMetricPeriod]) -> IspMetricSummary:
    max_latency = _present(periods, "max_latency_ms")
    downtime = _present(periods, "downtime")
    return IspMetricSummary(
        period_count=len(periods),
        first_time=periods[0].time if periods else None,
        last_time=periods[-1].time if periods else None,
        avg_latency_ms=_mean(_present(periods, "avg_latency_ms")),
        max_latency_ms=max(max_latency) if max_latency else None,
        avg_packet_loss=_mean(_present(periods, "packet_loss")),
        avg_download_kbps=_mean(_present(periods, "download_kbps")),
        avg_upload_kbps=_mean(_present(periods, "upload_kbps")),
        total_downtime=sum(downtime) if downtime else None,
        periods_with_downtime=sum(1 for value in downtime if value > 0),
    )


def series_from_api(raw: Any, *, period_limit: int = DEFAULT_PERIOD_LIMIT) -> IspMetricSeries:
    """Build an :class:`IspMetricSeries`, keeping the ``period_limit`` most recent periods."""
    entry = as_dict(raw)
    periods = [_period(period) for period in as_list(entry.get("periods"))]
    limit = max(0, min(period_limit, MAX_PERIODS))
    kept = periods[len(periods) - limit :] if limit else []
    return IspMetricSeries(
        host_id=text(entry.get("hostId")),
        site_id=text(entry.get("siteId")),
        metric_type=text(entry.get("metricType")),
        summary=_summary(periods),
        periods=kept,
        periods_truncated=len(kept) < len(periods),
    )
