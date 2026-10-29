import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from aiounifi.errors import Forbidden, RequestError
from aiounifi.models.api import ApiRequest, ApiRequestV2
from aiounifi.models.dpi_restriction_app import DPIRestrictionApp  # Import DPIApp model
from aiounifi.models.dpi_restriction_group import (
    DPIRestrictionGroup,
)  # Import DPIGroup model

from unifi_core.exceptions import UniFiMalformedResponseError
from unifi_core.mac import mac_equal, normalize_mac
from unifi_core.network import stats_series
from unifi_core.network.managers.client_manager import ClientManager  # Needed for get_top_clients
from unifi_core.network.managers.connection_manager import ConnectionManager, response_status
from unifi_core.network.managers.device_manager import DeviceManager
from unifi_core.network.managers.event_manager import _V2_ENVELOPE_KEYS, _v2_page, safe_request_error

logger = logging.getLogger("unifi-network-mcp")

# Cache prefixes
CACHE_PREFIX_STATS_NETWORK = "stats_network"
CACHE_PREFIX_STATS_CLIENT = "stats_client"
CACHE_PREFIX_STATS_DEVICE = "stats_device"
CACHE_PREFIX_STATS_DPI = "stats_dpi"
CACHE_PREFIX_STATS_ALERTS = "stats_alerts"
CACHE_PREFIX_STATS_GATEWAY = "stats_gateway"
CACHE_PREFIX_STATS_SPEEDTEST = "stats_speedtest"
CACHE_PREFIX_STATS_SITE_DPI = "stats_site_dpi"
CACHE_PREFIX_STATS_CLIENT_DPI = "stats_client_dpi"
CACHE_PREFIX_STATS_IPS = "stats_ips"
CACHE_PREFIX_STATS_SESSIONS = "stats_sessions"
CACHE_PREFIX_STATS_DASHBOARD = "stats_dashboard"
CACHE_PREFIX_STATS_ANOMALIES = "stats_anomalies"
CACHE_PREFIX_STATS_CLIENT_WIFI = "stats_client_wifi"

# Granularity validation
VALID_GRANULARITIES = {"5minutes", "hourly", "daily", "monthly"}


def _resolve_granularity(granularity: str) -> str:
    """Validate and return the granularity string.

    Args:
        granularity: One of 5minutes, hourly, daily, monthly.

    Returns:
        The validated granularity string.

    Raises:
        ValueError: If the granularity is not valid.
    """
    if granularity not in VALID_GRANULARITIES:
        raise ValueError(
            f"Invalid granularity '{granularity}'. Must be one of: {', '.join(sorted(VALID_GRANULARITIES))}"
        )
    return granularity


# Network 11 statistics engine: series metric -> legacy report field, per schema.
_SERIES_SITE_WAN = {"rxBytes": "wan-rx_bytes", "txBytes": "wan-tx_bytes"}
_SERIES_SITE_CLIENTS = {"distinctClientCount": "num_sta", "distinctUserClientCount": "num_user"}
_SERIES_AP = {
    "rxBytes": "rx_bytes",
    "txBytes": "tx_bytes",
    "distinctClientCount": "num_sta",
    "avgClientSatisfactionScore": "satisfaction",
    "wifiTxRetryPackets": "tx_retries",
    "wifiTxAttemptPackets": "wifi_tx_attempts",
    "wifiTxDroppedPackets": "wifi_tx_dropped",
}
_SERIES_GATEWAY_WAN = {"rxBytes": "wan-rx_bytes", "txBytes": "wan-tx_bytes"}
_SERIES_GATEWAY_SYSTEM = {"avgCpuUtilizationPct": "cpu", "avgMemoryUtilizationPct": "mem"}
_SERIES_DEVICE_TRAFFIC = {"rxBytes": "rx_bytes", "txBytes": "tx_bytes"}
_SERIES_DEVICE_CLIENTS = {"distinctClientCount": "num_sta"}
# Client series count from the client's side; the legacy report counts from
# the network's, so a client's rx is the report's tx.
_SERIES_CLIENT = {
    "rxBytes": "tx_bytes",
    "txBytes": "rx_bytes",
    "avgSignalDbm": "signal",
    "avgSatisfactionScore": "satisfaction",
    "wifiRxRetryPackets": "tx_retries",
    "wifiRxAttemptPackets": "wifi_tx_attempts",
    "maxRxRateTierKbps": "tx_rate",
}
_GATEWAY_TYPE_PREFIXES = ("ugw", "udm", "uxg")
_STATS_FORBIDDEN = (
    "This controller keeps statistics in the Network 11 statistics engine, and the account lacks "
    "permission for /v2/api/stats (HTTP 403). Use a Network account with the Full Admin role."
)
_STATS_SOURCE_UNKNOWN = (
    "The legacy statistics report returned nothing, and the check for the Network 11 statistics "
    "engine failed, so the history may be there instead. Retry the call."
)
_STATS_SOURCE_FORBIDDEN = "FORBIDDEN"
_STATS_SOURCE_LEGACY = "LEGACY"


class StatsPermissionError(RequestError):
    """The account cannot read the Network 11 statistics engine."""

    def __init__(self) -> None:
        super().__init__(_STATS_FORBIDDEN)


class StatsWindowError(ValueError):
    """The window is longer than the Network 11 statistics engine answers in one read."""

    def __init__(self) -> None:
        super().__init__("Network 11 statistics cover at most 30 days per call. Split the window into 30-day ranges.")


# Report retention on current controllers: 5-minute rows for ~12-24h, hourly
# for ~7d, daily for ~1y. Auto-selection stays inside the shortest of each.
_AUTO_5MIN_MAX_AGE_MS = 12 * 3600 * 1000
_AUTO_HOURLY_MAX_AGE_MS = 7 * 24 * 3600 * 1000


def _now_ms() -> int:
    return int(datetime.now().timestamp() * 1000)


