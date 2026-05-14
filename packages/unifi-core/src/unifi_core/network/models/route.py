"""Shared field models for Network static routes.

Mirrors the Strawberry types in
``unifi_api.graphql.types.network.route``:

- ``Route``       — list_routes + get_route_details (static routes via V1 ``/rest/routing``)
- ``ActiveRoute`` — list_active_routes (kernel routing table from ``/stat/routing``)

Both classes are read-only (no update/create tools use these models for
validation). The models exist to provide typed output shaping and
cross-layer symmetry test coverage.

Factory helpers:
- ``route_from_controller``        — normalise raw → Route
- ``active_route_from_controller`` — normalise raw → ActiveRoute

Per-class MUTABLE_FIELDS constants drive the cross-layer symmetry test.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, *keys: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        for k in keys:
            v = obj.get(k)
            if v is not None:
                return v
        return default
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        for k in keys:
            v = raw.get(k)
            if v is not None:
                return v
        return default
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None:
            return v
    return default


# ---------------------------------------------------------------------------
# Route — static route (V1 /rest/routing)
# ---------------------------------------------------------------------------


class Route(BaseModel):
    """Canonical static route model (read-only output shape).

    Static routes use V1 hyphen-prefixed controller fields:
    ``static-route_network``, ``static-route_nexthop``,
    ``static-route_distance``.
    """

    id: Optional[str] = Field(
        default=None,
        description="Route UUID (assigned by controller)",
        json_schema_extra={"mutable": False},
    )
    name: Optional[str] = Field(
        default=None,
        description="Descriptive name for the route",
        json_schema_extra={"mutable": False},
    )
    target_subnet: Optional[str] = Field(
        default=None,
        description="Destination network in CIDR notation",
        json_schema_extra={"mutable": False},
    )
    gateway: Optional[str] = Field(
        default=None,
        description="Next-hop gateway IP address",
        json_schema_extra={"mutable": False},
    )
    distance: Optional[int] = Field(
        default=None,
        description="Administrative distance / route metric (lower = preferred)",
        json_schema_extra={"mutable": False},
    )
    enabled: bool = Field(
        default=True,
        description="Whether the route is active",
        json_schema_extra={"mutable": False},
    )


ROUTE_MUTABLE_FIELDS: frozenset[str] = frozenset()
ROUTE_READ_ONLY_FIELDS: frozenset[str] = frozenset(Route.model_fields.keys())


def route_from_controller(raw: Any) -> Route:
    """Build a Route from a controller API response dict.

    The controller stores destination as ``static-route_network``,
    gateway as ``static-route_nexthop``, and metric as
    ``static-route_distance``.
    """
    return Route(
        id=_get(raw, "_id", "id"),
        name=_get(raw, "name"),
        target_subnet=_get(raw, "static-route_network", "target_subnet", "network"),
        gateway=_get(raw, "static-route_nexthop", "gateway", "nexthop"),
        distance=_get(raw, "static-route_distance", "distance"),
        enabled=bool(_get(raw, "enabled", default=True)),
    )


# ---------------------------------------------------------------------------
# ActiveRoute — kernel routing table entry (/stat/routing)
# ---------------------------------------------------------------------------


class ActiveRoute(BaseModel):
    """Canonical active-route model (read-only output shape).

    ``/stat/routing`` rows. ``target_subnet`` is the natural primary key
    since active routes have no stable id.
    The controller returns next-hop info under the nested ``nh`` list of
    ``{via, intf}`` dicts; this model flattens the first entry.
    """

    target_subnet: Optional[str] = Field(
        default=None,
        description="Destination network prefix",
        json_schema_extra={"mutable": False},
    )
    gateway: Optional[str] = Field(
        default=None,
        description="Next-hop gateway IP address",
        json_schema_extra={"mutable": False},
    )
    interface: Optional[str] = Field(
        default=None,
        description="Outbound network interface name",
        json_schema_extra={"mutable": False},
    )
    distance: Optional[int] = Field(
        default=None,
        description="Route metric",
        json_schema_extra={"mutable": False},
    )


ACTIVEROUTE_MUTABLE_FIELDS: frozenset[str] = frozenset()
ACTIVEROUTE_READ_ONLY_FIELDS: frozenset[str] = frozenset(ActiveRoute.model_fields.keys())

# Module-level alias (symmetry test fallback)
MUTABLE_FIELDS = ROUTE_MUTABLE_FIELDS


def active_route_from_controller(raw: Any) -> ActiveRoute:
    """Build an ActiveRoute from a ``/stat/routing`` controller response row.

    The controller nests next-hop details under the ``nh`` list; this
    helper plucks the first entry to populate gateway and interface.
    Falls through cleanly when the endpoint emits a flatter shape.
    """
    if isinstance(raw, dict):
        nh_list = raw.get("nh") or []
    else:
        nh_list = getattr(raw, "nh", []) or []

    first_nh: dict = nh_list[0] if isinstance(nh_list, list) and nh_list else {}

    return ActiveRoute(
        target_subnet=_get(raw, "pfx", "target_subnet", "network"),
        gateway=first_nh.get("via") or _get(raw, "gateway", "nexthop"),
        interface=first_nh.get("intf") or _get(raw, "interface", "intf"),
        distance=_get(raw, "metric", "distance"),
    )
