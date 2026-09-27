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

import ipaddress
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from unifi_core.mac import canonical_mac

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


_SELECTORS = frozenset({"domains", "ip_addresses", "ip_ranges", "regions"})
_WRITE_FIELDS = frozenset(TrafficRoute.model_fields) - {"id", "name"} | {"description"}
_UPDATE_FIELDS = _WRITE_FIELDS - {"matching_target"}


class TrafficRouteValidationError(ValueError):
    """Invalid traffic-route fields submitted by a caller."""


def _nonempty(value: Any) -> bool:
    return type(value) is str and bool(value.strip())


def _object(value: Any, *, label: str, required: set[str], allowed: set[str]) -> Dict[str, Any]:
    if type(value) is not dict:
        raise ValueError(f"Each {label} entry must be an object.")
    missing, unknown = required - value.keys(), value.keys() - allowed
    if missing or unknown:
        raise ValueError(f"Each {label} entry has invalid field(s): {', '.join(sorted(map(str, missing | unknown)))}.")
    return value


def _ports(value: Any, *, label: str) -> List[int]:
    if type(value) is not list or any(type(port) is not int or not 1 <= port <= 65535 for port in value):
        raise ValueError(f"{label} must contain integer ports from 1 through 65535.")
    return value


def _port_ranges(value: Any, *, label: str) -> List[Dict[str, int]]:
    if type(value) is not list:
        raise ValueError(f"{label} must be a list.")
    for item in value:
        _object(item, label=label, required={"port_start", "port_stop"}, allowed={"port_start", "port_stop"})
        start, stop = item["port_start"], item["port_stop"]
        if type(start) is not int or type(stop) is not int or not 1 <= start <= stop <= 65535:
            raise ValueError(f"{label} entries must contain ordered ports from 1 through 65535.")
    return value


def _domains(value: Any) -> List[Dict[str, Any]]:
    if type(value) is not list or not value:
        raise ValueError("DOMAIN Traffic Routes require a non-empty domains list.")
    result = []
    for item in value:
        _object(item, label="domains", required={"domain"}, allowed={"domain", "ports", "port_ranges"})
        if not _nonempty(item["domain"]):
            raise ValueError("Each domains entry must contain a non-empty domain.")
        result.append(
            {
                "domain": item["domain"],
                "ports": _ports(item.get("ports", []), label="domains.ports"),
                "port_ranges": _port_ranges(item.get("port_ranges", []), label="domains.port_ranges"),
            }
        )
    return result


def _ip_version(value: Any, *, version: int, label: str) -> str:
    """Use the Network controller's v4/v6 enum for submitted IP selectors."""
    controller_value = f"v{version}"
    if type(value) is str and value in {controller_value, f"IPV{version}"}:
        return controller_value
    raise ValueError(f"Each {label} ip_version must match its address family (v4 or v6).")


def _ip_addresses(value: Any) -> List[Dict[str, Any]]:
    if type(value) is not list:
        raise ValueError("ip_addresses must be a list.")
    result = []
    for item in value:
        _object(
            item,
            label="ip_addresses",
            required={"ip_or_subnet", "ip_version"},
            allowed={"ip_or_subnet", "ip_version", "ports", "port_ranges"},
        )
        if not _nonempty(item["ip_or_subnet"]):
            raise ValueError("Each ip_addresses entry must contain a non-empty ip_or_subnet.")
        try:
            address = ipaddress.ip_network(item["ip_or_subnet"], strict=False)
        except ValueError:
            raise ValueError("Each ip_addresses ip_or_subnet must be a valid IP address or subnet.") from None
        result.append(
            {
                "ip_or_subnet": item["ip_or_subnet"],
                "ip_version": _ip_version(item["ip_version"], version=address.version, label="ip_addresses"),
                "ports": _ports(item.get("ports", []), label="ip_addresses.ports"),
                "port_ranges": _port_ranges(item.get("port_ranges", []), label="ip_addresses.port_ranges"),
            }
        )
    return result


