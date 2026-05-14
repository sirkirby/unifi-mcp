"""Strawberry types for network/stats.

Phase 6 PR2 Task 23 migration target. The stats cluster spans two read shapes:

- ``StatPoint`` — TIMESERIES kind. Single per-point payload
                  ``{ts: <ms>, ...metric_keys}``. Window/step metadata lives
                  in ``render_hint``; per spec §5 the action endpoint emits
                  ``data: list[point]``. Covers:
                    * ``unifi_get_dashboard``
                    * ``unifi_get_network_stats``
                    * ``unifi_get_gateway_stats``
                    * ``unifi_get_client_dpi_traffic``
                    * ``unifi_get_site_dpi_traffic``
                    * ``unifi_get_device_stats``
                    * ``unifi_get_client_stats``

- ``DpiStats`` — DETAIL kind. Wrapper shape
                 ``{applications: [...], categories: [...]}`` used by
                 ``unifi_get_dpi_stats``. Each sub-row passes through as a
                 plain dict to preserve the legacy contract.

The kind a given stats tool maps to is recorded via
``register_tool_type(tool_name, type_class, kind)`` so the route's
dual-kind dispatcher can look it up.
"""

from __future__ import annotations

from typing import Any

import strawberry


def _normalize_ts(point: dict) -> int:
    ts = point.get("ts") or point.get("time") or point.get("timestamp") or 0
    if ts and ts < 10_000_000_000:  # likely seconds → ms
        ts = ts * 1000
    return ts


@strawberry.type(description="A single timeseries point: {ts: <ms>, ...metrics}.")
class StatPoint:
    # The actual metric payload is heterogeneous across stats endpoints
    # (rx_bytes, tx_bytes, wan_rx, num_user, ...). The Strawberry layer
    # only declares ``ts`` as a typed field; the rest of the metrics are
    # carried as a private dict and re-flattened on ``to_dict()`` to keep
    # the legacy ``{ts, ...metric_keys}`` contract.
    ts: int
    _metrics: strawberry.Private[dict[str, Any]]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind, "sort_default": "ts:desc"}

    @classmethod
    def from_manager_output(cls, point: Any) -> "StatPoint":
        if not isinstance(point, dict):
            return cls(ts=0, _metrics={})
        ts = _normalize_ts(point)
        metrics = {k: v for k, v in point.items() if k not in ("time", "timestamp", "ts")}
        return cls(ts=ts, _metrics=metrics)

    def to_dict(self) -> dict:
        return {"ts": self.ts, **self._metrics}


@strawberry.type(description="DPI stats wrapper: applications + categories arrays.")
class DpiStats:
    # Wrapper-dict shape; each sub-row is a passthrough dict (unstructured —
    # the controller's DPI catalogs vary by firmware so we don't tighten the
    # schema here). Exposed as ``JSON`` scalars on the GraphQL surface so the
    # heterogeneous payload survives without an enumerated sub-type.
    applications: strawberry.scalars.JSON  # type: ignore[name-defined]
    categories: strawberry.scalars.JSON  # type: ignore[name-defined]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "DpiStats":
        if not isinstance(obj, dict):
            return cls(applications=[], categories=[])

        def _itemize(items):
            out = []
            for it in items or []:
                if isinstance(it, dict):
                    out.append(it)
                else:
                    raw = getattr(it, "raw", None)
                    if isinstance(raw, dict):
                        out.append(dict(raw))
            return out

        return cls(
            applications=_itemize(obj.get("applications")),
            categories=_itemize(obj.get("categories")),
        )

    def to_dict(self) -> dict:
        return {
            "applications": list(self.applications),
            "categories": list(self.categories),
        }
