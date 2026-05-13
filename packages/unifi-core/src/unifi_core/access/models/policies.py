"""Shared field model for Access policies (read + update).

Mirrors the Strawberry type in
``unifi_api.graphql.types.access.policies``.

- ``Policy`` — access_list_policies + access_get_policy +
  access_update_policy (mutable fields only)

Factory helpers:
- ``from_controller``      — normalise the raw manager dict → Policy
- ``to_controller_update`` — filter a partial dict to mutable keys only

``MUTABLE_FIELDS`` drives the cross-layer symmetry test: the Strawberry
type must expose every field listed here.

Naming note: the controller may return door associations under either
``door_ids`` or ``doors``; ``from_controller`` coalesces both into
``door_ids``. Similarly ``user_groups`` is coalesced into
``user_group_ids``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Pydantic domain model
# ---------------------------------------------------------------------------


class Policy(BaseModel):
    """Canonical Access policy model (read + mutable update fields)."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="Policy UUID",
        json_schema_extra={"mutable": False},
    )

    # --- mutable (accepted by update) ---
    name: Optional[str] = Field(
        default=None,
        description="Policy display name",
    )
    schedule_id: Optional[str] = Field(
        default=None,
        description="UUID of the schedule assigned to this policy",
    )
    door_ids: List[str] = Field(
        default_factory=list,
        description="UUIDs of the doors assigned to this policy",
    )
    user_group_ids: List[str] = Field(
        default_factory=list,
        description="UUIDs of the user groups assigned to this policy",
    )
    enabled: bool = Field(
        default=True,
        description="Whether the policy is currently active",
    )


# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------

MUTABLE_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in Policy.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True)
)

READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in Policy.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True) is False
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _coalesce_door_ids(raw: Any) -> List[str]:
    """Resolve door IDs from either ``door_ids`` or ``doors`` key."""
    door_ids = _get(raw, "door_ids")
    if isinstance(door_ids, list):
        return door_ids
    doors = _get(raw, "doors")
    if isinstance(doors, list):
        return [
            d.get("id") if isinstance(d, dict) else d
            for d in doors
            if d is not None
        ]
    return []


def _coalesce_user_group_ids(raw: Any) -> List[str]:
    """Resolve user group IDs from either ``user_group_ids`` or ``user_groups`` key."""
    user_group_ids = _get(raw, "user_group_ids")
    if isinstance(user_group_ids, list):
        return user_group_ids
    user_groups = _get(raw, "user_groups")
    if isinstance(user_groups, list):
        return [
            g.get("id") if isinstance(g, dict) else g
            for g in user_groups
            if g is not None
        ]
    return []


# ---------------------------------------------------------------------------
# Public factory helpers
# ---------------------------------------------------------------------------


def from_controller(raw: Any) -> Policy:
    """Build a Policy from a manager dict or object.

    Coalesces:
    - ``door_ids`` / ``doors``              → ``door_ids``
    - ``user_group_ids`` / ``user_groups``  → ``user_group_ids``
    """
    enabled_raw = _get(raw, "enabled", None)
    enabled = enabled_raw if isinstance(enabled_raw, bool) else True

    return Policy(
        id=_get(raw, "id"),
        name=_get(raw, "name"),
        schedule_id=_get(raw, "schedule_id"),
        door_ids=_coalesce_door_ids(raw),
        user_group_ids=_coalesce_user_group_ids(raw),
        enabled=enabled,
    )


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to only the mutable, recognised keys.

    The Access manager PUTs this payload directly to the controller, so
    only canonical field names (``door_ids``, ``user_group_ids``, etc.)
    are forwarded.  Read-only fields and unrecognised keys are silently
    dropped; ``None`` values are also dropped to avoid accidentally
    clearing fields.

    Note: boolean ``False`` is preserved (it is a valid update value).
    """
    return {
        k: v
        for k, v in fields.items()
        if k in MUTABLE_FIELDS and v is not None
    }
