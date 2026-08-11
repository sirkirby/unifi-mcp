"""Shared field model for Network switch port profiles.

Mirrors the Strawberry type in
``unifi_api.graphql.types.network.switch`` (class ``PortProfile``).

Only ``PortProfile`` is in Phase 4 scope. The other Strawberry types
(``PortOverrideRow``, ``SwitchPorts``, ``PortStatRow``, ``PortStats``,
``SwitchCapabilities``) are read-only / action shapes out of scope.

- ``PortProfile`` — list_port_profiles + get_port_profile_details +
  create_port_profile + delete_port_profile

Factory helpers:
- ``from_controller``      — normalise the raw controller dict → PortProfile
- ``to_controller_create`` — translate a PortProfile → create payload
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


class PortProfile(BaseModel):
    """Canonical port profile model (read + mutable create/update fields)."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="Port profile UUID (assigned by controller)",
        json_schema_extra={"mutable": False},
    )
    attr_no_delete: Optional[bool] = Field(
        default=None,
        description="Whether this is a system profile that cannot be deleted",
        json_schema_extra={"mutable": False},
    )

    # --- mutable (accepted by create and update) ---
    name: Optional[str] = Field(
        default=None,
        description="Profile name",
    )
    forward: Optional[str] = Field(
        default=None,
        description=(
            "Forwarding mode: all (trunk), native (access), customize, disabled. "
            "The controller rewrites this to agree with tagged_vlan_mgmt, so an access "
            "port needs forward='native' together with tagged_vlan_mgmt='block_all'"
        ),
    )
    tagged_vlan_mgmt: Optional[str] = Field(
        default=None,
        description=(
            "Tagged VLAN Management — decides whether the port trunks: "
            "'auto' (allow all), 'block_all' (access port), or 'custom' "
            "(only tagged_networkconf_ids, minus excluded_networkconf_ids)"
        ),
    )
    excluded_networkconf_ids: Optional[List[str]] = Field(
        default=None,
        description="Network IDs excluded when tagged_vlan_mgmt is 'custom'",
    )
    native_networkconf_id: Optional[str] = Field(
        default=None,
        description="Native network/VLAN ID for untagged traffic",
    )
    tagged_networkconf_ids: Optional[List[str]] = Field(
        default=None,
        description="List of tagged VLAN network IDs",
    )
    voice_networkconf_id: Optional[str] = Field(
        default=None,
        description="Voice VLAN network ID",
    )
    isolation: Optional[bool] = Field(
        default=None,
        description="Enable port isolation (blocks inter-client traffic)",
    )
    poe_mode: Optional[str] = Field(
        default=None,
        description="PoE mode: auto, off, pasv24, passthrough",
    )
    stp_port_mode: Optional[bool] = Field(
        default=None,
        description="Enable STP on this port",
    )
    # The UI's single "Port Mode: Infrastructure | Edge" control maps to these
    # three stored fields; Edge is stp_edge_state='enabled' + BPDU guard on +
    # stp_uplink false.
    stp_edge_state: Optional[str] = Field(
        default=None,
        description="STP edge state: 'enabled' for end-device (Edge) ports, 'disabled' for uplinks",
    )
    stp_bpdu_guard_enabled: Optional[bool] = Field(
        default=None,
        description="Shut the port if it receives a BPDU (paired with stp_edge_state for Edge ports)",
    )
    stp_uplink: Optional[bool] = Field(
        default=None,
        description="Treat the port as an STP uplink (Infrastructure ports)",
    )
    dot1x_ctrl: Optional[str] = Field(
        default=None,
        description="802.1X control: force_authorized, auto, force_unauthorized, mac_based, multi_host",
    )


# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------

MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in PortProfile.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in PortProfile.model_fields.items()
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


def from_controller(raw: Any) -> PortProfile:
    """Build a PortProfile from a controller API response dict."""
    tagged = _get(raw, "tagged_networkconf_ids") or []
    if not isinstance(tagged, list):
        tagged = []
    excluded = _get(raw, "excluded_networkconf_ids")
    return PortProfile(
        id=_get(raw, "_id") or _get(raw, "id"),
        attr_no_delete=_get(raw, "attr_no_delete"),
        name=_get(raw, "name"),
        forward=_get(raw, "forward"),
        tagged_vlan_mgmt=_get(raw, "tagged_vlan_mgmt"),
        excluded_networkconf_ids=list(excluded) if isinstance(excluded, list) else None,
        native_networkconf_id=_get(raw, "native_networkconf_id"),
        tagged_networkconf_ids=list(tagged),
        voice_networkconf_id=_get(raw, "voice_networkconf_id"),
        isolation=_get(raw, "isolation"),
        poe_mode=_get(raw, "poe_mode"),
        stp_port_mode=_get(raw, "stp_port_mode"),
        stp_edge_state=_get(raw, "stp_edge_state"),
        stp_bpdu_guard_enabled=_get(raw, "stp_bpdu_guard_enabled"),
        stp_uplink=_get(raw, "stp_uplink"),
        dot1x_ctrl=_get(raw, "dot1x_ctrl"),
    )


def build_create_payload(
    name: str,
    forward: str,
    native_networkconf_id: str = "",
    tagged_vlan_mgmt: str = "",
    tagged_networkconf_ids: Optional[List[str]] = None,
    excluded_networkconf_ids: Optional[List[str]] = None,
    voice_networkconf_id: str = "",
    isolation: bool = False,
    poe_mode: str = "auto",
    stp_port_mode: bool = True,
    stp_edge_state: str = "",
    stp_bpdu_guard_enabled: Optional[bool] = None,
    stp_uplink: Optional[bool] = None,
    dot1x_ctrl: str = "",
) -> Dict[str, Any]:
    """Build a controller create payload from the tool's flat parameters.

    ``poe_mode``, ``stp_port_mode`` and ``isolation`` are always included:
    omitting a value that happens to equal the default let the controller apply
    its own instead, so the documented default was not the one that took effect.
    Everything else is sent only when the caller supplied it, leaving the
    controller's own default in place.

    Shared by the MCP tool and the ``/v1/actions`` dispatch translator so the two
    entry points cannot drift.
    """
    payload: Dict[str, Any] = {
        "name": name,
        "forward": forward,
        "isolation": isolation,
        "poe_mode": poe_mode,
        "stp_port_mode": stp_port_mode,
    }
    if native_networkconf_id:
        payload["native_networkconf_id"] = native_networkconf_id
    if tagged_vlan_mgmt:
        payload["tagged_vlan_mgmt"] = tagged_vlan_mgmt
    if tagged_networkconf_ids is not None:
        payload["tagged_networkconf_ids"] = tagged_networkconf_ids
    if excluded_networkconf_ids is not None:
        payload["excluded_networkconf_ids"] = excluded_networkconf_ids
    if voice_networkconf_id:
        payload["voice_networkconf_id"] = voice_networkconf_id
    if stp_edge_state:
        payload["stp_edge_state"] = stp_edge_state
    if stp_bpdu_guard_enabled is not None:
        payload["stp_bpdu_guard_enabled"] = stp_bpdu_guard_enabled
    if stp_uplink is not None:
        payload["stp_uplink"] = stp_uplink
    if dot1x_ctrl:
        payload["dot1x_ctrl"] = dot1x_ctrl
    return payload


def to_controller_create(model: PortProfile) -> Dict[str, Any]:
    """Produce a controller create payload from a PortProfile model."""
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
