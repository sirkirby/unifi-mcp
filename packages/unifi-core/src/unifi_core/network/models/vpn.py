"""Shared field models for Network VPN clients and servers.

Mirrors the Strawberry types in
``unifi_api.graphql.types.network.vpn``:

- ``VpnClient`` — list_vpn_clients + get_vpn_client_details + create/update
- ``VpnServer`` — list_vpn_servers + get_vpn_server_details (read-only)

Factory helpers:
- ``from_controller``      — normalise the raw controller dict → VpnClient or VpnServer
- ``to_controller_create`` — translate a VpnClient → create payload
- ``to_controller_update`` — filter a partial dict to mutable keys only

``MUTABLE_FIELDS`` and per-class variants drive the cross-layer symmetry test.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

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
# VpnServer — read-only
# ---------------------------------------------------------------------------


class VpnServer(BaseModel):
    """Canonical VPN server shape (inbound tunnel, read-only)."""

    # --- read-only (all fields) ---
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

VPNSERVER_MUTABLE_FIELDS: frozenset[str] = frozenset()  # all read-only

VPNSERVER_READ_ONLY_FIELDS: frozenset[str] = frozenset(VpnServer.model_fields.keys())

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