def _ip_ranges(value: Any) -> List[Dict[str, Any]]:
    if type(value) is not list:
        raise ValueError("ip_ranges must be a list.")
    result = []
    for item in value:
        _object(
            item,
            label="ip_ranges",
            required={"ip_start", "ip_stop", "ip_version"},
            allowed={"ip_start", "ip_stop", "ip_version"},
        )
        if not _nonempty(item["ip_start"]) or not _nonempty(item["ip_stop"]):
            raise ValueError("Each ip_ranges entry must contain non-empty ip_start and ip_stop.")
        try:
            start, stop = ipaddress.ip_address(item["ip_start"]), ipaddress.ip_address(item["ip_stop"])
        except ValueError:
            raise ValueError("Each ip_ranges entry must contain valid IP addresses.") from None
        if start.version != stop.version or start > stop:
            raise ValueError("Each ip_ranges entry must be an ordered range in one address family.")
        result.append(
            {
                "ip_start": item["ip_start"],
                "ip_stop": item["ip_stop"],
                "ip_version": _ip_version(item["ip_version"], version=start.version, label="ip_ranges"),
            }
        )
    return result


def _regions(value: Any) -> List[str]:
    if type(value) is not list or not value or any(not _nonempty(item) for item in value):
        raise ValueError("REGION Traffic Routes require non-empty region strings.")
    return value


def _target_devices(value: Any) -> List[Dict[str, str]]:
    if type(value) is not list or not value:
        raise ValueError("target_devices must be a non-empty list when supplied.")
    result = []
    for item in value:
        _object(item, label="target_devices", required={"type"}, allowed={"type", "client_mac", "network_id"})
        kind = item["type"]
        if kind == "ALL_CLIENTS":
            if len(value) != 1 or set(item) != {"type"}:
                raise ValueError("ALL_CLIENTS must appear alone without client_mac or network_id.")
            result.append({"type": kind})
        elif kind == "CLIENT":
            mac = canonical_mac(item.get("client_mac"))
            if set(item) != {"type", "client_mac"} or mac is None:
                raise ValueError("CLIENT target_devices entries require a valid client_mac and no network_id.")
            result.append({"type": kind, "client_mac": mac})
        elif kind == "NETWORK":
            if set(item) != {"type", "network_id"} or not _nonempty(item["network_id"]):
                raise ValueError("NETWORK target_devices entries require a non-empty network_id and no client_mac.")
            result.append({"type": kind, "network_id": item["network_id"]})
        else:
            raise ValueError("target_devices type must be ALL_CLIENTS, CLIENT, or NETWORK.")
    return result


def _validate_create_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate submitted controller fields without adding an implicit client scope."""
    if type(payload) is not dict:
        raise ValueError("Traffic Route create payload must be an object.")
    unknown = payload.keys() - _WRITE_FIELDS
    if unknown:
        raise ValueError(f"Unknown Traffic Route field(s): {', '.join(sorted(unknown))}.")
    raw_target = payload.get("matching_target")
    target = raw_target.strip().upper() if type(raw_target) is str else None
    if target not in {"DOMAIN", "IP", "REGION", "INTERNET"}:
        raise ValueError("matching_target must be DOMAIN, IP, REGION, or INTERNET.")
    if not _nonempty(payload.get("description")) or len(payload["description"]) > 128:
        raise ValueError("description is required and must be at most 128 characters.")
    if not _nonempty(payload.get("network_id")):
        raise ValueError("network_id is required.")
    result = payload.copy()
    result["matching_target"] = target
    for field in ("enabled", "kill_switch_enabled"):
        if field in result and type(result[field]) is not bool:
            raise ValueError(f"{field} must be a boolean.")
    if "next_hop" in result and type(result["next_hop"]) is not str:
        raise ValueError("next_hop must be a string.")
    allowed = {"DOMAIN": {"domains"}, "IP": {"ip_addresses", "ip_ranges"}, "REGION": {"regions"}, "INTERNET": set()}[
        target
    ]
    for field in _SELECTORS - allowed:
        if result.get(field) not in (None, []):
            raise ValueError(f"{target} Traffic Routes do not accept selector field(s): {field}.")
    if target == "DOMAIN":
        result["domains"] = _domains(result.get("domains"))
    elif target == "IP":
        result["ip_addresses"] = _ip_addresses(result.get("ip_addresses", []))
        result["ip_ranges"] = _ip_ranges(result.get("ip_ranges", []))
        if not (result["ip_addresses"] or result["ip_ranges"]):
            raise ValueError("IP Traffic Routes require ip_addresses or ip_ranges.")
    elif target == "REGION":
        result["regions"] = _regions(result.get("regions"))
    if "target_devices" in result:
        result["target_devices"] = _target_devices(result["target_devices"])
    return result


def validate_create_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a complete create payload and mark only deliberate input failures."""
    try:
        return _validate_create_payload(payload)
    except ValueError as exc:
        raise TrafficRouteValidationError(str(exc)) from None


