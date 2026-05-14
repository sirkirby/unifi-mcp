"""Shared field model for Network QoS rate-limit rules.

Mirrors the Strawberry type in
``unifi_api.graphql.types.network.qos`` (class ``QosRule``).

- ``QosRule`` — list_qos_rules + get_qos_rule_details +
  create_qos_rule + create_simple_qos_rule + toggle_qos_rule_enabled

Factory helpers:
- ``from_controller``      — normalise the raw controller dict → QosRule
- ``to_controller_create`` — translate a QosRule → create payload
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


class QosRule(BaseModel):
    """Canonical QoS rate-limit rule model (read + mutable create/update fields)."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="QoS rule UUID (assigned by controller)",
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
        description="Descriptive name for the QoS rule",
    )
    enabled: Optional[bool] = Field(
        default=None,
        description="Whether the rule is enabled",
    )
    interface: Optional[str] = Field(
        default=None,
        description="Network interface the rule applies to (e.g., 'WAN', 'LAN')",
    )
    direction: Optional[str] = Field(
        default=None,
        description="Direction of traffic affected: upload or download",
    )
    bandwidth_limit_kbps: Optional[int] = Field(
        default=None,
        description="Bandwidth limit in Kilobits per second",
    )
    target_ip_address: Optional[str] = Field(
        default=None,
        description="Specific IP address to target",
    )
    target_subnet: Optional[str] = Field(
        default=None,
        description="Subnet (CIDR notation) to target",
    )
    dscp_value: Optional[int] = Field(
        default=None,
        description="DSCP value to match/set (0-63)",
    )
    # Rate fields used by newer V2 API shape (exposed via Strawberry)
    rate_max_down: Optional[int] = Field(
        default=None,
        description="Maximum download rate in kbps (V2 API field)",
    )
    rate_max_up: Optional[int] = Field(
        default=None,
        description="Maximum upload rate in kbps (V2 API field)",
    )
    priority: Optional[int] = Field(
        default=None,
        description="QoS rule priority (V2 API field)",
    )


# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------

MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in QosRule.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in QosRule.model_fields.items()
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


def from_controller(raw: Any) -> QosRule:
    """Build a QosRule from a controller API response dict."""
    return QosRule(
        id=_get(raw, "_id") or _get(raw, "id"),
        site_id=_get(raw, "site_id"),
        name=_get(raw, "name"),
        enabled=_get(raw, "enabled"),
        interface=_get(raw, "interface"),
        direction=_get(raw, "direction"),
        bandwidth_limit_kbps=_get(raw, "bandwidth_limit_kbps"),
        target_ip_address=_get(raw, "target_ip_address"),
        target_subnet=_get(raw, "target_subnet"),
        dscp_value=_get(raw, "dscp_value"),
        rate_max_down=_get(raw, "rate_max_down"),
        rate_max_up=_get(raw, "rate_max_up"),
        priority=_get(raw, "priority"),
    )


def to_controller_create(model: QosRule) -> Dict[str, Any]:
    """Produce a controller create payload from a QosRule model."""
    payload: Dict[str, Any] = {}
    for field_name in MUTABLE_FIELDS:
        value = getattr(model, field_name, None)
        if value is not None:
            payload[field_name] = value
    return payload


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to only mutable, recognised keys.

    Read-only fields and unrecognised keys are dropped.
    ``None`` values are dropped; boolean ``False`` is preserved.
    """
    return {k: v for k, v in fields.items() if k in MUTABLE_FIELDS and v is not None}
