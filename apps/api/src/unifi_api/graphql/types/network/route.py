"""Strawberry types for network/routes (static + active + traffic routes).

Phase 6 PR2 Task 21 migration target. Three read shapes that used to live in
``unifi_api.serializers.network.routes``:

- ``Route``        — list_routes + get_route_details (static routes via V1 ``/rest/routing``)
- ``ActiveRoute``  — list_active_routes (kernel routing table from ``/stat/routing``)
- ``TrafficRoute`` — list_traffic_routes + get_traffic_route_details (V2 ``/trafficroutes``)

Static routes use V1 hyphen-prefixed fields (``static-route_network``,
``static-route_nexthop``, ``static-route_distance``). Active routes come
from the undocumented ``/stat/routing`` endpoint with a nested ``nh`` list
of ``{intf, via}`` next-hop entries. Traffic routes use ``description`` for
the human-readable name and ``matching_target`` (DOMAIN/IP/REGION) for what
triggers the route.

Each type's ``from_manager_output(raw)`` classmethod replaces the dict-shaping
logic that used to live in serializers/network/routes.py. ``to_dict()``
exposes the same dict contract the REST routes return today.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


def _summarize_targets(value: Any) -> Any:
    """Pass-through helper: traffic-route target lists are returned as-is when
    present, ``None`` otherwise. Mirrors the legacy serializer behavior."""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    return value


@strawberry.type(description="A static route configured on the gateway.")
class Route:
    id: strawberry.ID | None
    name: str | None
    target_subnet: str | None
    gateway: str | None
    distance: int | None
    enabled: bool

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "target_subnet", "gateway", "distance", "enabled"],
            "sort_default": "name:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "Route":
        return cls(
            id=_get(obj, "_id") or _get(obj, "id"),
            name=_get(obj, "name"),
            target_subnet=_get(obj, "static-route_network") or _get(obj, "target_subnet") or _get(obj, "network"),
            gateway=_get(obj, "static-route_nexthop") or _get(obj, "gateway") or _get(obj, "nexthop"),
            distance=_get(obj, "static-route_distance") or _get(obj, "distance"),
            enabled=bool(_get(obj, "enabled", True)),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@strawberry.type(description="An active kernel routing-table entry on a gateway.")
class ActiveRoute:
    """``/stat/routing`` rows. ``primary_key`` is ``target_subnet`` since
    active routes have no stable id."""

    target_subnet: str | None
    gateway: str | None
    interface: str | None
    distance: int | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "target_subnet",
            "display_columns": ["target_subnet", "gateway", "interface", "distance"],
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "ActiveRoute":
        # /stat/routing returns nh as a list of {via, intf} dicts; pluck the
        # first to populate gateway/interface. Falls through cleanly when the
        # endpoint emits a flatter shape.
        nh_list = _get(obj, "nh") or []
        first_nh: dict[str, Any] = nh_list[0] if isinstance(nh_list, list) and nh_list else {}
        return cls(
            target_subnet=_get(obj, "pfx") or _get(obj, "target_subnet") or _get(obj, "network"),
            gateway=first_nh.get("via") or _get(obj, "gateway") or _get(obj, "nexthop"),
            interface=first_nh.get("intf") or _get(obj, "interface") or _get(obj, "intf"),
            distance=_get(obj, "metric") or _get(obj, "distance"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@strawberry.type(description="A traffic-route policy (V2 /trafficroutes entry).")
class TrafficRoute:
    id: strawberry.ID | None
    name: str | None
    matching_target: str | None
    network_id: str | None
    next_hop: str | None
    enabled: bool
    kill_switch_enabled: bool | None
    # Aggregated read views of the per-type target lists (read-only shapes).
    source_targets: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    destination_targets: strawberry.scalars.JSON | None  # type: ignore[name-defined]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "matching_target", "next_hop", "enabled"],
            "sort_default": "name:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "TrafficRoute":
        return cls(
            id=_get(obj, "_id") or _get(obj, "id"),
            name=_get(obj, "description") or _get(obj, "name"),
            matching_target=_get(obj, "matching_target"),
            network_id=_get(obj, "network_id"),
            next_hop=_get(obj, "next_hop"),
            enabled=bool(_get(obj, "enabled", True)),
            kill_switch_enabled=_get(obj, "kill_switch_enabled"),
            source_targets=_summarize_targets(_get(obj, "target_devices")),
            destination_targets=_summarize_targets(
                _get(obj, "domains") or _get(obj, "ip_addresses") or _get(obj, "ip_ranges") or _get(obj, "regions")
            ),
        )

    def to_dict(self) -> dict:
        return asdict(self)