def _safe_int(value: Any) -> int:
    """Parse a controller counter, treating anything non-numeric as 0."""
    try:
        if value is None:
            return 0
        if isinstance(value, (bool, int, float)):
            return int(value)  # NaN and infinity raise and are caught below
        return int(str(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def _window_ms(
    duration_hours: int,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    now_ms: Optional[int] = None,
) -> tuple[int, int]:
    """Resolve a report window in epoch milliseconds.

    An explicit ``start_ms`` wins over ``duration_hours``; ``end_ms`` defaults
    to ``now_ms`` (the current time unless given). Raises ValueError for an
    empty or inverted window.
    """
    if now_ms is None:
        now_ms = _now_ms()
    end = int(end_ms) if end_ms is not None else now_ms
    start = int(start_ms) if start_ms is not None else end - int(duration_hours) * 3600 * 1000
    if start >= end:
        raise ValueError("Report window start must be before its end.")
    return start, end


def _window_cache_key(start: int, end: int, start_ms: Optional[int], end_ms: Optional[int]) -> str:
    """Cache-key fragment for a resolved window.

    Bounds the caller pinned explicitly are keyed exactly, so two distinct
    absolute windows never share an entry; a bound that floats with "now"
    is bucketed to the minute so repeated moving-window calls still hit.
    """
    start_part = str(start) if start_ms is not None else f"m{start // 60000}"
    end_part = str(end) if end_ms is not None else f"m{end // 60000}"
    return f"{start_part}_{end_part}"


def _auto_granularity(start_ms: int, now_ms: int) -> str:
    """Pick the finest report granularity the controller still retains for start_ms.

    ``now_ms`` must be the same instant the window was resolved against, so a
    window exactly on a retention threshold always gets the same answer.
    """
    age = now_ms - start_ms
    if age <= _AUTO_5MIN_MAX_AGE_MS:
        return "5minutes"
    if age <= _AUTO_HOURLY_MAX_AGE_MS:
        return "hourly"
    return "daily"


_IPS_SUBCATEGORY = "SECURITY_INTRUSION_PREVENTION"
_IPS_V2_PAGE_SIZE = 100
_IPS_V2_MAX_PAGES = 10
_LOG_ROW_FIELDS = frozenset({"category", "subcategory", "event", "key"})


def _system_log_page(response: Any) -> tuple[List[Dict[str, Any]], int]:
    """Unwrap a v2 system-log page, which arrives as a dict, a one-element list or a bare list.

    Returns the dict rows and the page's raw row count, so a junk row doesn't make a
    full page look short.
    """
    if isinstance(response, list) and response and isinstance(response[0], dict):
        if _V2_ENVELOPE_KEYS.intersection(response[0]):
            if len(response) != 1:
                raise UniFiMalformedResponseError("Unexpected response shape from /system-log/all")
            response = response[0]
    data: Any = response
    if isinstance(response, dict):
        # Share count-only empty-envelope handling with event/alarm reads.
        data = _v2_page(response, "/system-log/all").rows
    if not isinstance(data, list):
        raise UniFiMalformedResponseError("Unexpected response shape from /system-log/all")
    rows = [row for row in data if isinstance(row, dict) and _LOG_ROW_FIELDS.intersection(row)]
    if data and not rows:
        raise UniFiMalformedResponseError("Unreadable rows in response from /system-log/all")
    return rows, len(data)


def _is_ips_event(row: Dict[str, Any]) -> bool:
    """True for intrusion-prevention rows; the SECURITY category also holds firewall blocks."""
    return row.get("subcategory") == _IPS_SUBCATEGORY


def _v2_traffic_payload(response: Any) -> Dict[str, Any]:
    """Unwrap the v2 /traffic response, which arrives as a dict or a one-element list."""
    if isinstance(response, list) and response and isinstance(response[0], dict):
        response = response[0]
    return response if isinstance(response, dict) else {}


def _group_dpi_usage(entries: List[Dict[str, Any]], by: str) -> List[Dict[str, Any]]:
    """Normalise v2 usage rows and optionally fold them into categories, largest first."""
    if by == "by_cat":
        folded: Dict[Any, Dict[str, Any]] = {}
        for e in entries:
            cat = e.get("category")
            row = folded.setdefault(
                cat, {"category": cat, "bytes_transmitted": 0, "bytes_received": 0, "total_bytes": 0}
            )
            for k in ("bytes_transmitted", "bytes_received", "total_bytes"):
                row[k] += _safe_int(e.get(k))
        rows = list(folded.values())
    else:
        rows = [dict(e) for e in entries]
    for row in rows:
        # v2 counts from the client's side: transmitted = uploaded by the client.
        row["upload_bytes"] = _safe_int(row.get("bytes_transmitted"))
        row["download_bytes"] = _safe_int(row.get("bytes_received"))
    return sorted(rows, key=lambda r: _safe_int(r.get("total_bytes")), reverse=True)


class StatsManager:
    """Manages statistics retrieval from the Unifi Controller."""

    def __init__(self, connection_manager: ConnectionManager, client_manager: ClientManager):
        """Initialize the Stats Manager.

        Args:
            connection_manager: The shared ConnectionManager instance.
            client_manager: The ClientManager instance (needed for some stats methods).
        """
        self._connection = connection_manager
        self._client_manager = client_manager

    # ------------------------------------------------------------------
    # Network 11 statistics engine
    # ------------------------------------------------------------------

    async def _stats_source(self) -> Optional[str]:
        """Which statistics engine the controller reads from, probed once per hour.

        ``MODERN`` (Network 11) keeps history behind ``/v2/api/stats``; a
        controller without that endpoint is legacy. A permission refusal is
        remembered as such. Other failures are not cached and read as legacy.
        """
        cache_key = "stats_engine_source"
        cached = self._connection.get_cached(cache_key, timeout=3600)
        if cached is not None:
            return cached
        try:
            response = await self._connection.request(stats_series.StatsApiRequest(method="get", path="/source"))
            source = stats_series.source_from_response(response) or _STATS_SOURCE_LEGACY
        except Forbidden:
            source = _STATS_SOURCE_FORBIDDEN
        except Exception as e:
            if response_status(e) != 404:
                logger.debug("Statistics engine probe failed: %s", type(e).__name__)
                return None
            source = _STATS_SOURCE_LEGACY
        self._connection._update_cache(cache_key, source, timeout=3600)
        return source

    async def _legacy_report(self, api_request: ApiRequest, source: Optional[str]) -> List[Dict[str, Any]]:
        """Read a legacy report. Empty is an error when the new engine may hold the data instead."""
        response = await self._connection.request(api_request)
        rows = response if isinstance(response, list) else []
        if not rows and source == _STATS_SOURCE_FORBIDDEN:
            raise StatsPermissionError()
        if not rows and source is None:
            raise RequestError(_STATS_SOURCE_UNKNOWN)
        return rows

    async def _series(
        self,
        schema: str,
        fields: Dict[str, str],
        start_ms: int,
        end_ms: int,
        granularity: str,
        *,
        device_mac: Optional[str] = None,
        client_mac: Optional[str] = None,
        nested: Optional[tuple[str, str]] = None,
    ) -> Dict[int, Dict[str, Any]]:
        """Read one schema's series for this site and fold it into report rows."""
        projection = f"values({','.join(fields)})" + (f",nested({nested[0]})" if nested else "")
        rows = await self._series_site_rows(
            schema, start_ms, end_ms, device_mac=device_mac, client_mac=client_mac, projection=projection
        )
        return stats_series.legacy_rows(
            rows, fields, start_ms=start_ms, end_ms=end_ms, granularity=granularity, nested=nested
        )

    async def _series_site_rows(
        self,
        schema: str,
        start_ms: int,
        end_ms: int,
        *,
        device_mac: Optional[str] = None,
        client_mac: Optional[str] = None,
        projection: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """This site's series rows for the window. The series are controller-wide, even when filtered."""
        if not stats_series.window_fits(start_ms, end_ms):
            raise StatsWindowError()
        path = stats_series.series_path(
            schema,
            stats_series.period_for_window(start_ms, end_ms),
            end_ms,
            device_mac=device_mac,
            client_mac=client_mac,
            projection=projection,
        )
        try:
            response = await self._connection.request(stats_series.StatsApiRequest(method="get", path=path))
        except Forbidden:
            raise StatsPermissionError() from None
        rows = stats_series.series_rows(response)
        if not rows:
            return []
        return stats_series.series_rows(rows, site_id=await self._series_site_id())

    async def _series_site_id(self) -> str:
        """The statistics engine's UUID for this site, which the site's ``self`` record carries."""
        cache_key = f"stats_engine_site_{self._connection.site}"
        cached = self._connection.get_cached(cache_key, timeout=3600)
        if cached is not None:
            return cached
        response = await self._connection.request(ApiRequest(method="get", path="/self"))
        record = response[0] if isinstance(response, list) and response else response
        site_id = record.get("site_id") if isinstance(record, dict) else None
        if not isinstance(site_id, str):
            raise RequestError("Could not tell which statistics belong to this site: the controller sent no site id.")
        self._connection._update_cache(cache_key, site_id, timeout=3600)
        return site_id

    async def _gateway_mac(self) -> Optional[str]:
        for device in await DeviceManager(self._connection).get_devices():
            raw = device.raw if hasattr(device, "raw") else device
            if str(raw.get("type", ""))[:3] in _GATEWAY_TYPE_PREFIXES and isinstance(raw.get("mac"), str):
                return normalize_mac(raw["mac"])
        return None

    async def _series_network_rows(self, start_ms: int, end_ms: int, granularity: str) -> List[Dict[str, Any]]:
        wan = await self._series("wanBySite", _SERIES_SITE_WAN, start_ms, end_ms, granularity)
        clients = await self._series("clientCountBySite", _SERIES_SITE_CLIENTS, start_ms, end_ms, granularity)
        rows = stats_series.merge_rows(wan, clients)
        for row in rows:
            # The site report's rx/tx is its WAN traffic.
            row.setdefault("rx_bytes", row.get("wan-rx_bytes", 0))
            row.setdefault("tx_bytes", row.get("wan-tx_bytes", 0))
            row["bytes"] = row["rx_bytes"] + row["tx_bytes"]
        return rows

    async def _series_gateway_rows(
        self, gateway_mac: Optional[str], start_ms: int, end_ms: int, granularity: str
    ) -> List[Dict[str, Any]]:
        if gateway_mac is None:
            wan = await self._series("wanBySite", _SERIES_GATEWAY_WAN, start_ms, end_ms, granularity)
            return stats_series.merge_rows(wan)
        wan = await self._series(
            "wanBySiteByDevice", _SERIES_GATEWAY_WAN, start_ms, end_ms, granularity, device_mac=gateway_mac
        )
        system = await self._series(
            "systemBySiteByDevice", _SERIES_GATEWAY_SYSTEM, start_ms, end_ms, granularity, device_mac=gateway_mac
        )
        return stats_series.merge_rows(wan, system, extra={"gw": gateway_mac})

    async def _series_device_rows(
        self, device_mac: str, device_type: str, start_ms: int, end_ms: int, granularity: str
    ) -> List[Dict[str, Any]]:
        if device_type == "gw":
            return await self._series_gateway_rows(device_mac, start_ms, end_ms, granularity)
        if device_type == "ap":
            wireless = await self._series(
                "wirelessBySiteByDevice",
                _SERIES_AP,
                start_ms,
                end_ms,
                granularity,
                device_mac=device_mac,
                nested=("byRadioBand", "radioBand"),
            )
            return stats_series.merge_rows(wireless, extra={"ap": device_mac})
        traffic = await self._series(
            "portTrafficBySiteByDevice", _SERIES_DEVICE_TRAFFIC, start_ms, end_ms, granularity, device_mac=device_mac
        )
        clients = await self._series(
            "clientCountBySiteByDevice", _SERIES_DEVICE_CLIENTS, start_ms, end_ms, granularity, device_mac=device_mac
        )
        return stats_series.merge_rows(traffic, clients, extra={"device": device_mac})

    async def get_network_stats(self, duration_hours: int = 1, granularity: str = "hourly") -> List[Dict[str, Any]]:
        """Get network statistics (e.g., hourly site stats)."""
        granularity = _resolve_granularity(granularity)
        cache_key = f"{CACHE_PREFIX_STATS_NETWORK}_{duration_hours}_{granularity}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key, timeout=300)  # 5 minute cache
        if cached_data is not None:
            return cached_data

        try:
            start_time, end_time = _window_ms(duration_hours)

            source = await self._stats_source()
            if source == stats_series.STATS_SOURCE_MODERN:
                result = await self._series_network_rows(start_time, end_time, granularity)
                self._connection._update_cache(cache_key, result, timeout=300)
                return result

            endpoint = f"/stat/report/{granularity}.site"
            # Use non-rate attributes commonly available on report endpoints
            payload = {
                "attrs": [
                    "bytes",  # total bytes (if provided by controller)
                    "rx_bytes",  # some controllers provide rx/tx at site level
                    "tx_bytes",
                    "num_user",
                    "num_sta",
                    "num_active_user",
                    "wan-rx_bytes",
                    "wan-tx_bytes",
                    "wlan-num_sta",
                    "lan-num_sta",
                ],
                "start": start_time,
                "end": end_time,
            }
            result = await self._legacy_report(ApiRequest(method="post", path=endpoint, data=payload), source)
            self._connection._update_cache(cache_key, result, timeout=300)
            return result
        except Exception as e:
            logger.error("Error getting network stats: %s", e)
            raise

    async def get_client_stats(
        self,
        client_mac: str,
        duration_hours: int = 1,
        granularity: str = "hourly",
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Get statistics for a specific client.

        ``start_ms``/``end_ms`` select an absolute window (epoch ms) and take
        precedence over ``duration_hours``, which otherwise counts back from now.
        """
        client_mac = normalize_mac(client_mac) or client_mac
        granularity = _resolve_granularity(granularity)
        start_time, end_time = _window_ms(duration_hours, start_ms, end_ms)
        window_key = _window_cache_key(start_time, end_time, start_ms, end_ms)
        cache_key = f"{CACHE_PREFIX_STATS_CLIENT}_{client_mac}_{window_key}_{granularity}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key, timeout=300)  # 5 minute cache
        if cached_data is not None:
            return cached_data

        try:
            source = await self._stats_source()
            if source == stats_series.STATS_SOURCE_MODERN:
                activity = await self._series(
                    "activityBySiteByClient",
                    _SERIES_CLIENT,
                    start_time,
                    end_time,
                    granularity,
                    client_mac=client_mac,
                )
                result = stats_series.merge_rows(activity, extra={"user": client_mac})
                self._connection._update_cache(cache_key, result, timeout=300)
                return result
            endpoint = f"/stat/report/{granularity}.user"
            payload = {
                "attrs": [
                    "rx_bytes",
                    "tx_bytes",
                    "bytes",
                    "signal",
                    "satisfaction",
                    "tx_retries",
                    "tx_rate",
                    "rx_rate",
                    "wifi_tx_attempts",
                ],
                "mac": client_mac,
                "start": start_time,
                "end": end_time,
            }
            result = await self._legacy_report(ApiRequest(method="post", path=endpoint, data=payload), source)
            self._connection._update_cache(cache_key, result, timeout=300)
            return result
        except Exception as e:
            logger.error("Error getting stats for client %s: %s", client_mac, e)
            raise

    async def get_client_stats_for_identifier(
        self,
        client_id: str,
        duration_hours: int = 1,
        granularity: str = "hourly",
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Resolve a public MAC-or-id client identifier before fetching stats."""
        client = await self._client_manager.get_client_details(client_id, existence_only=True)
        raw = client.raw if hasattr(client, "raw") else client
        client_mac = raw.get("mac", client_id)
        return await self.get_client_stats(
            client_mac,
            duration_hours=duration_hours,
            granularity=granularity,
            start_ms=start_ms,
            end_ms=end_ms,
        )

    async def get_device_stats(
        self,
        device_mac: str,
        duration_hours: int = 1,
        granularity: str = "hourly",
        device_type: str = "dev",
    ) -> List[Dict[str, Any]]:
        """Get statistics for a specific device.

        Args:
            device_mac: MAC address of the device.
            duration_hours: Number of hours to look back.
            granularity: Report granularity (5minutes, hourly, daily, monthly).
            device_type: Device type for endpoint routing (ap, gw, or dev).
        """
        device_mac = normalize_mac(device_mac) or device_mac
        granularity = _resolve_granularity(granularity)
        cache_key = (
            f"{CACHE_PREFIX_STATS_DEVICE}_{device_mac}_{duration_hours}_{granularity}"
            f"_{device_type}_{self._connection.site}"
        )
        cached_data = self._connection.get_cached(cache_key, timeout=300)  # 5 minute cache
        if cached_data is not None:
            return cached_data

        try:
            start_time, end_time = _window_ms(duration_hours)

            source = await self._stats_source()
            if source == stats_series.STATS_SOURCE_MODERN:
                result = await self._series_device_rows(device_mac, device_type, start_time, end_time, granularity)
                self._connection._update_cache(cache_key, result, timeout=300)
                return result

            # Route endpoint and attrs based on device_type
            if device_type == "ap":
                endpoint = f"/stat/report/{granularity}.ap"
                attrs = [
                    "num_sta",
                    "ng-num_sta",
                    "na-num_sta",
                    "satisfaction",
                    "tx_retries",
                    "wifi_tx_attempts",
                    "wifi_tx_dropped",
                    "ng-tx_bytes",
                    "na-tx_bytes",
                    "ng-rx_bytes",
                    "na-rx_bytes",
                ]
            elif device_type == "gw":
                endpoint = f"/stat/report/{granularity}.gw"
                attrs = [
                    "wan-rx_bytes",
                    "wan-tx_bytes",
                    "lan-rx_bytes",
                    "lan-tx_bytes",
                    "cpu",
                    "mem",
                    "loadavg_5",
                ]
            else:
                endpoint = f"/stat/report/{granularity}.dev"
                attrs = [
                    "rx_bytes",
                    "tx_bytes",
                    "bytes",
                    "num_sta",
                ]

            payload = {
                "attrs": attrs,
                "mac": device_mac,
                "start": start_time,
                "end": end_time,
            }
            result = await self._legacy_report(ApiRequest(method="post", path=endpoint, data=payload), source)
            self._connection._update_cache(cache_key, result, timeout=300)
            return result
        except Exception as e:
            logger.error("Error getting stats for device %s: %s", device_mac, e)
            raise

    async def get_device_stats_for_identifier(
        self,
        device_id: str,
        duration_hours: int = 1,
        granularity: str = "hourly",
    ) -> List[Dict[str, Any]]:
        """Resolve a public MAC-or-id device identifier and select its report family."""
        device = await DeviceManager(self._connection).get_device_details(device_id)
        raw = device.raw if hasattr(device, "raw") else device
        device_mac = raw.get("mac", device_id)
        device_type = raw.get("type", "unknown")
        report_type = {"uap": "ap", "ugw": "gw", "udm": "gw"}.get(device_type, "dev")
        return await self.get_device_stats(
            device_mac,
            duration_hours=duration_hours,
            granularity=granularity,
            device_type=report_type,
        )

    async def get_top_clients(
        self,
        duration_hours: int = 24,
        limit: int = 10,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
        granularity: Optional[str] = None,
        sort_by: str = "total",
    ) -> List[Dict[str, Any]]:
        """Rank clients by traffic inside a time window.

        Sums the controller's per-client report (``/stat/report/<g>.user``), or
        on Network 11 each client's activity series, over the window, so the
        ranking answers "who moved data between X and Y".
        In that report ``rx_bytes`` is what the client sent (upload) and
        ``tx_bytes`` what it received (download), seen from the network side.

        The legacy report only covers clients the controller meters per client,
        which on current gateways means wireless clients; wired clients are
        absent from it. The Network 11 series include wired clients. When the
        report yields nothing for a duration-based window (older controllers),
        the ranking falls back to cumulative counters of
        currently connected clients, marked ``source="live_counters"`` because
        they are not scoped to the window. A caller-pinned ``start_ms`` or
        ``end_ms`` never falls back: lifetime counters would describe a
        different period, so an empty window returns an empty ranking.
        """
        if sort_by not in ("total", "upload", "download"):
            raise ValueError("sort_by must be one of: total, upload, download")
        now_ms = _now_ms()
        start_time, end_time = _window_ms(duration_hours, start_ms, end_ms, now_ms)
        granularity = _resolve_granularity(granularity) if granularity else _auto_granularity(start_time, now_ms)
        sort_key = {"total": "total_bytes", "upload": "upload_bytes", "download": "download_bytes"}[sort_by]
        explicit_window = start_ms is not None or end_ms is not None

        cache_key = (
            f"stats_top_clients_{_window_cache_key(start_time, end_time, start_ms, end_ms)}"
            f"_{granularity}_{self._connection.site}"
        )
        per_client = self._connection.get_cached(cache_key, timeout=120)
        source = None
        if per_client is None:
            try:
                source = await self._stats_source()
                if source == stats_series.STATS_SOURCE_MODERN:
                    per_client = await self._top_clients_from_series(granularity, start_time, end_time)
                else:
                    per_client = await self._top_clients_from_report(granularity, start_time, end_time)
            except (StatsPermissionError, StatsWindowError):
                raise
            except Exception as e:
                logger.error("Top clients report read failed: %s", type(e).__name__)
                raise RequestError(f"Top clients report read failed ({type(e).__name__}).") from None
            if per_client:
                self._connection._update_cache(cache_key, per_client, timeout=120)

        if not per_client:
            if source == _STATS_SOURCE_FORBIDDEN:
                raise StatsPermissionError()
            # Lifetime counters stand in only where no windowed history exists.
            if explicit_window or source == stats_series.STATS_SOURCE_MODERN:
                return []
            try:
                per_client = await self._top_clients_from_live_counters()
            except Exception as e:
                logger.error("Top clients live counter read failed: %s", type(e).__name__)
                raise RequestError(f"Top clients live counter read failed ({type(e).__name__}).") from None

        ranked = sorted(per_client, key=lambda x: int(x.get(sort_key) or 0), reverse=True)
        return ranked[:limit]

    async def _top_clients_from_series(self, granularity: str, start_time: int, end_time: int) -> List[Dict[str, Any]]:
        """Sum each client's activity series over a window, counted from the client's side."""
        rows = await self._series_site_rows(
            "activityBySiteByClient", start_time, end_time, projection="values(rxBytes,txBytes)"
        )
        per_client = []
        for row in rows:
            mac = normalize_mac(row["clientId"]) if isinstance(row.get("clientId"), str) else None
            if not mac:
                continue
            points = [
                point
                for point in row.get("series") or []
                if isinstance(point, dict)
                and isinstance(point.get("timestamp"), int)
                and start_time <= point["timestamp"] < end_time
            ]
            upload = sum(_safe_int(point.get("txBytes")) for point in points)
            download = sum(_safe_int(point.get("rxBytes")) for point in points)
            if not upload and not download:
                continue
            per_client.append(
                {
                    "mac": mac,
                    "upload_bytes": upload,
                    "download_bytes": download,
                    "rx_bytes": upload,
                    "tx_bytes": download,
                    "total_bytes": upload + download,
                    "source": "report",
                    "granularity": granularity,
                    "start": start_time,
                    "end": end_time,
                }
            )
        return per_client

    async def _top_clients_from_report(self, granularity: str, start_time: int, end_time: int) -> List[Dict[str, Any]]:
        """Sum the per-client report over a window, one entry per client MAC."""
        api_request = ApiRequest(
            method="post",
            path=f"/stat/report/{granularity}.user",
            data={"attrs": ["rx_bytes", "tx_bytes", "time"], "start": start_time, "end": end_time},
        )
        response = await self._connection.request(api_request)
        rows = response if isinstance(response, list) else []
        totals: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_mac = row.get("user") or row.get("mac")
            mac = normalize_mac(raw_mac) if isinstance(raw_mac, str) else None
            if not mac:
                continue
            entry = totals.setdefault(mac, {"mac": mac, "upload_bytes": 0, "download_bytes": 0})
            entry["upload_bytes"] += _safe_int(row.get("rx_bytes"))
            entry["download_bytes"] += _safe_int(row.get("tx_bytes"))
        per_client = []
        for entry in totals.values():
            entry["rx_bytes"] = entry["upload_bytes"]
            entry["tx_bytes"] = entry["download_bytes"]
            entry["total_bytes"] = entry["upload_bytes"] + entry["download_bytes"]
            entry.update({"source": "report", "granularity": granularity, "start": start_time, "end": end_time})
            per_client.append(entry)
        return per_client

    async def _top_clients_from_live_counters(self) -> List[Dict[str, Any]]:
        """Cumulative counters of connected clients; not scoped to any window."""
        online_clients = await self._client_manager.get_clients()
        if not online_clients:
            return []

        aggregated: List[Dict[str, Any]] = []
        for client in (c.raw if hasattr(c, "raw") else c for c in online_clients):
            mac = client.get("mac")
            if not mac:
                continue
            rx = _safe_int(client.get("rx_bytes")) + _safe_int(
                client.get("wired_rx_bytes") or client.get("wired-rx_bytes")
            )
            tx = _safe_int(client.get("tx_bytes")) + _safe_int(
                client.get("wired_tx_bytes") or client.get("wired-tx_bytes")
            )
            aggregated.append(
                {
                    "mac": mac,
                    "name": client.get("name") or client.get("hostname", mac),
                    "rx_bytes": rx,
                    "tx_bytes": tx,
                    "upload_bytes": rx,
                    "download_bytes": tx,
                    "total_bytes": _safe_int(client.get("bytes")) or (rx + tx),
                    "source": "live_counters",
                }
            )
        return aggregated

    async def get_dpi_stats(
        self,
    ) -> Dict[str, List[Any]]:  # Return List[DPIRestrictionApp/Group]
        """Get Deep Packet Inspection (DPI) statistics."""
        cache_key = f"{CACHE_PREFIX_STATS_DPI}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key, timeout=900)  # 15 minute cache
        if cached_data is not None:
            return cached_data

        if not await self._connection.ensure_connected() or not self._connection.controller:
            raise ConnectionError("Not connected to controller")

        try:
            await self._connection.refresh_handler("dpi_apps")
            await self._connection.refresh_handler("dpi_groups")

            dpi_apps: List[DPIRestrictionApp] = list(self._connection.controller.dpi_apps.values())
            dpi_groups: List[DPIRestrictionGroup] = list(self._connection.controller.dpi_groups.values())
            result = {"applications": dpi_apps, "categories": dpi_groups}
            self._connection._update_cache(cache_key, result, timeout=900)
            return result
        except Exception as e:
            logger.error("Error getting DPI stats: %s", type(e).__name__)
            # REST/GraphQL call this manager directly and may log tracebacks.
            # Keep the original controller text out of every caller surface.
            raise RequestError(f"DPI stats refresh failed ({type(e).__name__}).") from None

    async def get_alerts(self, include_archived: bool = False) -> List[Dict[str, Any]]:
        """Get alerts from the controller."""
        cache_key = f"{CACHE_PREFIX_STATS_ALERTS}_{include_archived}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key, timeout=60)  # 1 minute cache
        if cached_data is not None:
            return cached_data

        if not await self._connection.ensure_connected() or not self._connection.controller:
            raise ConnectionError("Not connected to controller")
        try:
            alerts = await self._get_alerts_v2()
        except Exception as v2_error:
            logger.debug("V2 alert lookup failed, falling back to legacy alarms: %s", v2_error)
            try:
                alerts = await self._get_alerts_legacy(include_archived)
            except Exception as legacy_error:
                # Report both. Current controllers have removed /stat/alarm, so the
                # legacy error is usually a 404 that says nothing about the real
                # problem — which is whatever made the v2 lookup fail.
                raise RuntimeError(
                    f"/stat/alarm failed ({legacy_error}) after the v2 system-log lookup failed "
                    f"({v2_error}). On current UniFi Network versions the legacy endpoint no longer "
                    "exists, so the v2 failure is the one to act on."
                ) from legacy_error

        if not include_archived:
            alerts = [a for a in alerts if not a.get("archived", False)]
        self._connection._update_cache(cache_key, alerts, timeout=60)
        return alerts

    async def _get_alerts_v2(self) -> List[Dict[str, Any]]:
        """Get alerts from the v2 system-log critical endpoint."""
        now_ms = int(datetime.now().timestamp() * 1000)
        from_ms = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)
        api_request = ApiRequestV2(
            method="post",
            path="/system-log/critical",
            data={
                "timestampFrom": from_ms,
                "timestampTo": now_ms,
                "severities": ["HIGH", "VERY_HIGH"],
                "categories": [
                    "CLIENT_DEVICES",
                    "INTERNET_AND_WAN",
                    "POWER",
                    "SECURITY",
                    "UNIFI_DEVICES",
                    "SOFTWARE_UPDATES",
                    "UNIFI_ETHERNET_PORTS",
                    "VPN",
                ],
                "type": "GENERAL",
                "pageNumber": 0,
                "pageSize": 100,
                "searchText": "",
            },
        )
        response = await self._connection.request(api_request)
        if isinstance(response, list) and response and isinstance(response[0], dict) and "data" in response[0]:
            return response[0]["data"]
        if isinstance(response, dict):
            data = response.get("data", response.get("logs", []))
            return data if isinstance(data, list) else []
        if isinstance(response, list):
            return response
        return []

    async def _get_alerts_legacy(self, include_archived: bool) -> List[Dict[str, Any]]:
        """Get alerts from the legacy alarm endpoint."""
        path = "/stat/alarm?archived=true" if include_archived else "/stat/alarm"
        api_request = ApiRequest(method="get", path=path)
        response = await self._connection.request(api_request)
        if isinstance(response, list):
            return response
        if isinstance(response, dict):
            data = response.get("data", [])
            return data if isinstance(data, list) else []
        return []

    async def get_gateway_stats(self, duration_hours: int = 24, granularity: str = "hourly") -> List[Dict[str, Any]]:
        """Get gateway statistics."""
        granularity = _resolve_granularity(granularity)
        cache_key = f"{CACHE_PREFIX_STATS_GATEWAY}_{duration_hours}_{granularity}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key, timeout=300)  # 5 minute cache
        if cached_data is not None:
            return cached_data

        try:
            start_time, end_time = _window_ms(duration_hours)

            source = await self._stats_source()
            if source == stats_series.STATS_SOURCE_MODERN:
                result = await self._series_gateway_rows(await self._gateway_mac(), start_time, end_time, granularity)
                self._connection._update_cache(cache_key, result, timeout=300)
                return result

            endpoint = f"/stat/report/{granularity}.gw"
            payload = {
                "attrs": [
                    "wan-rx_bytes",
                    "wan-tx_bytes",
                    "lan-rx_bytes",
                    "lan-tx_bytes",
                    "cpu",
                    "mem",
                    "loadavg_5",
                    "wan-rx_packets",
                    "wan-tx_packets",
                ],
                "start": start_time,
                "end": end_time,
            }
            result = await self._legacy_report(ApiRequest(method="post", path=endpoint, data=payload), source)
            self._connection._update_cache(cache_key, result, timeout=300)
            return result
        except Exception as e:
            logger.error("Error getting gateway stats: %s", e)
            raise

    async def get_speedtest_results(self, duration_hours: int = 24) -> List[Dict[str, Any]]:
        """Get speed test results from the controller archive."""
        cache_key = f"{CACHE_PREFIX_STATS_SPEEDTEST}_{duration_hours}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key, timeout=300)  # 5 minute cache
        if cached_data is not None:
            return cached_data

        try:
            start_time = int((datetime.now() - timedelta(hours=duration_hours)).timestamp() * 1000)
            end_time = int(datetime.now().timestamp() * 1000)

            endpoint = "/stat/report/archive.speedtest"
            payload = {
                "attrs": [
                    "xput_download",
                    "xput_upload",
                    "latency",
                    "time",
                ],
                "start": start_time,
                "end": end_time,
            }
            api_request = ApiRequest(method="post", path=endpoint, data=payload)
            response = await self._connection.request(api_request)
            result = response if isinstance(response, list) else []
            self._connection._update_cache(cache_key, result, timeout=300)
            return result
        except Exception as e:
            logger.error("Error getting speedtest results: %s", e)
            raise

    async def _get_v2_traffic(self, start_ms: int, end_ms: int) -> Dict[str, Any]:
        """Read the v2 DPI traffic aggregate (Network 9.x+) for a window."""
        api_request = ApiRequestV2(
            method="get",
            path=f"/traffic?start={start_ms}&end={end_ms}&includeTrafficUsage=true&includeUnidentified=true",
        )
        return _v2_traffic_payload(await self._connection.request(api_request))

    async def get_site_dpi_traffic(
        self,
        by: str = "by_app",
        duration_hours: int = 24,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Get site-level DPI traffic statistics for a window.

        Uses the v2 traffic aggregate when the controller has it, else the
        legacy ``/stat/sitedpi`` (which has no window and is empty on 10.x).

        Args:
            by: Grouping type, e.g. 'by_app' or 'by_cat'.
        """
        start_time, end_time = _window_ms(duration_hours, start_ms, end_ms)
        cache_key = (
            f"{CACHE_PREFIX_STATS_SITE_DPI}_{by}_{_window_cache_key(start_time, end_time, start_ms, end_ms)}"
            f"_{self._connection.site}"
        )
        cached_data = self._connection.get_cached(cache_key, timeout=300)
        if cached_data is not None:
            return cached_data

        try:
            v2_failed = False
            try:
                payload = await self._get_v2_traffic(start_time, end_time)
            except Exception as v2_error:
                logger.debug("v2 traffic aggregate unavailable (%s); using /stat/sitedpi", type(v2_error).__name__)
                payload = {}
                v2_failed = True
            if "total_usage_by_app" in payload:
                result = _group_dpi_usage(payload.get("total_usage_by_app") or [], by)
            else:
                api_request = ApiRequest(method="post", path="/stat/sitedpi", data={"type": by})
                response = await self._connection.request(api_request)
                result = response if isinstance(response, list) else []
            # On 10.x the legacy endpoint is always empty, so an empty answer after a
            # v2 failure says nothing about the window; leave it uncached so a
            # transient v2 error is retried instead of held as "no traffic".
            if result or not v2_failed:
                self._connection._update_cache(cache_key, result, timeout=300)
            return result
        except Exception as e:
            logger.error("Site DPI traffic read failed: %s", type(e).__name__)
            raise RequestError(f"Site DPI traffic read failed ({type(e).__name__}).") from None

    async def get_client_dpi_traffic(
        self,
        client_mac: str,
        by: str = "by_app",
        duration_hours: int = 24,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Get DPI traffic statistics for one client over a window.

        Uses the v2 traffic aggregate when the controller has it, else the
        legacy ``/stat/stadpi`` (which has no window and is empty on 10.x).

        Args:
            client_mac: MAC address of the client.
            by: Grouping type, e.g. 'by_app' or 'by_cat'.
        """
        client_mac = normalize_mac(client_mac) or client_mac
        start_time, end_time = _window_ms(duration_hours, start_ms, end_ms)
        window_key = _window_cache_key(start_time, end_time, start_ms, end_ms)
        cache_key = f"{CACHE_PREFIX_STATS_CLIENT_DPI}_{client_mac}_{by}_{window_key}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key, timeout=300)
        if cached_data is not None:
            return cached_data

        try:
            v2_failed = False
            try:
                payload = await self._get_v2_traffic(start_time, end_time)
            except Exception as v2_error:
                logger.debug("v2 traffic aggregate unavailable (%s); using /stat/stadpi", type(v2_error).__name__)
                payload = {}
                v2_failed = True
            if "client_usage_by_app" in payload:
                usage: List[Dict[str, Any]] = []
                for entry in payload.get("client_usage_by_app") or []:
                    client = entry.get("client") or {}
                    if mac_equal(client.get("mac"), client_mac):
                        usage.extend(entry.get("usage_by_app") or [])
                result = _group_dpi_usage(usage, by)
            else:
                api_request = ApiRequest(method="post", path="/stat/stadpi", data={"type": by, "macs": [client_mac]})
                response = await self._connection.request(api_request)
                result = response if isinstance(response, list) else []
            # As for site DPI: an empty legacy answer after a v2 failure is not cached.
            if result or not v2_failed:
                self._connection._update_cache(cache_key, result, timeout=300)
            return result
        except Exception as e:
            logger.error("Client DPI traffic read failed: %s", type(e).__name__)
            raise RequestError(f"Client DPI traffic read failed ({type(e).__name__}).") from None

    async def get_ips_events(self, duration_hours: int = 24, limit: int = 50) -> List[Dict[str, Any]]:
        """Get IPS/IDS events.

        Args:
            duration_hours: Number of hours to look back.
            limit: Maximum number of events to return.
        """
        cache_key = f"{CACHE_PREFIX_STATS_IPS}_{duration_hours}_{limit}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key, timeout=300)  # 5 minute cache
        if cached_data is not None:
            return cached_data

        try:
            start_time = int((datetime.now() - timedelta(hours=duration_hours)).timestamp() * 1000)
            end_time = int(datetime.now().timestamp() * 1000)

            api_request = ApiRequest(
                method="post",
                path="/stat/ips/event",
                data={
                    "start": start_time,
                    "end": end_time,
                    "_limit": limit,
                },
            )
            try:
                response = await self._connection.request(api_request)
            except Exception as legacy_error:
                logger.debug(
                    "Legacy IPS endpoint failed, falling back to v2 security logs: %s", type(legacy_error).__name__
                )
                response, complete = await self._get_security_events_v2(start_time, end_time, limit)
                if not complete:
                    return response
            else:
                # A controller that has moved IPS events to the v2 system log answers
                # this endpoint 200 with an empty list rather than failing, so the
                # fallback above never fires on the versions it exists for.
                if not isinstance(response, list) or not response:
                    logger.debug("Legacy IPS endpoint returned no events, trying v2 security logs")
                    # Empty legacy data is inconclusive on controllers using v2.
                    # A failed fallback must remain an unavailable read, not "no threats".
                    response, complete = await self._get_security_events_v2(start_time, end_time, limit)
                    if not complete:
                        return response
            result = response if isinstance(response, list) else []
            self._connection._update_cache(cache_key, result, timeout=300)
            return result
        except UniFiMalformedResponseError as e:
            logger.error("Error getting IPS events: malformed response")
            raise e from None
        except Exception as e:
            logger.error("Error getting IPS events: %s", type(e).__name__)
            raise safe_request_error("IPS events", e) from None

    async def _get_security_events_v2(
        self, start_time: int, end_time: int, limit: int
    ) -> tuple[List[Dict[str, Any]], bool]:
        """Fallback for controllers where legacy IPS events no longer exist.

        Returns the events and whether the read was complete. It is incomplete when the
        page bound stopped it before the log or the limit ran out; callers must not
        cache that as the answer for the window.
        """
        # Threat blocks are logged with show_on_dashboard=false, so the
        # dashboard-only /system-log/critical view never contains them; the
        # full log filtered to the SECURITY category does (verified on 10.6).
        # That category also carries ordinary firewall blocks, which can outnumber
        # threats by hundreds to one. The controller filters on `subcategories`
        # (the singular key is ignored), and rows are narrowed again here in case
        # a controller ignores the filter, reading further pages if firewall rows
        # still crowd threats out.
        events: List[Dict[str, Any]] = []
        seen_ids: set[Any] = set()
        for page_number in range(_IPS_V2_MAX_PAGES):
            api_request = ApiRequestV2(
                method="post",
                path="/system-log/all",
                data={
                    "timestampFrom": start_time,
                    "timestampTo": end_time,
                    "categories": ["SECURITY"],
                    "subcategories": [_IPS_SUBCATEGORY],
                    "pageNumber": page_number,
                    "pageSize": _IPS_V2_PAGE_SIZE,
                },
            )
            rows, page_size = _system_log_page(await self._connection.request(api_request))
            for row in rows:
                if not _is_ips_event(row):
                    continue
                # New events shift rows between page reads, so a row can repeat.
                row_id = row.get("id")
                if row_id is not None:
                    if row_id in seen_ids:
                        continue
                    seen_ids.add(row_id)
                events.append(row)
            if len(events) >= limit or page_size < _IPS_V2_PAGE_SIZE:
                return events[:limit], True
        logger.warning("IPS events read stopped after %d pages; the result may be incomplete", _IPS_V2_MAX_PAGES)
        return events[:limit], False

    async def get_client_sessions(
        self,
        client_mac: Optional[str] = None,
        duration_hours: int = 24,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get client session history.

        Args:
            client_mac: Optional MAC address to filter sessions for a specific client.
            duration_hours: Number of hours to look back.
            limit: Maximum number of sessions to return.
        """
        client_mac = normalize_mac(client_mac) or client_mac
        mac_part = client_mac or "all"
        cache_key = f"{CACHE_PREFIX_STATS_SESSIONS}_{mac_part}_{duration_hours}_{limit}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key, timeout=300)  # 5 minute cache
        if cached_data is not None:
            return cached_data

        try:
            start_time = int((datetime.now() - timedelta(hours=duration_hours)).timestamp() * 1000)
            end_time = int(datetime.now().timestamp() * 1000)

            endpoint = "/stat/session"
            payload: Dict[str, Any] = {
                "type": "all",
                "start": start_time,
                "end": end_time,
                "_limit": limit,
            }
            if client_mac:
                payload["mac"] = client_mac

            api_request = ApiRequest(method="post", path=endpoint, data=payload)
            response = await self._connection.request(api_request)
            result = response if isinstance(response, list) else []
            self._connection._update_cache(cache_key, result, timeout=300)
            return result
        except Exception as e:
            logger.error("Client sessions read failed: %s", type(e).__name__)
            raise RequestError(f"Client sessions read failed ({type(e).__name__}).") from None

    async def get_dashboard(self, history_seconds: int = 86400) -> List[Dict[str, Any]]:
        """Get the site dashboard aggregate (health, WiFi standards, ISP metrics).

        Hits the V2 ``/aggregated-dashboard`` endpoint that the UniFi UI uses
        to render its dashboard view. The response is a list of one or more
        dashboard payloads (typically one per controller-managed site rollup).
        Each payload contains nested blocks like ``wifi`` (per-standard
        connection counts and traffic), ``isp_metrics`` (per-WAN history),
        and other UI-visible aggregates.

        Args:
            history_seconds: How far back to roll up history. Defaults to
                86400 (24h), matching the UI default. The endpoint requires
                this query parameter.
        """
        cache_key = f"{CACHE_PREFIX_STATS_DASHBOARD}_{history_seconds}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key, timeout=300)  # 5 minute cache
        if cached_data is not None:
            return cached_data

        try:
            api_request = ApiRequestV2(
                method="get",
                path=f"/aggregated-dashboard?historySeconds={int(history_seconds)}",
            )
            response = await self._connection.request(api_request)
            result = response if isinstance(response, list) else []
            self._connection._update_cache(cache_key, result, timeout=300)
            return result
        except Exception as e:
            logger.error("Error getting dashboard: %s", e)
            raise

    async def get_anomalies(self, duration_hours: int = 24) -> List[Dict[str, Any]]:
        """Get detected anomalies.

        Args:
            duration_hours: Number of hours to look back.
        """
        cache_key = f"{CACHE_PREFIX_STATS_ANOMALIES}_{duration_hours}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key, timeout=300)  # 5 minute cache
        if cached_data is not None:
            return cached_data

        try:
            start_time = int((datetime.now() - timedelta(hours=duration_hours)).timestamp() * 1000)
            end_time = int(datetime.now().timestamp() * 1000)

            endpoint = "/stat/anomalies"
            payload = {
                "start": start_time,
                "end": end_time,
            }
            api_request = ApiRequest(method="post", path=endpoint, data=payload)
            response = await self._connection.request(api_request)
            result = response if isinstance(response, list) else []
            self._connection._update_cache(cache_key, result, timeout=300)
            return result
        except Exception as e:
            logger.error("Error getting anomalies: %s", e)
            raise

    async def get_client_wifi_details(self, client_mac: str) -> Optional[Dict[str, Any]]:
        """Get detailed WiFi information for a specific client.

        Args:
            client_mac: MAC address of the client.

        Returns:
            Dict with WiFi detail fields, or None if client not found.
        """
        client_mac = normalize_mac(client_mac) or client_mac
        cache_key = f"{CACHE_PREFIX_STATS_CLIENT_WIFI}_{client_mac}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key, timeout=300)  # 5 minute cache
        if cached_data is not None:
            return cached_data

        try:
            # /stat/sta is a collection endpoint: it returns all currently-
            # connected wireless clients and ignores any MAC filter in the body.
            # Fetch the full list, then filter for the requested MAC ourselves.
            api_request = ApiRequest(method="get", path="/stat/sta")
            response = await self._connection.request(api_request)

            clients = response if isinstance(response, list) else []
            raw = next(
                (c for c in clients if isinstance(c, dict) and mac_equal(c.get("mac"), client_mac)),
                None,
            )
            if raw is None:
                return None

            wifi_fields = [
                "signal",
                "noise",
                "satisfaction",
                "tx_rate",
                "rx_rate",
                "tx_retries",
                "wifi_tx_attempts",
                "roam_count",
                "os_name",
                "dev_vendor",
                "dev_cat",
                "dev_family",
                "channel",
                "radio",
                "essid",
                "bssid",
                "nss",
                "is_11r",
            ]
            result: Dict[str, Any] = {"mac": raw.get("mac", client_mac)}
            for field in wifi_fields:
                if field in raw:
                    result[field] = raw[field]

            self._connection._update_cache(cache_key, result, timeout=300)
            return result
        except Exception as e:
            logger.error("Client WiFi details read failed: %s", type(e).__name__)
            raise RequestError(f"Client WiFi details read failed ({type(e).__name__}).") from None
