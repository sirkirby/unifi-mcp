"""Shared field models for Network VPN clients and servers.

Mirrors the Strawberry types in
``unifi_api.graphql.types.network.vpn``:

- ``VpnClient`` — list_vpn_clients + get_vpn_client_details + create/update
- ``VpnServer`` — server reads plus the focused alternate-address update

Factory helpers:
- ``from_controller``      — normalise the raw controller dict → VpnClient or VpnServer
- ``to_controller_create`` — translate a VpnClient → create payload
- ``to_controller_update`` — filter a partial dict to mutable keys only

``MUTABLE_FIELDS`` and per-class variants drive the cross-layer symmetry test.
"""

from __future__ import annotations

import re
from ipaddress import IPv4Address
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

ALTERNATE_ADDRESS_KEYS = {
    "alternate_address_enabled": "vpn_client_configuration_remote_ip_override_enabled",
    "alternate_address": "vpn_client_configuration_remote_ip_override",
}


class VpnAlternateAddressError(ValueError):
    """Locally authored, fixed public error; never wrap controller exception text."""


class VpnAlternateAddressUpdate(BaseModel):
    """Strict partial update; omitted fields are preserved, explicit null is invalid."""

    model_config = ConfigDict(
        extra="forbid", strict=True, hide_input_in_errors=True, json_schema_extra={"minProperties": 1}
    )

    alternate_address_enabled: bool | SkipJsonSchema[None] = Field(
        default=None, description="Advertise the alternate address"
    )
    alternate_address: str | SkipJsonSchema[None] = Field(
        default=None, description="Hostname or IPv4 address, without port or URI"
    )

    @model_validator(mode="after")
    def require_fields(self) -> VpnAlternateAddressUpdate:
        if not self.model_fields_set:
            raise ValueError("Supply at least one alternate-address field")
        return self

    @field_validator("alternate_address_enabled", "alternate_address")
    @classmethod
    def not_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Alternate-address fields cannot be null")
        return value

    @field_validator("alternate_address")
    @classmethod
    def valid_address(cls, value: str) -> str:
        try:
            IPv4Address(value)
            return value
        except ValueError:
            pass
        # Reject malformed numeric addresses rather than treating them as hostnames.
        labels = value.split(".")
        if (
            not value
            or len(value) > 253
            or re.fullmatch(r"[0-9.]+", value)
            or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in labels)
        ):
            raise ValueError("Alternate address must be a hostname or IPv4 address")
        return value


class VpnAlternateAddressToolInput(BaseModel):
    """Complete tool schema used by both MCP registration and the API catalog."""

    model_config = ConfigDict(extra="forbid", strict=True)
    server_id: str = Field(description="VPN server networkconf _id from unifi_list_vpn_servers")
    update_data: VpnAlternateAddressUpdate
    confirm: bool = False


def vpn_alternate_address_input_schema(model_type: type[BaseModel] = VpnAlternateAddressUpdate) -> Dict[str, Any]:
    """Inline model definitions for the MCP and manifest schema paths (NAT anchor)."""
    schema = model_type.model_json_schema()
    definitions = schema.pop("$defs", {})

    def inline(node: Any) -> Any:
        if isinstance(node, list):
            return [inline(value) for value in node]
        if isinstance(node, dict):
            if "$ref" in node:
                return inline(definitions[node["$ref"].removeprefix("#/$defs/")])
            return {key: inline(value) for key, value in node.items() if not (key == "default" and value is None)}
        return node

    return inline(schema)


def validate_alternate_address_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Return canonical partial fields without exposing submitted values in errors."""
    if isinstance(fields, dict) and not fields:
        raise VpnAlternateAddressError(
            "Supply at least one alternate-address field: alternate_address_enabled or alternate_address"
        )
    try:
        return VpnAlternateAddressUpdate.model_validate(fields).model_dump(exclude_unset=True)
    except ValidationError:
        raise VpnAlternateAddressError(
            "Invalid VPN alternate-address update: use only alternate_address_enabled (boolean) "
            "and alternate_address (hostname or IPv4); null values are not allowed"
        ) from None


def alternate_address_to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Translate only the two verified controller keys."""
    return {ALTERNATE_ADDRESS_KEYS[key]: value for key, value in validate_alternate_address_update(fields).items()}


class VpnAlternateAddressView(BaseModel):
    """Public projection for previews/results; never contains a raw VPN configuration."""

    alternate_address_enabled: bool | None = None
    alternate_address: str | None = None


def alternate_address_view(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Preserve absent/invalid read values as unknown, without boolean coercion."""
    enabled = raw.get(ALTERNATE_ADDRESS_KEYS["alternate_address_enabled"])
    address = raw.get(ALTERNATE_ADDRESS_KEYS["alternate_address"])
    return VpnAlternateAddressView(
        alternate_address_enabled=enabled if type(enabled) is bool else None,
        alternate_address=address if isinstance(address, str) else None,
    ).model_dump()


VPN_NETWORK_PURPOSES: frozenset[str] = frozenset({"site-vpn", "remote-user-vpn", "vpn-client", "vpn-server"})


def is_vpn_network(network: Dict[str, Any]) -> bool:
    """Return whether a networkconf record represents any VPN configuration."""
    purpose = str(network.get("purpose") or "").strip().casefold()
    vpn_type = str(network.get("vpn_type") or "").strip().casefold()
    return (
        purpose in VPN_NETWORK_PURPOSES
        or purpose.startswith("vpn")
        or "vpn" in vpn_type
        or "wireguard" in vpn_type
        or "openvpn" in vpn_type
    )


# ---------------------------------------------------------------------------
# VpnClient — mutable (create + update)
# ---------------------------------------------------------------------------


class VpnClient(BaseModel):
    """Canonical VPN client profile model (outbound tunnel, mutable)."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="VPN client UUID (assigned by controller)",
        json_schema_extra={"mutable": False},
    )

    # --- mutable ---
    name: Optional[str] = Field(
        default=None,
        description="Name of the VPN client profile",
    )
    enabled: Optional[bool] = Field(
        default=None,
        description="Whether this VPN client connection is active",
    )
    type: Optional[str] = Field(
        default=None,
        description="VPN type: wireguard, openvpn, l2tp, etc. (controller field: vpn_type / purpose)",
    )
    server_address: Optional[str] = Field(
        default=None,
        description="VPN server address (wireguard peer endpoint, openvpn remote host)",
    )


