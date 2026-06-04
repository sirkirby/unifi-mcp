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
