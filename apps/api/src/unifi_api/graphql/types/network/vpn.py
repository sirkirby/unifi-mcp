"""Strawberry types for network/vpn (VPN clients + servers).

Phase 6 PR2 Task 21 migration target. Two read shapes that used to live in
``unifi_api.serializers.network.vpn``:

- ``VpnClient`` — list_vpn_clients + get_vpn_client_details
- ``VpnServer`` — list_vpn_servers + get_vpn_server_details

VPN configurations live inside the ``networkconf`` API and are filtered by
purpose / vpn_type. The common fields surfaced here mirror the manager
output without re-classifying — we expose ``vpn_type`` directly as ``type``
so callers can disambiguate wireguard vs openvpn vs l2tp.

Each type's ``from_manager_output(raw)`` classmethod replaces the dict-shaping
logic that used to live in serializers/network/vpn.py. ``to_dict()``
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


def _vpn_server_address(obj: Any) -> str | None:
    # Wireguard client peer endpoint, openvpn remote, or generic server.
    return (
        _get(obj, "wireguard_client_peer_endpoint")
        or _get(obj, "openvpn_remote_host")
        or _get(obj, "remote_address")
        or _get(obj, "server_address")
    )


def _vpn_listen_port(obj: Any) -> int | None:
    return (
        _get(obj, "wireguard_server_listen_port")
        or _get(obj, "openvpn_server_listen_port")
        or _get(obj, "vpn_listen_port")
        or _get(obj, "listen_port")
    )


def _vpn_allowed_subnets(obj: Any) -> list[str] | None:
    # Wireguard server uses ``wireguard_server_subnet``; openvpn uses
    # ``openvpn_server_subnet`` or ``ip_subnet``.
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


@strawberry.type(description="A configured VPN client (outbound tunnel).")
class VpnClient:
    id: strawberry.ID | None
    name: str | None
    type: str | None
    enabled: bool
    server_address: str | None
    last_handshake: int | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "type", "enabled", "server_address"],
            "sort_default": "name:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "VpnClient":
        return cls(
            id=_get(obj, "_id") or _get(obj, "id"),
            name=_get(obj, "name"),
            type=_get(obj, "vpn_type") or _get(obj, "purpose"),
            enabled=bool(_get(obj, "enabled", False)),
            server_address=_vpn_server_address(obj),
            last_handshake=_get(obj, "wireguard_client_last_handshake") or _get(obj, "last_handshake"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@strawberry.type(description="A configured VPN server (inbound tunnel).")
class VpnServer:
    id: strawberry.ID | None
    name: str | None
    type: str | None
    enabled: bool
    listen_port: int | None
    allowed_subnets: list[str] | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "type", "enabled", "listen_port"],
            "sort_default": "name:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "VpnServer":
        return cls(
            id=_get(obj, "_id") or _get(obj, "id"),
            name=_get(obj, "name"),
            type=_get(obj, "vpn_type") or _get(obj, "purpose"),
            enabled=bool(_get(obj, "enabled", False)),
            listen_port=_vpn_listen_port(obj),
            allowed_subnets=_vpn_allowed_subnets(obj),
        )

    def to_dict(self) -> dict:
        return asdict(self)
