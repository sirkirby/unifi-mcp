"""Shared field models for Network client groups and user groups.

Mirrors the Strawberry types in
``unifi_api.graphql.types.network.client_group``.

- ``ClientGroup`` — list_client_groups + update/create client groups.
  Mutable fields: name, members (MAC addresses).
- ``UserGroup``   — list_usergroups + get_usergroup_details.
  Read-only shape — no update path at this layer (bandwidth limits are
  managed via the usergroup_manager's dedicated method args, not a generic
  update dict).

Factory helpers:
- ``from_controller``             — normalise raw manager dict → ClientGroup
- ``to_controller_update``        — filter partial dict to mutable keys
- ``usergroup_from_controller``   — normalise raw manager dict → UserGroup

``MUTABLE_FIELDS`` drives the cross-layer symmetry test.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# ClientGroup pydantic model
# ---------------------------------------------------------------------------


class ClientGroup(BaseModel):
    """Canonical client group model (read + mutable create/update fields)."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="Client group UUID (assigned by controller)",
        json_schema_extra={"mutable": False},
    )
    group_type: Optional[str] = Field(
        default=None,
        description="Group type (always CLIENTS for client groups)",
        json_schema_extra={"mutable": False},
    )

    # --- mutable (accepted by create and update) ---
    name: Optional[str] = Field(
        default=None,
        description="Client group name",
    )
    members: List[str] = Field(
        default_factory=list,
        description="List of member MAC addresses",
    )


# ---------------------------------------------------------------------------
# ClientGroup field sets
# ---------------------------------------------------------------------------

MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in ClientGroup.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in ClientGroup.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True) is False
)


# ---------------------------------------------------------------------------
# UserGroup pydantic model (read-only shape)
# ---------------------------------------------------------------------------


class UserGroup(BaseModel):
    """Canonical UserGroup model (read-only; QoS bandwidth profiles).

    UserGroups are managed via the usergroup_manager's positional args
    (name, down_limit_kbps, up_limit_kbps) rather than a generic update
    dict, so no ``to_controller_update`` is defined here.
    """

    # All fields read-only — no update dict path
    id: Optional[str] = Field(
        default=None,
        description="User group UUID",
        json_schema_extra={"mutable": False},
    )
    name: Optional[str] = Field(
        default=None,
        description="User group display name",
        json_schema_extra={"mutable": False},
    )
    qos_rate_max_down: Optional[int] = Field(
        default=None,
        description="Maximum download rate in Kbps (-1 = unlimited)",
        json_schema_extra={"mutable": False},
    )
    qos_rate_max_up: Optional[int] = Field(
        default=None,
        description="Maximum upload rate in Kbps (-1 = unlimited)",
        json_schema_extra={"mutable": False},
    )


USERGROUP_MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in UserGroup.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

USERGROUP_READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in UserGroup.model_fields.items()
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
# Public factory helpers — ClientGroup
# ---------------------------------------------------------------------------


def from_controller(raw: Any) -> ClientGroup:
    """Build a ClientGroup from a controller API response dict."""
    members = _get(raw, "members") or []
    if not isinstance(members, list):
        members = []
    return ClientGroup(
        id=_get(raw, "_id") or _get(raw, "id"),
        name=_get(raw, "name"),
        group_type=_get(raw, "type"),
        members=list(members),
    )


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to only mutable, recognised keys.

    Read-only fields and unrecognised keys are dropped.
    ``None`` values are dropped; boolean ``False`` is preserved.
    """
    return {k: v for k, v in fields.items() if k in MUTABLE_FIELDS and v is not None}


# ---------------------------------------------------------------------------
# Public factory helpers — UserGroup
# ---------------------------------------------------------------------------


def usergroup_from_controller(raw: Any) -> UserGroup:
    """Build a UserGroup from a controller API response dict."""
    return UserGroup(
        id=_get(raw, "_id") or _get(raw, "id"),
        name=_get(raw, "name"),
        qos_rate_max_down=_get(raw, "qos_rate_max_down"),
        qos_rate_max_up=_get(raw, "qos_rate_max_up"),
    )
