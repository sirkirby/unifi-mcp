"""Shared field models for Network client resources.

Mirrors the Strawberry types in
``unifi_api.graphql.types.network.client``:

- ``Client``        — list_clients + get_client_details
- ``BlockedClient`` — list_blocked_clients
- ``ClientLookup``  — lookup_by_ip

All three classes are read-only (no update/create tools use these models
for validation). The models exist to provide typed output shaping and
cross-layer symmetry test coverage.

Factory helpers:
- ``client_from_controller``         — normalise raw → Client
- ``blocked_client_from_controller`` — normalise raw → BlockedClient
- ``client_lookup_from_controller``  — normalise raw → ClientLookup

Per-class MUTABLE_FIELDS constants drive the cross-layer symmetry test.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


def _stringify_dt(ts: Any) -> Optional[str]:
    """Convert a Unix epoch int/float to ISO 8601 UTC string."""
    if ts is None:
        return None
    if isinstance(ts, str):
        return ts
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class Client(BaseModel):
    """Canonical client model (list + detail output shape)."""

    mac: Optional[str] = Field(
        default=None,
        description="Client MAC address",
        json_schema_extra={"mutable": False},
    )
    ip: Optional[str] = Field(
        default=None,
        description="Current IP address",
        json_schema_extra={"mutable": False},
    )
    hostname: Optional[str] = Field(
        default=None,
        description="DHCP-reported hostname from the device itself",
        json_schema_extra={"mutable": False},
    )
    name: Optional[str] = Field(
        default=None,
        description="User-assigned alias set in the UniFi console (preferred for display)",
        json_schema_extra={"mutable": False},
    )
    is_wired: bool = Field(
        default=False,
        description="True when client is connected via Ethernet",
        json_schema_extra={"mutable": False},
    )
    is_guest: bool = Field(
        default=False,
        description="True when client is on a guest network",
        json_schema_extra={"mutable": False},
    )
    status: str = Field(
        default="offline",
        description="'online' or 'offline'",
        json_schema_extra={"mutable": False},
    )
    last_seen: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp of last activity",
        json_schema_extra={"mutable": False},
    )
    first_seen: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp of first association",
        json_schema_extra={"mutable": False},
    )
    note: Optional[str] = Field(
        default=None,
        description="Optional note attached to the client",
        json_schema_extra={"mutable": False},
    )
    usergroup_id: Optional[str] = Field(
        default=None,
        description="User-group ID the client belongs to",
        json_schema_extra={"mutable": False},
    )


CLIENT_MUTABLE_FIELDS: frozenset[str] = frozenset()
CLIENT_READ_ONLY_FIELDS: frozenset[str] = frozenset(Client.model_fields.keys())


def client_from_controller(obj: Any) -> Client:
    """Build a Client from a controller API response dict or aiounifi object."""
    raw: dict = {}
    if isinstance(obj, dict):
        raw = obj
    else:
        r = getattr(obj, "raw", None)
        if isinstance(r, dict):
            raw = r
    return Client(
        mac=raw.get("mac"),
        ip=raw.get("last_ip") or raw.get("ip"),
        hostname=raw.get("hostname") or None,
        name=raw.get("name") or None,
        is_wired=bool(raw.get("is_wired", False)),
        is_guest=bool(raw.get("is_guest", False)),
        status="online" if raw.get("is_online") else "offline",
        last_seen=_stringify_dt(raw.get("last_seen")),
        first_seen=_stringify_dt(raw.get("first_seen")),
        note=raw.get("note") or None,
        usergroup_id=raw.get("usergroup_id") or None,
    )


# ---------------------------------------------------------------------------
# BlockedClient
# ---------------------------------------------------------------------------


class BlockedClient(BaseModel):
    """Minimal blocked-client list shape."""

    mac: Optional[str] = Field(
        default=None,
        description="Client MAC address",
        json_schema_extra={"mutable": False},
    )
    hostname: Optional[str] = Field(
        default=None,
        description="DHCP-reported hostname from the device itself",
        json_schema_extra={"mutable": False},
    )
    name: Optional[str] = Field(
        default=None,
        description="User-assigned alias set in the UniFi console (preferred for display)",
        json_schema_extra={"mutable": False},
    )
    last_seen: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp of last activity",
        json_schema_extra={"mutable": False},
    )
    blocked: bool = Field(
        default=True,
        description="True when the client is actively blocked",
        json_schema_extra={"mutable": False},
    )


BLOCKEDCLIENT_MUTABLE_FIELDS: frozenset[str] = frozenset()
BLOCKEDCLIENT_READ_ONLY_FIELDS: frozenset[str] = frozenset(BlockedClient.model_fields.keys())


def blocked_client_from_controller(obj: Any) -> BlockedClient:
    """Build a BlockedClient from a controller API response."""
    return BlockedClient(
        mac=_get(obj, "mac"),
        hostname=_get(obj, "hostname") or None,
        name=_get(obj, "name") or None,
        last_seen=_stringify_dt(_get(obj, "last_seen")),
        blocked=bool(_get(obj, "blocked", True)),
    )


# ---------------------------------------------------------------------------
# ClientLookup
# ---------------------------------------------------------------------------


class ClientLookup(BaseModel):
    """Online-presence check shape returned by lookup_by_ip."""

    mac: Optional[str] = Field(
        default=None,
        description="Client MAC address",
        json_schema_extra={"mutable": False},
    )
    ip: Optional[str] = Field(
        default=None,
        description="IP address that was looked up",
        json_schema_extra={"mutable": False},
    )
    hostname: Optional[str] = Field(
        default=None,
        description="DHCP-reported hostname from the device itself",
        json_schema_extra={"mutable": False},
    )
    name: Optional[str] = Field(
        default=None,
        description="User-assigned alias set in the UniFi console (preferred for display)",
        json_schema_extra={"mutable": False},
    )
    is_online: bool = Field(
        default=False,
        description="True when the client is currently online",
        json_schema_extra={"mutable": False},
    )
    last_seen: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp of last activity",
        json_schema_extra={"mutable": False},
    )


CLIENTLOOKUP_MUTABLE_FIELDS: frozenset[str] = frozenset()
CLIENTLOOKUP_READ_ONLY_FIELDS: frozenset[str] = frozenset(ClientLookup.model_fields.keys())

# Module-level alias (symmetry test fallback)
MUTABLE_FIELDS = CLIENT_MUTABLE_FIELDS


def client_lookup_from_controller(obj: Any) -> ClientLookup:
    """Build a ClientLookup from a controller API response."""
    return ClientLookup(
        mac=_get(obj, "mac"),
        ip=_get(obj, "last_ip") or _get(obj, "ip"),
        hostname=_get(obj, "hostname") or None,
        name=_get(obj, "name") or None,
        is_online=bool(_get(obj, "is_online", False)),
        last_seen=_stringify_dt(_get(obj, "last_seen")),
    )
