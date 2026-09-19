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
        json_schema_extra={"mutable": False},
    )
    network_id: Optional[str] = Field(
        default=None,
        description="Network ID (LAN/VLAN) the route applies to",
        json_schema_extra={"mutable": False},
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

    # --- complex list fields (create/update capable) ---
    domains: Optional[List[Any]] = Field(
        default=None,
        description="List of domains with ports (used with matching_target: DOMAIN)",
    )
    ip_addresses: Optional[List[Any]] = Field(
        default=None,
        description="List of IPs/subnets with ports (used with matching_target: IP)",
    )
    ip_ranges: Optional[List[Any]] = Field(
        default=None,
        description="List of IP ranges (used with matching_target: IP)",
    )
    # Controller-read values can include historical non-string selectors;
    # create/update helpers validate submitted replacements separately.
    regions: Optional[List[Any]] = Field(
        default=None,
        description="List of regions (used with matching_target: REGION)",
    )
    target_devices: Optional[List[Any]] = Field(
        default=None,
        description="List of client devices or networks the route applies to",
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


def _is_nonempty_string(value: Any) -> bool:
    return type(value) is str and bool(value.strip())


def _is_nonempty_list(value: Any) -> bool:
    return type(value) is list and bool(value)


_SELECTOR_FIELDS = frozenset({"domains", "ip_addresses", "ip_ranges", "regions"})
_UPDATE_FIELDS = MUTABLE_FIELDS


def _allowed_selectors(target: str) -> set[str]:
    if target == "DOMAIN":
        return {"domains"}
    if target == "IP":
        return {"ip_addresses", "ip_ranges"}
    return {"regions"}


def _require_keys(value: Any, *, allowed: set[str], required: set[str], label: str) -> Dict[str, Any]:
    if type(value) is not dict:
        raise ValueError(f"Each {label} entry must be an object.")
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise ValueError(f"Each {label} entry has unknown field(s): {', '.join(sorted(unknown))}.")
    if missing:
        raise ValueError(f"Each {label} entry is missing field(s): {', '.join(sorted(missing))}.")
    return value


def _validate_ports(value: Any, *, label: str) -> List[int]:
    if type(value) is not list:
        raise ValueError(f"{label} must be a list.")
    if any(type(port) is not int or not 1 <= port <= 65535 for port in value):
        raise ValueError(f"{label} entries must be integer ports from 1 through 65535.")
    return value


def _validate_port_ranges(value: Any, *, label: str) -> List[Dict[str, int]]:
    if type(value) is not list:
        raise ValueError(f"{label} must be a list.")
    result = []
    for item in value:
        item = _require_keys(
            item,
            allowed={"port_start", "port_stop"},
            required={"port_start", "port_stop"},
            label=label,
        )
        start, stop = item["port_start"], item["port_stop"]
        if type(start) is not int or type(stop) is not int or not 1 <= start <= stop <= 65535:
            raise ValueError(f"{label} entries must have port_start and port_stop from 1 through 65535 in order.")
        result.append({"port_start": start, "port_stop": stop})
    return result


def _validate_domains(value: Any, *, required: bool) -> List[Dict[str, Any]]:
    if type(value) is not list or (required and not value):
        raise ValueError("DOMAIN Traffic Routes require a non-empty domains list.")
    result = []
    for item in value:
        item = _require_keys(item, allowed={"domain", "ports", "port_ranges"}, required={"domain"}, label="domains")
        if not _is_nonempty_string(item["domain"]):
            raise ValueError("Each domains entry must contain a non-empty domain.")
        result.append(
            {
                "domain": item["domain"],
                "ports": _validate_ports(item.get("ports", []), label="domains.ports"),
                "port_ranges": _validate_port_ranges(item.get("port_ranges", []), label="domains.port_ranges"),
            }
        )
    return result


def _ip_version(value: Any, *, parsed: Any, label: str) -> str:
    if type(value) is not str or value not in {"IPV4", "IPV6"}:
        raise ValueError(f"Each {label} entry must use ip_version IPV4 or IPV6.")
    if value != f"IPV{parsed.version}":
        raise ValueError(f"Each {label} ip_version must match its address family.")
    return value


def _validate_ip_addresses(value: Any, *, required: bool) -> List[Dict[str, Any]]:
    if type(value) is not list or (required and not value):
        raise ValueError("IP Traffic Routes require ip_addresses or ip_ranges.")
    result = []
    for item in value:
        item = _require_keys(
            item,
            allowed={"ip_or_subnet", "ip_version", "ports", "port_ranges"},
            required={"ip_or_subnet", "ip_version"},
            label="ip_addresses",
        )
        if not _is_nonempty_string(item["ip_or_subnet"]):
            raise ValueError("Each ip_addresses entry must contain a non-empty ip_or_subnet.")
        try:
            parsed = ipaddress.ip_network(item["ip_or_subnet"], strict=False)
        except ValueError:
            raise ValueError("Each ip_addresses ip_or_subnet must be a valid IP address or subnet.") from None
        result.append(
            {
                "ip_or_subnet": item["ip_or_subnet"],
                "ip_version": _ip_version(item["ip_version"], parsed=parsed, label="ip_addresses"),
                "ports": _validate_ports(item.get("ports", []), label="ip_addresses.ports"),
                "port_ranges": _validate_port_ranges(item.get("port_ranges", []), label="ip_addresses.port_ranges"),
            }
        )
    return result


def _validate_ip_ranges(value: Any, *, required: bool) -> List[Dict[str, Any]]:
    if type(value) is not list or (required and not value):
        raise ValueError("IP Traffic Routes require ip_addresses or ip_ranges.")
    result = []
    for item in value:
        item = _require_keys(
            item,
            allowed={"ip_start", "ip_stop", "ip_version"},
            required={"ip_start", "ip_stop", "ip_version"},
            label="ip_ranges",
        )
        if not _is_nonempty_string(item["ip_start"]) or not _is_nonempty_string(item["ip_stop"]):
            raise ValueError("Each ip_ranges entry must contain non-empty ip_start and ip_stop.")
        try:
            start, stop = ipaddress.ip_address(item["ip_start"]), ipaddress.ip_address(item["ip_stop"])
        except ValueError:
            raise ValueError("Each ip_ranges entry must contain valid IP addresses.") from None
        if start.version != stop.version or int(start) > int(stop):
            raise ValueError("Each ip_ranges entry must be an ordered range in one address family.")
        result.append(
            {
                "ip_start": item["ip_start"],
                "ip_stop": item["ip_stop"],
                "ip_version": _ip_version(item["ip_version"], parsed=start, label="ip_ranges"),
            }
        )
    return result


def _validate_regions(value: Any, *, required: bool) -> List[str]:
    if type(value) is not list or (required and not value) or any(not _is_nonempty_string(item) for item in value):
        raise ValueError("Each regions entry must be a non-empty string.")
    return value


def _validate_target_devices(value: Any, *, omitted: bool) -> List[Dict[str, str]]:
    if omitted:
        return [{"type": "ALL_CLIENTS"}]
    if type(value) is not list or not value:
        raise ValueError("target_devices must be a non-empty list when supplied.")
    result = []
    for item in value:
        item = _require_keys(
            item, allowed={"type", "client_mac", "network_id"}, required={"type"}, label="target_devices"
        )
        kind = item["type"]
        if type(kind) is not str or kind not in {"ALL_CLIENTS", "CLIENT", "NETWORK"}:
            raise ValueError("target_devices type must be ALL_CLIENTS, CLIENT, or NETWORK.")
        if kind == "ALL_CLIENTS":
            if len(value) != 1 or set(item) != {"type"}:
                raise ValueError("ALL_CLIENTS must appear alone without client_mac or network_id.")
            result.append({"type": kind})
        elif kind == "CLIENT":
            client_mac = canonical_mac(item.get("client_mac"))
            if set(item) != {"type", "client_mac"} or client_mac is None:
                raise ValueError("CLIENT target_devices entries require a valid client_mac and no network_id.")
            result.append({"type": kind, "client_mac": client_mac})
        else:
            if set(item) != {"type", "network_id"} or not _is_nonempty_string(item["network_id"]):
                raise ValueError("NETWORK target_devices entries require a non-empty network_id and no client_mac.")
            result.append({"type": kind, "network_id": item["network_id"]})
    return result


def build_traffic_route_create_payload(
    *,
    description: str,
    matching_target: str,
    network_id: str,
    domains: Optional[List[Dict[str, Any]]] = None,
    ip_addresses: Optional[List[Dict[str, Any]]] = None,
    ip_ranges: Optional[List[Dict[str, Any]]] = None,
    regions: Optional[List[str]] = None,
    target_devices: Optional[List[Dict[str, Any]]] = None,
    kill_switch_enabled: bool = False,
    enabled: bool = True,
    next_hop: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate public create fields and return the controller traffic-route payload.

    This is the canonical builder for downstream MCP and typed API integrations,
    so their confirmation paths can share route-scope validation and controller
    defaults.
    """
    if type(matching_target) is not str:
        raise ValueError("matching_target must be a string.")
    target = matching_target.upper()
    if not _is_nonempty_string(description) or len(description) > 128:
        raise ValueError("description is required and must be at most 128 characters.")
    if target not in {"DOMAIN", "IP", "REGION", "INTERNET"}:
        raise ValueError("matching_target must be DOMAIN, IP, REGION, or INTERNET.")
    if not _is_nonempty_string(network_id):
        raise ValueError("network_id is required; a Traffic Route must explicitly name its target network or VPN.")
    for field, value in (("kill_switch_enabled", kill_switch_enabled), ("enabled", enabled)):
        if type(value) is not bool:
            raise ValueError(f"{field} must be a boolean.")
    if next_hop is not None and type(next_hop) is not str:
        raise ValueError("next_hop must be a string.")
    if target == "INTERNET":
        raise ValueError("INTERNET Traffic Routes are blocked to prevent accidental catch-all VPN routing.")
    supplied = {"domains": domains, "ip_addresses": ip_addresses, "ip_ranges": ip_ranges, "regions": regions}
    allowed_selectors = _allowed_selectors(target)
    incompatible = [field for field, value in supplied.items() if field not in allowed_selectors and value is not None]
    if incompatible:
        raise ValueError(f"{target} Traffic Routes do not accept selector field(s): {', '.join(incompatible)}.")
    normalized_domains = _validate_domains(domains, required=target == "DOMAIN") if target == "DOMAIN" else []
    normalized_addresses = _validate_ip_addresses(ip_addresses or [], required=False) if target == "IP" else []
    normalized_ranges = _validate_ip_ranges(ip_ranges or [], required=False) if target == "IP" else []
    if target == "IP" and not (normalized_addresses or normalized_ranges):
        raise ValueError("IP Traffic Routes require ip_addresses or ip_ranges.")
    normalized_regions = _validate_regions(regions, required=True) if target == "REGION" else []
    return {
        "description": description,
        "matching_target": target,
        "network_id": network_id,
        "domains": normalized_domains,
        "target_devices": _validate_target_devices(target_devices, omitted=target_devices is None),
        "kill_switch_enabled": kill_switch_enabled,
        "enabled": enabled,
        "ip_addresses": normalized_addresses,
        "ip_ranges": normalized_ranges,
        "regions": normalized_regions,
        "next_hop": "" if next_hop is None else next_hop,
    }


# ---------------------------------------------------------------------------
# Public factory helpers
# ---------------------------------------------------------------------------


def from_controller(raw: Any) -> TrafficRoute:
    """Build a TrafficRoute from a controller API response dict.

    The controller stores the human-readable name as 'description'.
    """
    # Controller-read data is historical and may predate the current V2 SDK
    # shapes. Write validation is deliberately separate from this projection.
    return TrafficRoute.model_construct(
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
    return build_traffic_route_create_payload(
        description=model.name,
        matching_target=model.matching_target,
        network_id=model.network_id,
        domains=model.domains,
        ip_addresses=model.ip_addresses,
        ip_ranges=model.ip_ranges,
        regions=model.regions,
        target_devices=model.target_devices,
        kill_switch_enabled=False if model.kill_switch_enabled is None else model.kill_switch_enabled,
        enabled=True if model.enabled is None else model.enabled,
        next_hop=model.next_hop,
    )


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to only mutable, recognised keys.

    Read-only fields (id) and unrecognised keys are dropped.
    ``None`` values are dropped; boolean ``False`` is preserved.
    Maps 'name' → 'description' for controller compatibility.
    """
    # All mutable fields, including replacement target lists, share one
    # canonical allowlist for MCP and API update translation.
    result = {k: v for k, v in fields.items() if k in MUTABLE_FIELDS and v is not None}
    # Map name → description for controller compatibility
    if "name" in result:
        result["description"] = result.pop("name")
    return result


def validate_update(
    fields: Dict[str, Any],
    *,
    matching_target: Any,
    current_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate submitted replacements without parsing legacy route values.

    ``current_fields`` is used only to retain an unsupplied non-empty IP
    selector while a caller clears its sibling. Its contents are not parsed or
    normalized, so historical controller data remains permissive.
    """
    if type(fields) is not dict or not fields:
        raise ValueError("Traffic Route update data cannot be empty.")
    immutable = sorted(set(fields) & READ_ONLY_FIELDS)
    if immutable:
        raise ValueError(f"Traffic Route field(s) are immutable: {', '.join(immutable)}.")
    unknown = sorted(set(fields) - _UPDATE_FIELDS)
    if unknown:
        raise ValueError(f"Unknown Traffic Route field(s): {', '.join(unknown)}.")

    for field in ("enabled", "kill_switch_enabled"):
        if field in fields and type(fields[field]) is not bool:
            raise ValueError(f"{field} must be a boolean.")
    if "name" in fields and (not _is_nonempty_string(fields["name"]) or len(fields["name"]) > 128):
        raise ValueError("name must be a non-empty string with at most 128 characters.")
    if "next_hop" in fields and type(fields["next_hop"]) is not str:
        raise ValueError("next_hop must be a string.")

    selector_updates = set(fields) & _SELECTOR_FIELDS
    target = matching_target.upper() if type(matching_target) is str else None
    if target == "INTERNET" and not selector_updates:
        unsafe_fields = set(fields) - {"name", "enabled"}
        if fields.get("enabled") is True:
            unsafe_fields.add("enabled")
        if unsafe_fields:
            raise ValueError(
                "INTERNET Traffic Routes may only be renamed or disabled to prevent accidental catch-all VPN routing."
            )
    if selector_updates:
        if target not in {"DOMAIN", "IP", "REGION"}:
            raise ValueError("Current Traffic Route matching_target is not safe for replacement updates.")
        allowed_selectors = _allowed_selectors(target)
        incompatible = sorted(selector_updates - allowed_selectors)
        if incompatible:
            raise ValueError(f"{target} Traffic Routes do not accept selector field(s): {', '.join(incompatible)}.")
    result: Dict[str, Any] = {}
    for field in ("enabled", "kill_switch_enabled", "next_hop"):
        if field in fields:
            result[field] = fields[field]
    if "name" in fields:
        result["description"] = fields["name"]
    if "target_devices" in fields:
        result["target_devices"] = _validate_target_devices(fields["target_devices"], omitted=False)
    if "domains" in fields:
        result["domains"] = _validate_domains(fields["domains"], required=True)
    if "ip_addresses" in fields:
        result["ip_addresses"] = _validate_ip_addresses(fields["ip_addresses"], required=False)
    if "ip_ranges" in fields:
        result["ip_ranges"] = _validate_ip_ranges(fields["ip_ranges"], required=False)
    if target == "IP" and selector_updates:
        existing = current_fields if type(current_fields) is dict else {}
        resulting_addresses = result.get("ip_addresses", existing.get("ip_addresses"))
        resulting_ranges = result.get("ip_ranges", existing.get("ip_ranges"))
        if not (_is_nonempty_list(resulting_addresses) or _is_nonempty_list(resulting_ranges)):
            raise ValueError("IP Traffic Routes require ip_addresses or ip_ranges.")
    if "regions" in fields:
        result["regions"] = _validate_regions(fields["regions"], required=True)
    return result
