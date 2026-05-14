"""Shared field model for Network WLAN (SSID) configurations.

Mirrors the Strawberry type in
``unifi_api.graphql.types.network.wlan`` (class ``Wlan``).

- ``Wlan`` — list_wlans + get_wlan_details + create_wlan + update_wlan +
  toggle_wlan + delete_wlan

Factory helpers:
- ``from_controller``      — normalise the raw controller dict → Wlan
- ``to_controller_create`` — translate a Wlan → create payload
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


class Wlan(BaseModel):
    """Canonical WLAN/SSID configuration model (read + mutable create/update fields)."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="WLAN UUID (assigned by controller)",
        json_schema_extra={"mutable": False},
    )
    site_id: Optional[str] = Field(
        default=None,
        description="Site ID this WLAN belongs to",
        json_schema_extra={"mutable": False},
    )

    # --- mutable (accepted by create and update) ---
    name: Optional[str] = Field(
        default=None,
        description="SSID name (wireless network name broadcast to clients)",
    )
    security: Optional[str] = Field(
        default=None,
        description="Security protocol: open, wpa-psk, wpa2-psk, wpa3, wpapsk, wep",
    )
    x_passphrase: Optional[str] = Field(
        default=None,
        description="WPA passphrase (required when security is not 'open')",
    )
    enabled: Optional[bool] = Field(
        default=None,
        description="Whether the WLAN is active",
    )
    hide_ssid: Optional[bool] = Field(
        default=None,
        description="Whether to hide the SSID from broadcasts",
    )
    guest_policy: Optional[bool] = Field(
        default=None,
        description="Whether this is a guest network",
    )
    network_id: Optional[str] = Field(
        default=None,
        description="Network configuration ID (controller field: networkconf_id)",
    )
    vlan_id: Optional[int] = Field(
        default=None,
        description="VLAN ID (controller field: vlan)",
    )
    usergroup_id: Optional[str] = Field(
        default=None,
        description="User group ID applied to this WLAN",
    )
    fast_roaming_enabled: Optional[bool] = Field(
        default=None,
        description="Enable 802.11r fast BSS transition",
    )
    pmf_mode: Optional[str] = Field(
        default=None,
        description="Protected Management Frames mode: disabled, optional, required",
    )
    wpa3_support: Optional[bool] = Field(
        default=None,
        description="Enable WPA3 support",
    )
    wpa3_transition: Optional[bool] = Field(
        default=None,
        description="Enable WPA3 transition mode (WPA2+WPA3)",
    )
    mac_filter_enabled: Optional[bool] = Field(
        default=None,
        description="Enable MAC address filtering on this WLAN",
    )
    mac_filter_policy: Optional[str] = Field(
        default=None,
        description="MAC filter policy: allow (whitelist) or deny (blacklist)",
    )
    mac_filter_list: Optional[List[str]] = Field(
        default=None,
        description="List of MAC addresses for the filter",
    )
    schedule_enabled: Optional[bool] = Field(
        default=None,
        description="Enable WLAN schedule (time-based on/off)",
    )
    l2_isolation: Optional[bool] = Field(
        default=None,
        description="Enable L2 client isolation within this WLAN",
    )
    wlan_band: Optional[str] = Field(
        default=None,
        description="Restrict WLAN to specific band: both, 2g, 5g",
    )
    multicast_enhance_enabled: Optional[bool] = Field(
        default=None,
        description="Convert multicast to unicast per client",
    )
    dtim_mode: Optional[str] = Field(
        default=None,
        description="DTIM interval mode: default, custom",
    )
    dtim_na: Optional[int] = Field(
        default=None,
        description="DTIM interval for 5GHz radio (1–255)",
    )
    dtim_ng: Optional[int] = Field(
        default=None,
        description="DTIM interval for 2.4GHz radio (1–255)",
    )
    minrate_ng_enabled: Optional[bool] = Field(
        default=None,
        description="Enable minimum data rate for 2.4GHz",
    )
    minrate_ng_data_rate_kbps: Optional[int] = Field(
        default=None,
        description="Minimum data rate for 2.4GHz in kbps",
    )
    minrate_na_enabled: Optional[bool] = Field(
        default=None,
        description="Enable minimum data rate for 5GHz",
    )
    minrate_na_data_rate_kbps: Optional[int] = Field(
        default=None,
        description="Minimum data rate for 5GHz in kbps",
    )
    group_rekey: Optional[int] = Field(
        default=None,
        description="Group key rotation interval in seconds (0=disabled)",
    )
    uapsd_enabled: Optional[bool] = Field(
        default=None,
        description="Enable Unscheduled Automatic Power Save Delivery",
    )
    proxy_arp: Optional[bool] = Field(
        default=None,
        description="Enable proxy ARP for wireless clients",
    )
    iapp_enabled: Optional[bool] = Field(
        default=None,
        description="Enable Inter-AP communication protocol",
    )
    ap_group_ids: Optional[List[str]] = Field(
        default=None,
        description="AP group IDs that this WLAN broadcasts on",
    )
    ap_group_mode: Optional[str] = Field(
        default=None,
        description="Whether the WLAN broadcasts on all APs (all) or only specific groups (groups)",
    )


# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------

MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in Wlan.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name for name, field in Wlan.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True) is False
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


def from_controller(raw: Any) -> Wlan:
    """Build a Wlan from a controller API response dict.

    The controller stores the network association as 'networkconf_id'
    and the VLAN as 'vlan'. Both are normalised to model field names.
    """
    return Wlan(
        id=_get(raw, "_id") or _get(raw, "id"),
        site_id=_get(raw, "site_id"),
        name=_get(raw, "name"),
        security=_get(raw, "security"),
        x_passphrase=_get(raw, "x_passphrase"),
        enabled=_get(raw, "enabled"),
        hide_ssid=_get(raw, "hide_ssid"),
        guest_policy=_get(raw, "guest_policy"),
        network_id=_get(raw, "networkconf_id") or _get(raw, "network_id"),
        vlan_id=_get(raw, "vlan") or _get(raw, "vlan_id"),
        usergroup_id=_get(raw, "usergroup_id"),
        fast_roaming_enabled=_get(raw, "fast_roaming_enabled"),
        pmf_mode=_get(raw, "pmf_mode"),
        wpa3_support=_get(raw, "wpa3_support"),
        wpa3_transition=_get(raw, "wpa3_transition"),
        mac_filter_enabled=_get(raw, "mac_filter_enabled"),
        mac_filter_policy=_get(raw, "mac_filter_policy"),
        mac_filter_list=_get(raw, "mac_filter_list"),
        schedule_enabled=_get(raw, "schedule_enabled"),
        l2_isolation=_get(raw, "l2_isolation"),
        wlan_band=_get(raw, "wlan_band"),
        multicast_enhance_enabled=_get(raw, "multicast_enhance_enabled"),
        dtim_mode=_get(raw, "dtim_mode"),
        dtim_na=_get(raw, "dtim_na"),
        dtim_ng=_get(raw, "dtim_ng"),
        minrate_ng_enabled=_get(raw, "minrate_ng_enabled"),
        minrate_ng_data_rate_kbps=_get(raw, "minrate_ng_data_rate_kbps"),
        minrate_na_enabled=_get(raw, "minrate_na_enabled"),
        minrate_na_data_rate_kbps=_get(raw, "minrate_na_data_rate_kbps"),
        group_rekey=_get(raw, "group_rekey"),
        uapsd_enabled=_get(raw, "uapsd_enabled"),
        proxy_arp=_get(raw, "proxy_arp"),
        iapp_enabled=_get(raw, "iapp_enabled"),
        ap_group_ids=_get(raw, "ap_group_ids"),
        ap_group_mode=_get(raw, "ap_group_mode"),
    )


def to_controller_create(model: Wlan) -> Dict[str, Any]:
    """Produce a controller create payload from a Wlan model.

    Maps model field names back to controller API field names.
    """
    payload: Dict[str, Any] = {}
    for field_name in MUTABLE_FIELDS:
        value = getattr(model, field_name, None)
        if value is not None:
            payload[field_name] = value
    # Map network_id → networkconf_id
    if "network_id" in payload:
        payload["networkconf_id"] = payload.pop("network_id")
    # Map vlan_id → vlan
    if "vlan_id" in payload:
        payload["vlan"] = payload.pop("vlan_id")
    return payload


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to only mutable, recognised keys.

    Read-only fields and unrecognised keys are dropped.
    ``None`` values are dropped; boolean ``False`` is preserved.
    Maps model field names to controller API field names.
    """
    result = {k: v for k, v in fields.items() if k in MUTABLE_FIELDS and v is not None}
    # Map network_id → networkconf_id
    if "network_id" in result:
        result["networkconf_id"] = result.pop("network_id")
    # Map vlan_id → vlan
    if "vlan_id" in result:
        result["vlan"] = result.pop("vlan_id")
    return result
