"""Manager for UniFi Network Traffic Flows (private v2 /traffic-flows endpoint).

Read-only. Results are cached with a short ~45s TTL keyed on the full query
body (sorted JSON) and the active site, matching the 60s alerts-cache precedent
used by upstream stats managers. Mirrors the ApiRequestV2 pattern used by
event_manager for /system-log.
"""

import json
from typing import Any, Dict

from aiounifi.models.api import ApiRequestV2

from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.models.traffic_flows import (
    TrafficFlowQuery,
    traffic_flow_from_controller,
    traffic_flow_statistics_from_controller,
)

_FLOWS_CACHE_TTL = 45  # seconds; short-lived, matching the 60s alerts-cache precedent

# Periods accepted by /traffic-flow-latest-statistics (the UI's 1h/1D/1W/1M).
_STATISTICS_PERIODS = ("HOUR", "DAY", "WEEK", "MONTH")

# User-facing filter arrays (populated from TrafficFlowQuery).
_FILTER_FIELDS = (
    "risk",
    "action",
    "direction",
    "protocol",
    "service",
    "source_mac",
    "source_ip",
    "source_host",
    "source_network_id",
    "destination_domain",
    "destination_ip",
    "destination_region",
)
# Remaining array fields the endpoint expects present in the body; not exposed
# as filters in v1, so always sent as empty arrays.
_ALL_ARRAY_FIELDS = _FILTER_FIELDS + (
    "policy",
    "policy_type",
    "source_port",
    "source_domain",
    "source_zone_id",
    "source_region",
    "destination_host",
    "destination_mac",
    "destination_port",
    "destination_network_id",
    "destination_zone_id",
    "in_network_id",
    "out_network_id",
    "next_ai_query",
    "except_for",
)


class TrafficFlowManager:
    """Reads completed traffic flows from the controller's private v2 API."""

    def __init__(self, connection_manager: ConnectionManager):
        self._connection = connection_manager

    def _build_body(self, query: TrafficFlowQuery) -> Dict[str, Any]:
        if query.time_from is None or query.time_to is None:
            raise ValueError("time_from and time_to are required")
        body: Dict[str, Any] = {field: [] for field in _ALL_ARRAY_FIELDS}
        for field in _FILTER_FIELDS:
            value = getattr(query, field, None)
            if value:
                body[field] = list(value)
        body["timestampFrom"] = query.time_from
        body["timestampTo"] = query.time_to
        body["pageNumber"] = query.page_number
        body["pageSize"] = query.page_size
        body["search_text"] = query.search_text or ""
        body["skip_count"] = False
        return body

    async def get_traffic_flows(self, query: TrafficFlowQuery) -> Dict[str, Any]:
        """POST the query and return the full pagination envelope.

        Results are cached for ~45s keyed on the full query body and active site.
        Errors propagate to the caller; the tool layer logs and maps them.
        """
        body = self._build_body(query)
        cache_key = "traffic_flows_" + json.dumps(body, sort_keys=True) + f"_{self._connection.site}"
        cached = self._connection.get_cached(cache_key, timeout=_FLOWS_CACHE_TTL)
        if cached is not None:
            return cached

        api_request = ApiRequestV2(method="post", path="/traffic-flows", data=body)
        # ConnectionManager.request() returns the decoded v2 response. aiounifi's
        # ApiRequestV2.decode wraps the envelope dict as data=[envelope], so the
        # full pagination envelope arrives list-wrapped (unwrapped just below),
        # mirroring event_manager's /system-log path.
        response = await self._connection.request(api_request)

        if isinstance(response, list):
            response = response[0] if response else {}
        if not isinstance(response, dict):
            response = {}

        raw_flows = response.get("data") or []
        flows = [traffic_flow_from_controller(f).model_dump(exclude_none=True) for f in raw_flows]
        result = {
            "flows": flows,
            "page_number": response.get("page_number", query.page_number),
            "total_element_count": response.get("total_element_count", len(flows)),
            "total_page_count": response.get("total_page_count", 1),
            "has_next": response.get("has_next", False),
            "or_more": response.get("or_more", False),
        }
        self._connection._update_cache(cache_key, result, timeout=_FLOWS_CACHE_TTL)
        return result

    async def get_traffic_flow_statistics(self, period: str = "DAY", top: int = 10) -> Dict[str, Any]:
        """Fetch aggregated Insights > Flows statistics (latest-statistics).

        ``period`` is one of HOUR/DAY/WEEK/MONTH (the UI's 1h/1D/1W/1M); ``top``
        bounds each Top-Talker ranking (clamped 1-100). Validated client-side so
        an unknown period fails clearly instead of as an opaque controller 400.
        Cached ~45s keyed on period+top+site.
        """
        period = (period or "").upper()
        if period not in _STATISTICS_PERIODS:
            raise ValueError(f"period must be one of {', '.join(_STATISTICS_PERIODS)}")
        top = max(1, min(int(top), 100))

        cache_key = f"traffic_flow_statistics_{period}_{top}_{self._connection.site}"
        cached = self._connection.get_cached(cache_key, timeout=_FLOWS_CACHE_TTL)
        if cached is not None:
            return cached

        api_request = ApiRequestV2(method="get", path=f"/traffic-flow-latest-statistics?period={period}&top={top}")
        response = await self._connection.request(api_request)

        # aiounifi's ApiRequestV2.decode list-wraps the response object (data=[obj]),
        # mirroring the /traffic-flows path; unwrap to the single statistics object.
        if isinstance(response, list):
            response = response[0] if response else {}
        if not isinstance(response, dict):
            response = {}

        result = traffic_flow_statistics_from_controller(response).model_dump()
        self._connection._update_cache(cache_key, result, timeout=_FLOWS_CACHE_TTL)
        return result