# ---------------------------------------------------------------------------
# VpnServer — alternate address is mutable through the focused update only
# ---------------------------------------------------------------------------


class VpnServer(BaseModel):
    """Canonical VPN server shape (inbound tunnel)."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="VPN server UUID (assigned by controller)",
        json_schema_extra={"mutable": False},
    )
    name: Optional[str] = Field(
        default=None,
        description="Name of the VPN server profile",
        json_schema_extra={"mutable": False},
    )
    type: Optional[str] = Field(
        default=None,
        description="VPN type: wireguard, openvpn, l2tp, etc.",
        json_schema_extra={"mutable": False},
    )
    enabled: Optional[bool] = Field(
        default=None,
        description="Whether the VPN server is active",
        json_schema_extra={"mutable": False},
    )
    listen_port: Optional[int] = Field(
        default=None,
        description="Listen port for the VPN server",
        json_schema_extra={"mutable": False},
    )
    allowed_subnets: Optional[List[str]] = Field(
        default=None,
        description="Subnets routed through the VPN server",
        json_schema_extra={"mutable": False},
    )
    alternate_address_enabled: Optional[bool] = Field(default=None, description="Advertise the alternate address")
    alternate_address: Optional[str] = Field(default=None, description="Alternate hostname or IPv4 address for clients")


# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------

VPNCLIENT_MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in VpnClient.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

VPNCLIENT_READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in VpnClient.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True) is False
)

VPNSERVER_MUTABLE_FIELDS: frozenset[str] = frozenset(ALTERNATE_ADDRESS_KEYS)

VPNSERVER_READ_ONLY_FIELDS: frozenset[str] = frozenset(VpnServer.model_fields) - VPNSERVER_MUTABLE_FIELDS

# Module-level alias: point to VpnClient's mutable fields for generic usage
MUTABLE_FIELDS = VPNCLIENT_MUTABLE_FIELDS


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


def _vpn_server_address(obj: Any) -> Optional[str]:
    return (
        _get(obj, "wireguard_client_peer_endpoint")
        or _get(obj, "openvpn_remote_host")
        or _get(obj, "remote_address")
        or _get(obj, "server_address")
    )


def _vpn_listen_port(obj: Any) -> Optional[int]:
    return (
        _get(obj, "wireguard_server_listen_port")
        or _get(obj, "openvpn_server_listen_port")
        or _get(obj, "vpn_listen_port")
        or _get(obj, "listen_port")
    )


def _vpn_allowed_subnets(obj: Any) -> Optional[List[str]]:
    val = (
        _get(obj, "wireguard_server_subnet")
        or _get(obj, "openvpn_server_subnet")
        or _get(obj, "ip_subnet")
        or _get(obj, "allowed_subnets")
    )
    if val is None:
        return None
    if isinstance(val, list):
        return list(val)
    return [str(val)]


# ---------------------------------------------------------------------------
# Public factory helpers — VpnClient
# ---------------------------------------------------------------------------


def from_controller(raw: Any) -> VpnClient:
    """Build a VpnClient from a controller API response dict."""
    return VpnClient(
        id=_get(raw, "_id") or _get(raw, "id"),
        name=_get(raw, "name"),
        enabled=_get(raw, "enabled"),
        type=_get(raw, "vpn_type") or _get(raw, "purpose"),
        server_address=_vpn_server_address(raw),
    )


def vpn_server_from_controller(raw: Any) -> VpnServer:
    """Build a VpnServer from a controller API response dict."""
    return VpnServer(
        id=_get(raw, "_id") or _get(raw, "id"),
        name=_get(raw, "name"),
        type=_get(raw, "vpn_type") or _get(raw, "purpose"),
        enabled=_get(raw, "enabled"),
        listen_port=_vpn_listen_port(raw),
        allowed_subnets=_vpn_allowed_subnets(raw),
        **alternate_address_view({key: _get(raw, key) for key in ALTERNATE_ADDRESS_KEYS.values()}),
    )


def to_controller_create(model: VpnClient) -> Dict[str, Any]:
    """Produce a controller create payload from a VpnClient model."""
    payload: Dict[str, Any] = {}
    for field_name in VPNCLIENT_MUTABLE_FIELDS:
        value = getattr(model, field_name, None)
        if value is not None:
            payload[field_name] = value
    # Map type → vpn_type for controller compatibility
    if "type" in payload:
        payload["vpn_type"] = payload.pop("type")
    # Map server_address → wireguard_client_peer_endpoint (or let manager decide)
    if "server_address" in payload:
        payload["server_address"] = payload["server_address"]
    return payload


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to only mutable, recognised keys.

    Read-only fields and unrecognised keys are dropped.
    ``None`` values are dropped; boolean ``False`` is preserved.
    """
    result = {k: v for k, v in fields.items() if k in VPNCLIENT_MUTABLE_FIELDS and v is not None}
    # Map type → vpn_type for controller compatibility
    if "type" in result:
        result["vpn_type"] = result.pop("type")
    return result
