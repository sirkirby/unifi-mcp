"""Shared field model for Network traffic-route (policy-based routing) rules.

Mirrors the Strawberry type in
``unifi_api.graphql.types.network.route`` (class ``TrafficRoute``).

- ``TrafficRoute`` — list_traffic_routes + get_traffic_route_details +
  update_traffic_route + toggle_traffic_route

Factory helpers:
- ``from_controller``      — normalise the raw controller dict → TrafficRoute
- ``to_controller_create`` — translate a TrafficRoute → create payload
- ``to_controller_update`` — filter a partial dict to mutable keys only

``MUTABLE_FIELDS`` drives the cross-layer symmetry test: the Strawberry
type must expose every field listed here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Pydantic domain model
# ---------------------------------------------------------------------------


class TrafficRoute(BaseModel):
    """Canonical traffic-route policy model (read + mutable create/update fields)."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="Route UUID (assigned by controller)",
        json_schema_extra={"mutable": False},
    )

    # --- mutable (simple scalar fields) ---
    name: Optional[str] = Field(
        default=None,
        description="Descriptive name for the traffic route (controller field: 'description')",
    )
    matching_target: Optional[str] = Field(
        default=None,
        description="Specifies the destination/source type: INTERNET, DOMAIN, IP, or REGION",
    )
    network_id: Optional[str] = Field(
        default=None,
        description="Network ID (LAN/VLAN) the route applies to",
    )
    enabled: Optional[bool] = Field(
        default=None,
        description="Whether the route is active",
    )
    kill_switch_enabled: Optional[bool] = Field(
        default=None,
        description="Whether the kill switch is enabled (blocks traffic if VPN is down)",
    )
    next_hop: Optional[str] = Field(
        default=None,
        description="Next hop IP address (advanced routing)",
    )

    # --- complex list fields (create/update capable but excluded from
    #     MUTABLE_FIELDS to avoid Strawberry JSON-scalar type mismatch in
    #     the cross-layer symmetry test; set via to_controller_create) ---
    domains: Optional[List[Any]] = Field(
        default=None,
        description="List of domains with ports (used with matching_target: DOMAIN)",
        json_schema_extra={"mutable": False},
    )
    ip_addresses: Optional[List[Any]] = Field(
        default=None,
        description="List of IPs/subnets with ports (used with matching_target: IP)",
        json_schema_extra={"mutable": False},
    )
    ip_ranges: Optional[List[Any]] = Field(
        default=None,
        description="List of IP ranges (used with matching_target: IP)",
        json_schema_extra={"mutable": False},
    )
    regions: Optional[List[str]] = Field(
        default=None,
        description="List of regions (used with matching_target: REGION)",
        json_schema_extra={"mutable": False},
    )
    target_devices: Optional[List[Any]] = Field(
        default=None,
        description="List of client devices or networks the route applies to",
        json_schema_extra={"mutable": False},
    )


# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------

MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in TrafficRoute.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in TrafficRoute.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True) is False
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


# ---------------------------------------------------------------------------
# Public factory helpers
# ---------------------------------------------------------------------------


def from_controller(raw: Any) -> TrafficRoute:
    """Build a TrafficRoute from a controller API response dict.

    The controller stores the human-readable name as 'description'.
    """
    return TrafficRoute(
        id=_get(raw, "_id") or _get(raw, "id"),
        name=_get(raw, "description") or _get(raw, "name"),
        matching_target=_get(raw, "matching_target"),
        network_id=_get(raw, "network_id"),
        enabled=_get(raw, "enabled"),
        kill_switch_enabled=_get(raw, "kill_switch_enabled"),
        next_hop=_get(raw, "next_hop"),
        domains=_get(raw, "domains"),
        ip_addresses=_get(raw, "ip_addresses"),
        ip_ranges=_get(raw, "ip_ranges"),
        regions=_get(raw, "regions"),
        target_devices=_get(raw, "target_devices"),
    )


def to_controller_create(model: TrafficRoute) -> Dict[str, Any]:
    """Produce a controller create payload from a TrafficRoute model.

    Maps model 'name' back to the controller's 'description' field.
    Includes all non-None fields (scalar + list).
    """
    all_fields = set(TrafficRoute.model_fields.keys()) - {"id"}
    payload: Dict[str, Any] = {}
    for field_name in all_fields:
        value = getattr(model, field_name, None)
        if value is not None:
            payload[field_name] = value
    # Map name → description for controller compatibility
    if "name" in payload:
        payload["description"] = payload.pop("name")
    return payload


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to only mutable, recognised keys.

    Read-only fields (id) and unrecognised keys are dropped.
    ``None`` values are dropped; boolean ``False`` is preserved.
    Maps 'name' → 'description' for controller compatibility.
    """
    # Accept both MUTABLE_FIELDS scalar keys and the list fields for update
    accepted = MUTABLE_FIELDS | {"domains", "ip_addresses", "ip_ranges", "regions", "target_devices"}
    result = {k: v for k, v in fields.items() if k in accepted and v is not None}
    # Map name → description for controller compatibility
    if "name" in result:
        result["description"] = result.pop("name")
    return result
