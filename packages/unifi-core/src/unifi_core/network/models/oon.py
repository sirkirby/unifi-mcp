"""Shared field model for Network OON (Object-Oriented Network) policies.

Mirrors the Strawberry type in
``unifi_api.graphql.types.network.oon`` (class ``OonPolicy``).

- ``OonPolicy`` — list_oon_policies + get_oon_policy_details +
  create_oon_policy + delete_oon_policy + toggle_oon_policy

Factory helpers:
- ``from_controller``      — normalise the raw controller dict → OonPolicy
- ``to_controller_create`` — translate an OonPolicy → create payload
- ``to_controller_update`` — filter a partial dict to mutable keys only

``MUTABLE_FIELDS`` drives the cross-layer symmetry test: the Strawberry
type must expose every field listed here.

Note: ``qos_enabled`` and ``route_enabled`` are included as explicit
mutable fields to prevent silent-drop bugs (issue #137). The full ``qos``
and ``route`` nested dicts are also mutable.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Pydantic domain model
# ---------------------------------------------------------------------------


class OonPolicy(BaseModel):
    """Canonical OON policy model (read + mutable create/update fields)."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="OON policy UUID (assigned by controller)",
        json_schema_extra={"mutable": False},
    )
    restriction_level: Optional[str] = Field(
        default=None,
        description="Controller-assigned restriction level label (firmware-dependent)",
        json_schema_extra={"mutable": False},
    )

    # --- mutable (accepted by create and update) ---
    name: Optional[str] = Field(
        default=None,
        description="Policy name",
    )
    enabled: Optional[bool] = Field(
        default=None,
        description="Whether the policy is active",
    )
    target_type: Optional[str] = Field(
        default=None,
        description="Target type: CLIENTS or GROUPS",
    )
    targets: Optional[List[Any]] = Field(
        default=None,
        description="List of target MAC addresses or group IDs",
    )
    # OON nested sections
    secure: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Internet access and app blocking configuration",
    )
    qos: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Bandwidth limiting configuration (includes qos_enabled)",
    )
    qos_enabled: Optional[bool] = Field(
        default=None,
        description="Whether QoS is enabled (top-level flag, mirrors qos.enabled)",
    )
    route: Optional[Dict[str, Any]] = Field(
        default=None,
        description="VPN routing configuration (includes route_enabled)",
    )
    route_enabled: Optional[bool] = Field(
        default=None,
        description="Whether route is enabled (top-level flag, mirrors route.enabled)",
    )
    applies_to: Optional[List[Any]] = Field(
        default=None,
        description="Alias for targets — list of client/group matchers",
    )


# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------

MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in OonPolicy.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in OonPolicy.model_fields.items()
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


def from_controller(raw: Any) -> OonPolicy:
    """Build an OonPolicy from a controller API response dict."""
    qos_block = _get(raw, "qos") or {}
    route_block = _get(raw, "route") or {}
    targets = _get(raw, "targets") or _get(raw, "applies_to") or []
    return OonPolicy(
        id=_get(raw, "_id") or _get(raw, "id"),
        restriction_level=_get(raw, "restriction_level"),
        name=_get(raw, "name"),
        enabled=_get(raw, "enabled"),
        target_type=_get(raw, "target_type"),
        targets=list(targets) if targets else [],
        secure=_get(raw, "secure"),
        qos=qos_block if qos_block else None,
        qos_enabled=qos_block.get("enabled") if isinstance(qos_block, dict) else None,
        route=route_block if route_block else None,
        route_enabled=route_block.get("enabled") if isinstance(route_block, dict) else None,
        applies_to=list(targets) if targets else [],
    )


def to_controller_create(model: OonPolicy) -> Dict[str, Any]:
    """Produce a controller create payload from an OonPolicy model."""
    payload: Dict[str, Any] = {}
    for field_name in ("name", "enabled", "target_type", "targets", "secure", "qos", "route"):
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
