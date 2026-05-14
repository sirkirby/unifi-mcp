"""Strawberry types for network/port_forwards.

Phase 6 PR2 Task 22 migration target. One read shape that used to live in
``unifi_api.serializers.network.port_forwards``:

- ``PortForward`` — list_port_forwards + get_port_forward (V1
                    ``/rest/portforward``; the manager normalizes
                    ``protocol`` to ``fwd_protocol`` so this layer accepts
                    both)

The mutation ack serializer (``PortForwardMutationAckSerializer``) stays in
the original module for create/update/toggle dispatch.

Each type's ``from_manager_output(raw)`` classmethod replaces the dict-shaping
logic that used to live in serializers/network/port_forwards.py.
``to_dict()`` exposes the same dict contract the REST routes return today.
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


@strawberry.type(description="A port-forward rule (V1 /rest/portforward entry).")
class PortForward:
    id: strawberry.ID | None
    name: str | None
    enabled: bool
    fwd_protocol: str | None
    dst_port: str | None
    fwd_port: str | None
    fwd_ip: str | None
    src: str | None
    log: bool

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": [
                "name",
                "enabled",
                "fwd_protocol",
                "dst_port",
                "fwd_port",
                "fwd_ip",
            ],
            "sort_default": "name:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "PortForward":
        return cls(
            id=_get(obj, "_id") or _get(obj, "id"),
            name=_get(obj, "name"),
            enabled=bool(_get(obj, "enabled", False)),
            fwd_protocol=_get(obj, "fwd_protocol") or _get(obj, "proto") or _get(obj, "protocol"),
            dst_port=_get(obj, "dst_port"),
            fwd_port=_get(obj, "fwd_port"),
            fwd_ip=_get(obj, "fwd_ip") or _get(obj, "fwd"),
            src=_get(obj, "src"),
            log=bool(_get(obj, "log", False)),
        )

    def to_dict(self) -> dict:
        return asdict(self)
