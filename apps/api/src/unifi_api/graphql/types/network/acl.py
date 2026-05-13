"""Strawberry types for network/acl (MAC ACL rules).

Read shape for ``list_acl_rules`` and ``get_acl_rule_details``. Field
set is aligned with the canonical pydantic model at
``unifi_core.network.models.acl`` and enforced by
``apps/api/tests/unit/test_cross_layer_symmetry.py``. The mutation ack
serializer (``AclMutationAckSerializer``) stays in
``unifi_api.serializers.network.acl`` for create/update/delete dispatch.

Phase 0 of the Protect/Access schema bootstrap replaced the previous
opaque ``source`` / ``destination`` JSON fields with the flattened
mutable field set so callers can round-trip API list output back into
MCP create/update tools without field-name translation.
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


@strawberry.type(description="A MAC ACL rule (V2 /acl-rules entry).")
class AclRule:
    id: strawberry.ID | None
    name: str | None
    enabled: bool
    action: str | None
    acl_index: int | None
    network_id: str | None
    source_type: str | None
    destination_type: str | None
    source_macs: list[str]
    destination_macs: list[str]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "enabled", "action"],
            "sort_default": "name:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "AclRule":
        source = _get(obj, "traffic_source") or {}
        destination = _get(obj, "traffic_destination") or {}
        if not isinstance(source, dict):
            source = {}
        if not isinstance(destination, dict):
            destination = {}
        src_macs = source.get("specific_mac_addresses") or []
        dst_macs = destination.get("specific_mac_addresses") or []
        if not isinstance(src_macs, list):
            src_macs = []
        if not isinstance(dst_macs, list):
            dst_macs = []
        return cls(
            id=_get(obj, "_id") or _get(obj, "id"),
            name=_get(obj, "name"),
            enabled=bool(_get(obj, "enabled", False)),
            action=_get(obj, "action"),
            acl_index=_get(obj, "acl_index"),
            network_id=_get(obj, "mac_acl_network_id") or _get(obj, "network_id"),
            source_type=source.get("type"),
            destination_type=destination.get("type"),
            source_macs=list(src_macs),
            destination_macs=list(dst_macs),
        )

    def to_dict(self) -> dict:
        return asdict(self)
