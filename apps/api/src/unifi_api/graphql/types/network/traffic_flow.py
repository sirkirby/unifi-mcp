"""Strawberry types for network/traffic-flows.

Read shape emitted by ``TrafficFlowManager.get_traffic_flows()`` (LIST). Each
flow dict comes from ``traffic_flow_from_controller(...).model_dump(
exclude_none=True)`` and carries scalar fields plus ``source`` / ``destination``
endpoint sub-objects.

- ``TrafficFlowEndpoint`` — one side of a flow (source or destination).
- ``TrafficFlow`` — a single traffic-flow record.
- ``TrafficFlowPage`` — paginated wrapper around ``TrafficFlow`` items.

Each type's ``from_manager_output(raw)`` classmethod shapes the manager dict
into the type; ``to_dict()`` exposes the dict contract the REST routes return.

The manager's ``policies`` field is intentionally not projected here: its shape
is firmware-variable, so it is omitted from the GraphQL type and REST rows for
now and can be added later without a breaking change.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry


def _get(obj: Any, *keys: str, default: Any = None) -> Any:
    """Return the first non-None value among ``keys`` (dict input), else ``default``.

    Matches the variadic helper convention in ``session.py`` so field aliases can
    be added by listing extra keys rather than changing the signature.
    """
    if not isinstance(obj, dict):
        return default
    for k in keys:
        v = obj.get(k)
        if v is not None:
            return v
    return default


@strawberry.type(description="One side (source or destination) of a traffic flow.")
class TrafficFlowEndpoint:
    name: str | None
    mac: str | None
    ip: str | None
    network_name: str | None
    zone_name: str | None
    domains: list[str]

    @classmethod
    def from_manager_output(cls, obj: Any) -> "TrafficFlowEndpoint":
        return cls(
            name=_get(obj, "name"),
            mac=_get(obj, "mac"),
            ip=_get(obj, "ip"),
            network_name=_get(obj, "network_name"),
            zone_name=_get(obj, "zone_name"),
            domains=_get(obj, "domains", default=[]),
        )


@strawberry.type(description="A single UniFi traffic-flow record.")
class TrafficFlow:
    id: str | None
    action: str | None
    risk: str | None
    service: str | None
    protocol: str | None
    direction: str | None
    count: int | None
    duration_milliseconds: int | None
    time: int | None
    flow_start_time: int | None
    flow_end_time: int | None
    bytes_total: int | None
    bytes_rx: int | None
    bytes_tx: int | None
    source: TrafficFlowEndpoint
    destination: TrafficFlowEndpoint

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": [
                "time",
                "source",
                "destination",
                "service",
                "risk",
                "action",
            ],
            "sort_default": "time:desc",
        }

    @classmethod
    def from_manager_output(cls, record: Any) -> "TrafficFlow":
        return cls(
            id=_get(record, "id"),
            action=_get(record, "action"),
            risk=_get(record, "risk"),
            service=_get(record, "service"),
            protocol=_get(record, "protocol"),
            direction=_get(record, "direction"),
            count=_get(record, "count"),
            duration_milliseconds=_get(record, "duration_milliseconds"),
            time=_get(record, "time"),
            flow_start_time=_get(record, "flow_start_time"),
            flow_end_time=_get(record, "flow_end_time"),
            bytes_total=_get(record, "bytes_total"),
            bytes_rx=_get(record, "bytes_rx"),
            bytes_tx=_get(record, "bytes_tx"),
            source=TrafficFlowEndpoint.from_manager_output(_get(record, "source")),
            destination=TrafficFlowEndpoint.from_manager_output(_get(record, "destination")),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@strawberry.type(description="Paginated page of UniFi traffic flows.")
class TrafficFlowPage:
    items: list[TrafficFlow]
    next_cursor: str | None = None


# ---------------------------------------------------------------------------
# Traffic-flow statistics (Insights > Flows "Flow Summary")
#
# Mirrors ``TrafficFlowManager.get_traffic_flow_statistics()``. Count-by-risk /
# region maps are exposed as ``JSON`` scalars (dynamic key sets); the Top-Talker
# rankings are enumerated sub-types.
# ---------------------------------------------------------------------------


@strawberry.type(description="A client in a traffic-flow Top-Talkers ranking.")
class TrafficFlowTopClient:
    count: int | None
    client_mac: str | None
    client_name: str | None

    @classmethod
    def from_manager_output(cls, obj: Any) -> "TrafficFlowTopClient":
        return cls(
            count=_get(obj, "count"),
            client_mac=_get(obj, "client_mac"),
            client_name=_get(obj, "client_name"),
        )


@strawberry.type(description="A destination in a traffic-flow Top-Talkers ranking.")
class TrafficFlowTopDestination:
    count: int | None
    destination: str | None
    most_frequent_region: str | None

    @classmethod
    def from_manager_output(cls, obj: Any) -> "TrafficFlowTopDestination":
        return cls(
            count=_get(obj, "count"),
            destination=_get(obj, "destination"),
            most_frequent_region=_get(obj, "most_frequent_region"),
        )


@strawberry.type(description="An application in a traffic-flow Top-Talkers ranking (by bytes).")
class TrafficFlowTopApplication:
    application_id: int | None
    category_id: int | None
    bytes: int | None
    application_name: str | None
    category_name: str | None

    @classmethod
    def from_manager_output(cls, obj: Any) -> "TrafficFlowTopApplication":
        return cls(
            application_id=_get(obj, "application_id"),
            category_id=_get(obj, "category_id"),
            bytes=_get(obj, "bytes"),
            application_name=_get(obj, "application_name"),
            category_name=_get(obj, "category_name"),
        )


@strawberry.type(description="A policy in a traffic-flow blocked-flow ranking.")
class TrafficFlowTopPolicy:
    count: int | None
    policy_id: str | None
    policy_name: str | None
    policy_type: str | None

    @classmethod
    def from_manager_output(cls, obj: Any) -> "TrafficFlowTopPolicy":
        return cls(
            count=_get(obj, "count"),
            policy_id=_get(obj, "policy_id"),
            policy_name=_get(obj, "policy_name"),
            policy_type=_get(obj, "policy_type"),
        )


@strawberry.type(description="Aggregated Insights > Flows summary (latest-statistics).")
class TrafficFlowStatistics:
    # Count maps keyed by risk band (low/medium/high) or region (country code);
    # dynamic key sets, so exposed as JSON scalars.
    allowed_count_by_risk: strawberry.scalars.JSON  # type: ignore[name-defined]
    blocked_count_by_risk: strawberry.scalars.JSON  # type: ignore[name-defined]
    allowed_count_by_region_by_risk: strawberry.scalars.JSON  # type: ignore[name-defined]
    all_count_by_region: strawberry.scalars.JSON  # type: ignore[name-defined]
    blocked_count_by_region: strawberry.scalars.JSON  # type: ignore[name-defined]
    top_clients: list[TrafficFlowTopClient]
    top_blocked_clients: list[TrafficFlowTopClient]
    top_destinations: list[TrafficFlowTopDestination]
    top_applications: list[TrafficFlowTopApplication]
    top_blocked_policies: list[TrafficFlowTopPolicy]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "TrafficFlowStatistics":
        def _list(key: str, sub: Any) -> list:
            return [sub.from_manager_output(i) for i in (_get(obj, key, default=[]) or [])]

        return cls(
            allowed_count_by_risk=_get(obj, "allowed_count_by_risk", default={}),
            blocked_count_by_risk=_get(obj, "blocked_count_by_risk", default={}),
            allowed_count_by_region_by_risk=_get(obj, "allowed_count_by_region_by_risk", default={}),
            all_count_by_region=_get(obj, "all_count_by_region", default={}),
            blocked_count_by_region=_get(obj, "blocked_count_by_region", default={}),
            top_clients=_list("top_clients", TrafficFlowTopClient),
            top_blocked_clients=_list("top_blocked_clients", TrafficFlowTopClient),
            top_destinations=_list("top_destinations", TrafficFlowTopDestination),
            top_applications=_list("top_applications", TrafficFlowTopApplication),
            top_blocked_policies=_list("top_blocked_policies", TrafficFlowTopPolicy),
        )

    def to_dict(self) -> dict:
        return asdict(self)
