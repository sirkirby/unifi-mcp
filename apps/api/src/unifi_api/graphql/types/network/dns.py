"""Strawberry types for network/dns (static DNS records).

Phase 6 PR2 Task 21 migration target. One type per read serializer that used
to live in ``unifi_api.serializers.network.dns``:

- ``DnsRecord`` — list_dns_records + get_dns_record_details

UniFi's V2 ``/static-dns`` endpoint stores hostname under ``key`` and the
resolved value under ``value``; we surface them as ``hostname`` / ``ip`` so
the hint-shape matches caller expectations across record types.

Each type's ``from_manager_output(raw)`` classmethod replaces the dict-shaping
logic that used to live in serializers/network/dns.py. ``to_dict()``
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


@strawberry.type(description="A static DNS record served by the controller.")
class DnsRecord:
    id: strawberry.ID | None
    hostname: str | None
    ip: str | None
    type: str | None
    ttl: int | None
    enabled: bool
    key: str | None
    value: str | None
    record_type: str | None
    port: int | None
    priority: int | None
    weight: int | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["hostname", "type", "ip", "ttl", "enabled"],
            "sort_default": "hostname:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "DnsRecord":
        key = _get(obj, "key") or _get(obj, "hostname")
        value = _get(obj, "value") or _get(obj, "ip")
        record_type = _get(obj, "record_type") or _get(obj, "type")
        return cls(
            id=_get(obj, "_id") or _get(obj, "id"),
            hostname=key,
            ip=value,
            type=record_type,
            ttl=_get(obj, "ttl"),
            enabled=bool(_get(obj, "enabled", True)),
            key=key,
            value=value,
            record_type=record_type,
            port=_get(obj, "port"),
            priority=_get(obj, "priority"),
            weight=_get(obj, "weight"),
        )

    def to_dict(self) -> dict:
        return asdict(self)
