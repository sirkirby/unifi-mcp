"""Shared field models for Network statistics resources.

Mirrors the Strawberry types in
``unifi_api.graphql.types.network.stat``:

- ``StatPoint`` — single timeseries point {ts: <ms>, ...metrics}
- ``DpiStats``  — wrapper shape {applications: [...], categories: [...]}

Both classes are read-only. StatPoint covers all time-series stats endpoints
(network_stats, gateway_stats, device_stats, client_stats). DpiStats wraps
the DPI restriction configuration endpoint.

Factory helpers:
- ``stat_point_from_controller`` — normalise raw point dict → StatPoint
- ``dpi_stats_from_controller``  — normalise raw DPI result → DpiStats

MUTABLE_FIELDS = frozenset() for both classes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_ts(point: dict) -> int:
    """Normalise a point's timestamp to milliseconds."""
    ts = point.get("ts") or point.get("time") or point.get("timestamp") or 0
    if ts and ts < 10_000_000_000:  # likely seconds → convert to ms
        ts = ts * 1000
    return int(ts)


# ---------------------------------------------------------------------------
# StatPoint
# ---------------------------------------------------------------------------


class StatPoint(BaseModel):
    """A single timeseries data point: {ts: <ms>, ...metrics}.

    The ``ts`` field is normalised to milliseconds. All other metric keys
    (rx_bytes, tx_bytes, num_user, etc.) are preserved as-is in the raw
    ``metrics`` dict; they are not typed here because the set of keys varies
    across stats endpoints and firmware versions.
    """

    ts: int = Field(
        default=0,
        description="Timestamp in milliseconds (UTC)",
        json_schema_extra={"mutable": False},
    )
    metrics: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Raw metric key/value pairs from the controller",
        json_schema_extra={"mutable": False},
    )


STATPOINT_MUTABLE_FIELDS: frozenset[str] = frozenset()
STATPOINT_READ_ONLY_FIELDS: frozenset[str] = frozenset(StatPoint.model_fields.keys())


def stat_point_from_controller(point: Any) -> StatPoint:
    """Build a StatPoint from a controller stats dict."""
    if not isinstance(point, dict):
        return StatPoint(ts=0, metrics={})
    ts = _normalize_ts(point)
    metrics = {k: v for k, v in point.items() if k not in ("time", "timestamp", "ts")}
    return StatPoint(ts=ts, metrics=metrics if metrics else None)


# ---------------------------------------------------------------------------
# DpiStats
# ---------------------------------------------------------------------------


class DpiStats(BaseModel):
    """DPI stats wrapper: applications + categories arrays.

    Each sub-row is a passthrough dict (unstructured — the controller's DPI
    catalogs vary by firmware). The applications and categories lists carry
    raw dicts from the controller.
    """

    applications: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="DPI application entries (raw controller dicts)",
        json_schema_extra={"mutable": False},
    )
    categories: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="DPI category entries (raw controller dicts)",
        json_schema_extra={"mutable": False},
    )


DPISTATS_MUTABLE_FIELDS: frozenset[str] = frozenset()
DPISTATS_READ_ONLY_FIELDS: frozenset[str] = frozenset(DpiStats.model_fields.keys())

# Module-level alias (symmetry test fallback)
MUTABLE_FIELDS = STATPOINT_MUTABLE_FIELDS


def dpi_stats_from_controller(obj: Any) -> DpiStats:
    """Build a DpiStats from a controller API response dict."""
    if not isinstance(obj, dict):
        return DpiStats()

    def _itemize(items: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for it in items or []:
            if isinstance(it, dict):
                out.append(it)
            else:
                raw = getattr(it, "raw", None)
                if isinstance(raw, dict):
                    out.append(dict(raw))
        return out

    return DpiStats(
        applications=_itemize(obj.get("applications")),
        categories=_itemize(obj.get("categories")),
    )