def _validate_update_fields(fields: Dict[str, Any], *, current: Dict[str, Any]) -> Dict[str, Any]:
    """Validate only submitted replacements; fetched legacy values remain untouched."""
    if type(fields) is not dict:
        raise ValueError("Traffic Route update data must be an object.")
    immutable = fields.keys() & {"_id", "id", "matching_target"}
    if immutable:
        raise ValueError(f"Traffic Route field(s) are immutable: {', '.join(sorted(immutable))}.")
    unknown = fields.keys() - _UPDATE_FIELDS
    if unknown:
        raise ValueError(f"Unknown Traffic Route field(s): {', '.join(sorted(unknown))}.")
    result = {key: value for key, value in fields.items() if value is not None}
    for field in ("enabled", "kill_switch_enabled"):
        if field in result and type(result[field]) is not bool:
            raise ValueError(f"{field} must be a boolean.")
    if "description" in result and (not _nonempty(result["description"]) or len(result["description"]) > 128):
        raise ValueError("description must be a non-empty string with at most 128 characters.")
    if "network_id" in result and not _nonempty(result["network_id"]):
        raise ValueError("network_id must be a non-empty string.")
    if "next_hop" in result and type(result["next_hop"]) is not str:
        raise ValueError("next_hop must be a string.")
    raw_target = current.get("matching_target")
    target = raw_target.strip().upper() if isinstance(raw_target, str) else None
    allowed = {
        "DOMAIN": {"domains"},
        "IP": {"ip_addresses", "ip_ranges"},
        "REGION": {"regions"},
        "INTERNET": set(),
    }.get(target, set())
    for field in result.keys() & (_SELECTORS - allowed):
        if result[field] == []:
            continue
        if target in {"DOMAIN", "IP", "REGION", "INTERNET"}:
            raise ValueError(f"{target} Traffic Routes do not accept selector field(s): {field}.")
        raise ValueError("Current Traffic Route matching_target does not permit selector updates.")
    if "domains" in result and target == "DOMAIN":
        result["domains"] = _domains(result["domains"])
    if "ip_addresses" in result and target == "IP":
        result["ip_addresses"] = _ip_addresses(result["ip_addresses"])
    if "ip_ranges" in result and target == "IP":
        result["ip_ranges"] = _ip_ranges(result["ip_ranges"])
    if target == "IP" and result.keys() & {"ip_addresses", "ip_ranges"}:
        if not (
            result.get("ip_addresses", current.get("ip_addresses")) or result.get("ip_ranges", current.get("ip_ranges"))
        ):
            raise ValueError("IP Traffic Routes require ip_addresses or ip_ranges.")
    if "regions" in result and target == "REGION":
        result["regions"] = _regions(result["regions"])
    if "target_devices" in result:
        result["target_devices"] = _target_devices(result["target_devices"])
    return result


def validate_update_fields(fields: Dict[str, Any], *, current: Dict[str, Any]) -> Dict[str, Any]:
    """Validate submitted replacements without parsing fetched controller fields."""
    try:
        return _validate_update_fields(fields, current=current)
    except ValueError as exc:
        raise TrafficRouteValidationError(str(exc)) from None


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
