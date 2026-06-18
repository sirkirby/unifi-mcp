"""Strawberry types for network/wlans (WLAN/SSID definitions).

Phase 6 PR2 Task 21 migration target. One type per read serializer that used
to live in ``unifi_api.serializers.network.wlans``:

- ``Wlan`` — list_wlans + get_wlan_details

Each type's ``from_manager_output(raw)`` classmethod replaces the dict-shaping
logic that used to live in serializers/network/wlans.py. ``to_dict()``
exposes the same dict contract the REST routes return today.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry
from unifi_core.redaction import redact_value


def _get(obj: Any, *keys: str, default: Any = None) -> Any:
    d = getattr(obj, "raw", obj if isinstance(obj, dict) else {})
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


@strawberry.type(description="A UniFi WLAN/SSID configuration.")
class Wlan:
    id: strawberry.ID | None
    name: str | None
    enabled: bool
    security: str | None
    network_id: str | None
    hide_ssid: bool | None
    vlan_id: int | None
    # Extended mutable fields exposed for create/update symmetry
    x_passphrase: str | None
    guest_policy: bool | None
    usergroup_id: str | None
    fast_roaming_enabled: bool | None
    pmf_mode: str | None
    wpa3_support: bool | None
    wpa3_transition: bool | None
    mac_filter_enabled: bool | None
    mac_filter_policy: str | None
    mac_filter_list: list[str] | None
    schedule_enabled: bool | None
    l2_isolation: bool | None
    wlan_band: str | None
    multicast_enhance_enabled: bool | None
    dtim_mode: str | None
    dtim_na: int | None
    dtim_ng: int | None
    minrate_ng_enabled: bool | None
    minrate_ng_data_rate_kbps: int | None
    minrate_na_enabled: bool | None
    minrate_na_data_rate_kbps: int | None
    group_rekey: int | None
    uapsd_enabled: bool | None
    proxy_arp: bool | None
    iapp_enabled: bool | None
    ap_group_ids: list[str] | None
    ap_group_mode: str | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "security", "enabled", "vlan_id"],
            "sort_default": "name:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any, *, redact_sensitive: bool = True) -> "Wlan":
        raw = getattr(obj, "raw", obj if isinstance(obj, dict) else {})
        return cls(
            id=raw.get("_id") or raw.get("id"),
            name=raw.get("name"),
            enabled=bool(raw.get("enabled", False)),
            security=raw.get("security"),
            network_id=raw.get("networkconf_id") or raw.get("network_id"),
            hide_ssid=raw.get("hide_ssid"),
            vlan_id=raw.get("vlan") or raw.get("vlan_id"),
            x_passphrase=redact_value("x_passphrase", raw.get("x_passphrase"), redact_sensitive=redact_sensitive),
            guest_policy=raw.get("guest_policy"),
            usergroup_id=raw.get("usergroup_id"),
            fast_roaming_enabled=raw.get("fast_roaming_enabled"),
            pmf_mode=raw.get("pmf_mode"),
            wpa3_support=raw.get("wpa3_support"),
            wpa3_transition=raw.get("wpa3_transition"),
            mac_filter_enabled=raw.get("mac_filter_enabled"),
            mac_filter_policy=raw.get("mac_filter_policy"),
            mac_filter_list=raw.get("mac_filter_list"),
            schedule_enabled=raw.get("schedule_enabled"),
            l2_isolation=raw.get("l2_isolation"),
            wlan_band=raw.get("wlan_band"),
            multicast_enhance_enabled=raw.get("multicast_enhance_enabled"),
            dtim_mode=raw.get("dtim_mode"),
            dtim_na=raw.get("dtim_na"),
            dtim_ng=raw.get("dtim_ng"),
            minrate_ng_enabled=raw.get("minrate_ng_enabled"),
            minrate_ng_data_rate_kbps=raw.get("minrate_ng_data_rate_kbps"),
            minrate_na_enabled=raw.get("minrate_na_enabled"),
            minrate_na_data_rate_kbps=raw.get("minrate_na_data_rate_kbps"),
            group_rekey=raw.get("group_rekey"),
            uapsd_enabled=raw.get("uapsd_enabled"),
            proxy_arp=raw.get("proxy_arp"),
            iapp_enabled=raw.get("iapp_enabled"),
            ap_group_ids=raw.get("ap_group_ids"),
            ap_group_mode=raw.get("ap_group_mode"),
        )

    def to_dict(self) -> dict:
        return asdict(self)
