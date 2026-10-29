"""Network 11 statistics engine, read in the shape of the legacy reports.

Network 11 moved time-series statistics to a new engine. On those
controllers ``GET /v2/api/stats/source`` answers ``MODERN`` and the legacy
``stat/report/*`` endpoints no longer return data. History lives behind
``/v2/api/stats/recent/series`` instead: one series per schema
(``wanBySite``, ``wirelessBySiteByDevice``, ...), rows keyed by a site UUID
and, for device schemas, a device MAC (``clientId``, also a MAC, for client
schemas).

The stats tools and the API server read the legacy report rows, so this
module turns series points into those rows: renamed fields, one row per
requested granularity bucket, with ``time`` in epoch milliseconds.

The window is requested as a ``period`` ending at ``end`` rather than
``start``/``end``, because Network 11 releases before 11.0.89 ignore
``start``. The longest period is 30 days; further back the engine keeps
calendar-month buckets that a request must align to in the controller's
time zone, so a longer window is refused rather than paged. The period
fixes the bucket size: HOUR and DAY return 5-minute points, WEEK hourly
points and MONTH 8-hour points. Points outside the
window are dropped, and a granularity finer than the period's buckets
yields the period's buckets.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from aiounifi.models.api import ApiRequestV2

STATS_SOURCE_MODERN = "MODERN"

_HOUR_MS = 3_600_000
_PERIODS = (("HOUR", _HOUR_MS), ("DAY", 24 * _HOUR_MS), ("WEEK", 7 * 24 * _HOUR_MS), ("MONTH", 30 * 24 * _HOUR_MS))
_BUCKET_MS = {"5minutes": 300_000, "hourly": _HOUR_MS, "daily": 24 * _HOUR_MS}


class StatsApiRequest(ApiRequestV2):
    """A request under ``/v2/api/stats``, which is controller-wide, not site-scoped."""

    def full_path(self, site: str, is_unifi_os: bool) -> str:
        if is_unifi_os:
            return f"/proxy/network/v2/api/stats{self.path}"
        return f"/v2/api/stats{self.path}"


def source_from_response(response: Any) -> Optional[str]:
    """Read the engine name from a ``/stats/source`` response."""
    value = response[0] if isinstance(response, list) and response else response
    return value.upper() if isinstance(value, str) else None


def period_for_window(start_ms: int, end_ms: int) -> str:
    """The shortest series period that covers ``start_ms``..``end_ms``."""
    span = end_ms - start_ms
    for name, length in _PERIODS:
        if span <= length:
            return name
    return _PERIODS[-1][0]


def window_fits(start_ms: int, end_ms: int) -> bool:
    """Whether one series request covers the window: the longest period is 30 days."""
    return end_ms - start_ms <= _PERIODS[-1][1]


def series_path(
    schema: str,
    period: str,
    end_ms: int,
    *,
    device_mac: Optional[str] = None,
    client_mac: Optional[str] = None,
    projection: Optional[str] = None,
) -> str:
    """Build a ``/recent/series`` path. MACs must already be normalized."""
    path = f"/recent/series?schema={schema}&period={period}&end={int(end_ms)}"
    if device_mac:
        path += f"&filter=deviceMac.eq('{device_mac}')"
    elif client_mac:
        path += f"&filter=clientId.eq('{client_mac}')"
    if projection:
        path += f"&projection={projection}"
    return path


def series_rows(response: Any, *, site_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """The keyed rows of a series response, limited to ``site_id`` when given."""
    rows = [row for row in response if isinstance(row, dict)] if isinstance(response, list) else []
    if site_id is not None:
        rows = [row for row in rows if row.get("siteId") == site_id]
    return rows


def _reducer(field: str) -> Callable[[List[float]], float]:
    """How points of one metric combine into a coarser bucket."""
    if field.endswith(("Bytes", "Packets")):
        return sum
    if field.startswith("max") or field.startswith("distinct") or field.endswith("S"):
        return max
    return lambda values: sum(values) / len(values)


def _bucket_start(timestamp: int, granularity: str) -> int:
    if granularity == "monthly":
        moment = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
        return int(datetime(moment.year, moment.month, 1, tzinfo=timezone.utc).timestamp() * 1000)
    size = _BUCKET_MS[granularity]
    return timestamp - timestamp % size


def _point_values(point: Mapping[str, Any], fields: Mapping[str, str], nested: Optional[Tuple[str, str]]):
    """Yield ``(legacy name, series name, value)`` for each metric of one series point."""
    for source, target in fields.items():
        value = point.get(source)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            yield target, source, value
    if nested:
        group, key = nested
        for entry in point.get(group) or []:
            if not isinstance(entry, dict) or not isinstance(entry.get(key), str):
                continue
            for source, target in fields.items():
                value = entry.get(source)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    yield f"{entry[key]}-{target}", source, value


def legacy_rows(
    rows: Iterable[Mapping[str, Any]],
    fields: Mapping[str, str],
    *,
    start_ms: int,
    end_ms: int,
    granularity: str,
    nested: Optional[Tuple[str, str]] = None,
) -> Dict[int, Dict[str, Any]]:
    """Fold series points into legacy report rows, keyed by bucket start.

    ``fields`` maps series metric names to legacy report names. ``nested``
    names a nested group and its key (``("byRadioBand", "radioBand")``),
    whose metrics become ``<key value>-<legacy name>``, as the legacy AP
    report spells per-band counters (``ng-num_sta``).
    """
    collected: Dict[int, Dict[str, Tuple[str, List[float]]]] = {}
    for row in rows:
        for point in row.get("series") or []:
            timestamp = point.get("timestamp") if isinstance(point, dict) else None
            if not isinstance(timestamp, int) or not start_ms <= timestamp < end_ms:
                continue
            bucket = collected.setdefault(_bucket_start(timestamp, granularity), {})
            for target, source, value in _point_values(point, fields, nested):
                bucket.setdefault(target, (source, []))[1].append(value)
    folded: Dict[int, Dict[str, Any]] = {}
    for bucket_start, metrics in collected.items():
        folded[bucket_start] = {target: _reducer(source)(values) for target, (source, values) in metrics.items()}
    return folded


def merge_rows(
    *parts: Mapping[int, Mapping[str, Any]], extra: Optional[Mapping[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Merge folded rows from several schemas into time-ordered report rows."""
    merged: Dict[int, Dict[str, Any]] = {}
    for part in parts:
        for bucket_start, values in part.items():
            merged.setdefault(bucket_start, {"time": bucket_start, **(extra or {})}).update(values)
    for row in merged.values():
        if "bytes" not in row and ("rx_bytes" in row or "tx_bytes" in row):
            row["bytes"] = row.get("rx_bytes", 0) + row.get("tx_bytes", 0)
    return [merged[key] for key in sorted(merged)]
