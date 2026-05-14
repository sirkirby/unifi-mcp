"""Shared field model for Network static DNS records (read + create/update).

Mirrors the Strawberry type in
``unifi_api.graphql.types.network.dns``.

- ``DnsRecord`` — list_dns_records + get_dns_record_details +
  create_dns_record + update_dns_record

The controller stores hostname under ``key`` and the resolved value
under ``value``; ``record_type`` holds the DNS type string.  The
Strawberry layer surfaces these as ``hostname`` / ``ip`` / ``type``
for display purposes — those aliases are also captured here.

Factory helpers:
- ``from_controller``      — normalise the raw controller dict → DnsRecord
- ``to_controller_create`` — translate a DnsRecord → create payload
- ``to_controller_update`` — filter a partial dict to mutable keys only

``MUTABLE_FIELDS`` drives the cross-layer symmetry test.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Pydantic domain model
# ---------------------------------------------------------------------------


class DnsRecord(BaseModel):
    """Canonical static DNS record model (read + mutable create/update fields)."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="DNS record UUID (assigned by controller)",
        json_schema_extra={"mutable": False},
    )

    # --- mutable (accepted by create and update) ---
    key: Optional[str] = Field(
        default=None,
        description="Hostname / record name (e.g. 'myhost.example.com')",
    )
    value: Optional[str] = Field(
        default=None,
        description="Record value — IP for A/AAAA, hostname for CNAME, etc.",
    )
    record_type: Optional[str] = Field(
        default=None,
        description="DNS record type: A, AAAA, CNAME, MX, TXT, SRV",
    )
    enabled: Optional[bool] = Field(
        default=None,
        description="Whether the record is active",
    )
    ttl: Optional[int] = Field(
        default=None,
        description="Time to live in seconds (0 = default 300s)",
        ge=0,
    )
    port: Optional[int] = Field(
        default=None,
        description="Port number (for SRV records)",
        ge=0,
    )
    priority: Optional[int] = Field(
        default=None,
        description="Priority (for MX and SRV records, lower = higher priority)",
        ge=0,
    )
    weight: Optional[int] = Field(
        default=None,
        description="Weight (for SRV records)",
        ge=0,
    )


# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------

MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in DnsRecord.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in DnsRecord.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True) is False
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ---------------------------------------------------------------------------
# Public factory helpers
# ---------------------------------------------------------------------------


def from_controller(raw: Any) -> DnsRecord:
    """Build a DnsRecord from a controller API response dict."""
    enabled_raw = _get(raw, "enabled", None)
    enabled = enabled_raw if isinstance(enabled_raw, bool) else None
    return DnsRecord(
        id=_get(raw, "_id") or _get(raw, "id"),
        key=_get(raw, "key") or _get(raw, "hostname"),
        value=_get(raw, "value") or _get(raw, "ip"),
        record_type=_get(raw, "record_type") or _get(raw, "type"),
        enabled=enabled,
        ttl=_get(raw, "ttl"),
        port=_get(raw, "port"),
        priority=_get(raw, "priority"),
        weight=_get(raw, "weight"),
    )


def to_controller_create(model: DnsRecord) -> Dict[str, Any]:
    """Produce a controller create payload from a DnsRecord."""
    payload: Dict[str, Any] = {}
    if model.key is not None:
        payload["key"] = model.key
    if model.value is not None:
        payload["value"] = model.value
    if model.record_type is not None:
        payload["record_type"] = model.record_type
    if model.enabled is not None:
        payload["enabled"] = model.enabled
    if model.ttl is not None:
        payload["ttl"] = model.ttl
    if model.port is not None:
        payload["port"] = model.port
    if model.priority is not None:
        payload["priority"] = model.priority
    if model.weight is not None:
        payload["weight"] = model.weight
    return payload


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to only mutable, recognised keys.

    Read-only fields and unrecognised keys are dropped.
    ``None`` values are dropped; boolean ``False`` is preserved.
    """
    return {k: v for k, v in fields.items() if k in MUTABLE_FIELDS and v is not None}
