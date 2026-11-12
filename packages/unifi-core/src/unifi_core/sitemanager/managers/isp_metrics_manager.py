"""ISP metrics from the Site Manager API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from unifi_core.exceptions import UniFiMalformedResponseError, UniFiValidationError
from unifi_core.sitemanager.managers.connection_manager import SiteManagerConnectionManager, path_segment
from unifi_core.sitemanager.managers.inventory_manager import rfc3339
from unifi_core.sitemanager.models._coerce import as_dict, text
from unifi_core.sitemanager.models.isp_metrics import (
    DEFAULT_PERIOD_LIMIT,
    MAX_PERIODS,
    IspMetricSeries,
    series_from_api,
)

# Windows the API accepts for each interval, first entry the default.
DURATIONS: dict[str, tuple[str, ...]] = {"5m": ("24h",), "1h": ("7d", "30d")}
MAX_QUERY_SITES = 50


@dataclass(frozen=True, slots=True)
class IspMetricsQueryResult:
    """Result of a per-site metrics query."""

    series: list[IspMetricSeries]
    partial: bool
    message: str | None


def _interval(metric_type: Any) -> str:
    if metric_type not in DURATIONS:
        raise UniFiValidationError("metric_type must be 5m or 1h")
    return metric_type


def _period_limit(period_limit: Any) -> int:
    if isinstance(period_limit, bool) or not isinstance(period_limit, int) or not 0 <= period_limit <= MAX_PERIODS:
        raise UniFiValidationError(f"period_limit must be between 0 and {MAX_PERIODS}")
    return period_limit


def _series(data: Any, period_limit: int) -> list[IspMetricSeries]:
    if not isinstance(data, list):
        raise UniFiMalformedResponseError("Site Manager API returned unreadable ISP metrics.")
    return [series_from_api(entry, period_limit=period_limit) for entry in data]


class IspMetricsManager:
    """Reads WAN performance metrics for the account's sites."""

    def __init__(self, connection: SiteManagerConnectionManager) -> None:
        self._connection = connection

    async def get_metrics(
        self,
        metric_type: str,
        *,
        duration: str | None = None,
        begin_timestamp: str | None = None,
        end_timestamp: str | None = None,
        period_limit: int = DEFAULT_PERIOD_LIMIT,
    ) -> list[IspMetricSeries]:
        """Metrics for every site the account can see.

        Give either ``duration`` or a ``begin_timestamp``/``end_timestamp``
        range. With neither, the interval's shortest window is used.
        """
        interval = _interval(metric_type)
        limit = _period_limit(period_limit)
        has_range = begin_timestamp is not None or end_timestamp is not None
        if duration is not None and has_range:
            raise UniFiValidationError("Give either duration or begin_timestamp/end_timestamp, not both")
        params: list[tuple[str, str]] = []
        if has_range:
            if begin_timestamp is None or end_timestamp is None:
                raise UniFiValidationError("begin_timestamp and end_timestamp must be given together")
            params.append(("beginTimestamp", rfc3339(begin_timestamp, "begin_timestamp")))
            params.append(("endTimestamp", rfc3339(end_timestamp, "end_timestamp")))
        else:
            allowed = DURATIONS[interval]
            chosen = duration if duration is not None else allowed[0]
            if chosen not in allowed:
                raise UniFiValidationError(f"duration for {interval} metrics must be one of: {', '.join(allowed)}")
            params.append(("duration", chosen))
        response = await self._connection.get(f"/v1/isp-metrics/{path_segment(interval, 'metric type')}", params=params)
        return _series(response.data, limit)

    async def query_metrics(
        self,
        metric_type: str,
        sites: list[dict[str, Any]],
        *,
        period_limit: int = DEFAULT_PERIOD_LIMIT,
    ) -> IspMetricsQueryResult:
        """Metrics for named sites, each optionally with its own time range.

        Each entry of ``sites`` needs ``host_id`` and ``site_id`` and may give
        ``begin_timestamp`` and ``end_timestamp``.
        """
        interval = _interval(metric_type)
        limit = _period_limit(period_limit)
        if not isinstance(sites, list) or not 1 <= len(sites) <= MAX_QUERY_SITES:
            raise UniFiValidationError(f"sites must list between 1 and {MAX_QUERY_SITES} sites")
        body_sites: list[dict[str, str]] = []
        for site in sites:
            entry = as_dict(site)
            host_id, site_id = text(entry.get("host_id")), text(entry.get("site_id"))
            if host_id is None or site_id is None:
                raise UniFiValidationError("Each site needs host_id and site_id")
            item = {"hostId": host_id, "siteId": site_id}
            for field, api_field in (("begin_timestamp", "beginTimestamp"), ("end_timestamp", "endTimestamp")):
                if entry.get(field) is not None:
                    item[api_field] = rfc3339(entry[field], field)
            body_sites.append(item)
        response = await self._connection.post(
            f"/v1/isp-metrics/{path_segment(interval, 'metric type')}/query", json_body={"sites": body_sites}
        )
        data = response.data
        if not isinstance(data, dict) or not isinstance(data.get("metrics"), list):
            raise UniFiMalformedResponseError("Site Manager API returned unreadable ISP metrics.")
        return IspMetricsQueryResult(
            series=_series(data["metrics"], limit),
            partial=text(data.get("status")) == "partialSuccess",
            message=text(data.get("message")),
        )
