"""Shared field model for Network AP groups (read + create/update).

Mirrors the Strawberry type in
``unifi_api.graphql.types.network.ap_group``.

- ``ApGroup`` — list_ap_groups + get_ap_group_details +
  create_ap_group + update_ap_group

Factory helpers:
- ``from_controller``      — normalise the raw controller dict → ApGroup
- ``to_controller_create`` — translate an ApGroup → create payload
- ``to_controller_update`` — filter a partial dict to mutable keys only

``MUTABLE_FIELDS`` drives the cross-layer symmetry test: the Strawberry
type must expose every field listed here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Pydantic domain model
# ---------------------------------------------------------------------------


class ApGroup(BaseModel):
    """Canonical AP group model (read + mutable create/update fields)."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="AP group UUID (assigned by controller)",
        json_schema_extra={"mutable": False},
    )
    ap_count: Optional[int] = Field(
        default=None,
        description="Number of APs in this group (derived from device_macs)",
        json_schema_extra={"mutable": False},
    )

    # --- mutable (accepted by create and update) ---
    name: Optional[str] = Field(
        default=None,
        description="AP group name",
    )
    device_macs: List[str] = Field(
        default_factory=list,
        description="List of AP MAC addresses in this group",
    )
    wlan_group_ids: List[str] = Field(
        default_factory=list,
        description="List of WLAN group IDs assigned to this AP group",
    )


# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------

MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in ApGroup.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in ApGroup.model_fields.items()
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


def from_controller(raw: Any) -> ApGroup:
    """Build an ApGroup from a controller API response dict."""
    device_macs = _get(raw, "device_macs") or []
    if not isinstance(device_macs, list):
        device_macs = []
    wlan_group_ids = _get(raw, "wlan_group_ids") or []
    if not isinstance(wlan_group_ids, list):
        wlan_group_ids = []
    return ApGroup(
        id=_get(raw, "_id") or _get(raw, "id"),
        name=_get(raw, "name"),
        ap_count=len(device_macs),
        device_macs=list(device_macs),
        wlan_group_ids=list(wlan_group_ids),
    )


def to_controller_create(model: ApGroup) -> Dict[str, Any]:
    """Produce a controller create payload from an ApGroup."""
    payload: Dict[str, Any] = {}
    if model.name is not None:
        payload["name"] = model.name
    payload["device_macs"] = model.device_macs
    payload["wlan_group_ids"] = model.wlan_group_ids
    return payload


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to only mutable, recognised keys.

    Read-only fields and unrecognised keys are dropped.
    ``None`` values are dropped; boolean ``False`` is preserved.
    """
    return {k: v for k, v in fields.items() if k in MUTABLE_FIELDS and v is not None}
