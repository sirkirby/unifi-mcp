"""Strawberry types for network/qos (QoS rules).

Phase 6 PR2 Task 22 migration target. One read shape that used to live in
``unifi_api.serializers.network.qos``:

- ``QosRule`` — list_qos_rules + get_qos_rule_details (V2 ``/qos-rules``)

The mutation ack serializer (``QosMutationAckSerializer``) stays in the
original module since it covers create/update/toggle for QoS rules.

Each type's ``from_manager_output(raw)`` classmethod replaces the dict-shaping
logic that used to live in serializers/network/qos.py. ``to_dict()``
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


@strawberry.type(description="A QoS rate-limit rule (V2 /qos-rules entry).")
class QosRule:
    id: strawberry.ID | None
    name: str | None
    enabled: bool
    interface: str | None
    direction: str | None
    bandwidth_limit_kbps: int | None
    target_ip_address: str | None
    target_subnet: str | None
    dscp_value: int | None
    rate_max_down: int | None
    rate_max_up: int | None
    priority: int | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": [
                "name",
                "enabled",
                "priority",
                "rate_max_down",
                "rate_max_up",
            ],
            "sort_default": "name:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "QosRule":
        return cls(
            id=_get(obj, "_id") or _get(obj, "id"),
            name=_get(obj, "name"),
            enabled=bool(_get(obj, "enabled", False)),
            interface=_get(obj, "interface"),
            direction=_get(obj, "direction"),
            bandwidth_limit_kbps=_get(obj, "bandwidth_limit_kbps"),
            target_ip_address=_get(obj, "target_ip_address"),
            target_subnet=_get(obj, "target_subnet"),
            dscp_value=_get(obj, "dscp_value"),
            rate_max_down=_get(obj, "rate_max_down"),
            rate_max_up=_get(obj, "rate_max_up"),
            priority=_get(obj, "priority"),
        )

    def to_dict(self) -> dict:
        return asdict(self)
