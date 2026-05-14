"""Shared field model for Network port-forward rules.

Mirrors the Strawberry type in
``unifi_api.graphql.types.network.port_forward`` (class ``PortForward``).

- ``PortForward`` — list_port_forwards + get_port_forward +
  create_port_forward + create_simple_port_forward + toggle_port_forward

Factory helpers:
- ``from_controller``      — normalise the raw controller dict → PortForward
- ``to_controller_create`` — translate a PortForward → create payload
- ``to_controller_update`` — filter a partial dict to mutable keys only

``MUTABLE_FIELDS`` drives the cross-layer symmetry test: the Strawberry
type must expose every field listed here.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Pydantic domain model
# ---------------------------------------------------------------------------


class PortForward(BaseModel):
    """Canonical port-forward rule model (read + mutable create/update fields)."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="Port-forward rule UUID (assigned by controller)",
        json_schema_extra={"mutable": False},
    )
    site_id: Optional[str] = Field(
        default=None,
        description="Site ID this rule belongs to",
        json_schema_extra={"mutable": False},
    )

    # --- mutable (accepted by create and update) ---
    name: Optional[str] = Field(
        default=None,
        description="Descriptive name for the port-forward rule",
    )
    enabled: Optional[bool] = Field(
        default=None,
        description="Whether the rule is enabled",
    )
    # Protocol field name: the controller stores 'proto' but the schema uses
    # 'protocol' for user input. We keep 'fwd_protocol' to match the Strawberry
    # type, and expose 'protocol' as an alias accepted on input.
    fwd_protocol: Optional[str] = Field(
        default=None,
        description="Protocol: tcp, udp, tcp_udp (controller uses 'proto' field)",
    )
    dst_port: Optional[str] = Field(
        default=None,
        description="External (destination) port or range",
    )
    fwd_port: Optional[str] = Field(
        default=None,
        description="Internal (forward-to) port or range",
    )
    fwd_ip: Optional[str] = Field(
        default=None,
        description="Internal IP address to forward to",
    )
    src: Optional[str] = Field(
        default=None,
        description="Source IP/CIDR to restrict the rule to (empty = any)",
    )
    log: Optional[bool] = Field(
        default=None,
        description="Whether to log matching traffic",
    )


# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------

MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in PortForward.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in PortForward.model_fields.items()
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


def from_controller(raw: Any) -> PortForward:
    """Build a PortForward from a controller API response dict."""
    # Controller uses 'proto' for protocol; Strawberry uses 'fwd_protocol'
    protocol = _get(raw, "fwd_protocol") or _get(raw, "proto") or _get(raw, "protocol")
    return PortForward(
        id=_get(raw, "_id") or _get(raw, "id"),
        site_id=_get(raw, "site_id"),
        name=_get(raw, "name"),
        enabled=_get(raw, "enabled"),
        fwd_protocol=protocol,
        dst_port=_get(raw, "dst_port"),
        fwd_port=_get(raw, "fwd_port"),
        fwd_ip=_get(raw, "fwd_ip") or _get(raw, "fwd"),
        src=_get(raw, "src"),
        log=_get(raw, "log"),
    )


def to_controller_create(model: PortForward) -> Dict[str, Any]:
    """Produce a controller create payload from a PortForward model."""
    payload: Dict[str, Any] = {}
    for field_name in MUTABLE_FIELDS:
        value = getattr(model, field_name, None)
        if value is not None:
            payload[field_name] = value
    # Map fwd_protocol → proto for controller compatibility
    if "fwd_protocol" in payload:
        payload["proto"] = payload.pop("fwd_protocol")
    return payload


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to only mutable, recognised keys.

    Read-only fields and unrecognised keys are dropped.
    ``None`` values are dropped; boolean ``False`` is preserved.
    """
    return {k: v for k, v in fields.items() if k in MUTABLE_FIELDS and v is not None}
