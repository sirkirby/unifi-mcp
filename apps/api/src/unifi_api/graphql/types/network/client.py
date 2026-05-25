"""Strawberry types for network/clients.

Canonical migration target for Phase 6 PR2:
- ``Client``        — list_clients + get_client_details (full client shape)
- ``BlockedClient`` — list_blocked_clients (minimal blocked-list shape)
- ``ClientLookup``  — lookup_by_ip (online-status check shape)

Each type's ``from_manager_output(raw)`` classmethod replaces the dict-shaping
logic that used to live in serializers/network/clients.py. ``to_dict()``
exposes the same dict contract the REST routes return today.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Annotated, Any

import strawberry
from strawberry.types import Info

if TYPE_CHECKING:
    from unifi_api.graphql.types.network.device import Device


def _iso(ts: int | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


@strawberry.type(description="A client device on the UniFi Network controller.")
class Client:
    mac: strawberry.ID | None
    ip: str | None
    hostname: str | None
    name: str | None
    is_wired: bool
    is_guest: bool
    status: str
    last_seen: str | None
    first_seen: str | None
    note: str | None
    usergroup_id: str | None

    # Context for relationship edges — NOT in SDL, NOT in to_dict().
    # Set by the resolver after construction so edge resolvers can look up
    # related resources via the request cache.
    _controller_id: strawberry.Private[str | None] = None
    _site: strawberry.Private[str | None] = None
    _ap_mac: strawberry.Private[str | None] = None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "mac",
            "display_columns": ["hostname", "ip", "status", "last_seen"],
            "sort_default": "last_seen:desc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "Client":
        raw = getattr(obj, "raw", obj if isinstance(obj, dict) else {})
        return cls(
            mac=raw.get("mac"),
            ip=raw.get("last_ip") or raw.get("ip"),
            hostname=raw.get("hostname") or None,
            name=raw.get("name") or None,
            is_wired=bool(raw.get("is_wired", False)),
            is_guest=bool(raw.get("is_guest", False)),
            status="online" if raw.get("is_online") else "offline",
            last_seen=_iso(raw.get("last_seen")),
            first_seen=_iso(raw.get("first_seen")),
            note=raw.get("note") or None,
            usergroup_id=raw.get("usergroup_id") or None,
            _ap_mac=raw.get("ap_mac"),
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: v for k, v in out.items() if not k.startswith("_") and not callable(v)}

    @strawberry.field(description="The AP or switch this client connects through.")
    async def device(
        self,
        info: Info,
    ) -> Annotated["Device", strawberry.lazy("unifi_api.graphql.types.network.device")] | None:
        """Resolves to the parent AP/switch — uses the request cache to avoid N+1."""
        # Forward references to avoid circular imports.
        from unifi_api.graphql.resolvers.network import _fetch_devices
        from unifi_api.graphql.types.network.device import Device

        if not self._controller_id or not self._ap_mac:
            return None
        site = self._site or "default"
        raw_devices = await _fetch_devices(info.context, self._controller_id, site)
        for d in raw_devices:
            if isinstance(d, dict):
                d_mac = d.get("mac")
            else:
                raw = getattr(d, "raw", None)
                d_mac = raw.get("mac") if isinstance(raw, dict) else getattr(d, "mac", None)
            if d_mac == self._ap_mac:
                instance = Device.from_manager_output(d)
                instance._controller_id = self._controller_id
                instance._site = site
                return instance
        return None


@strawberry.type(description="A client currently blocked on the UniFi Network controller.")
class BlockedClient:
    mac: strawberry.ID | None
    hostname: str | None
    name: str | None
    last_seen: str | None
    blocked: bool

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "mac",
            "display_columns": ["mac", "hostname", "last_seen"],
            "sort_default": "last_seen:desc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "BlockedClient":
        return cls(
            mac=_get(obj, "mac"),
            hostname=_get(obj, "hostname") or None,
            name=_get(obj, "name") or None,
            last_seen=_iso(_get(obj, "last_seen")),
            blocked=bool(_get(obj, "blocked", True)),
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: v for k, v in out.items() if not k.startswith("_") and not callable(v)}


@strawberry.type(description="Result of a by-IP client lookup — online presence + last seen.")
class ClientLookup:
    mac: strawberry.ID | None
    ip: str | None
    hostname: str | None
    name: str | None
    is_online: bool
    last_seen: str | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind, "primary_key": "mac"}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "ClientLookup":
        return cls(
            mac=_get(obj, "mac"),
            ip=_get(obj, "last_ip") or _get(obj, "ip"),
            hostname=_get(obj, "hostname") or None,
            name=_get(obj, "name") or None,
            is_online=bool(_get(obj, "is_online", False)),
            last_seen=_iso(_get(obj, "last_seen")),
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: v for k, v in out.items() if not k.startswith("_") and not callable(v)}
