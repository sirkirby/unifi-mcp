"""Strawberry types for network/ap_groups.

Phase 6 PR2 Task 24 migration target. One read shape that used to live in
``unifi_api.serializers.network.ap_groups``:

- ``ApGroup`` — list_ap_groups + get_ap_group_details
                 (V2 ``/apgroups`` payloads served via ``NetworkManager``).
                 Computes ``ap_count`` from the ``device_macs`` array,
                 matching the legacy serializer.

The mutation ack serializer (``ApGroupMutationAckSerializer``) stays in the
original module for create/update/delete dispatch.

Each type's ``from_manager_output(raw)`` classmethod replaces the dict-shaping
logic that used to live in serializers/network/ap_groups.py. ``to_dict()``
exposes the same dict contract the REST routes return today.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


@strawberry.type(description="A UniFi AP group (collection of AP MAC addresses).")
class ApGroup:
    id: strawberry.ID | None
    name: str | None
    ap_count: int
    device_macs: list[str]
    wlan_group_ids: list[str]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "ap_count"],
            "sort_default": "name:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "ApGroup":
        device_macs = _get(obj, "device_macs") or []
        if not isinstance(device_macs, list):
            device_macs = []
        wlan_group_ids = _get(obj, "wlan_group_ids") or []
        if not isinstance(wlan_group_ids, list):
            wlan_group_ids = []
        return cls(
            id=_get(obj, "_id") or _get(obj, "id"),
            name=_get(obj, "name"),
            ap_count=len(device_macs),
            device_macs=list(device_macs),
            wlan_group_ids=list(wlan_group_ids),
        )

    def to_dict(self) -> dict:
        return asdict(self)
