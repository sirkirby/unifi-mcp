"""Strawberry type for the network references read.

Each family is carried as JSON rather than a typed mirror, so a newer
controller's extra fields still round-trip. A family whose read failed is
named in ``unavailable`` and kept out of ``counts``; an empty list never stands
in for a failed read.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry
from unifi_core.redaction import redact_sensitive_fields


@strawberry.type(
    description=(
        "What references a network: Wi-Fi networks, port profiles, switch-port overrides, "
        "V2 firewall policies and clients. network_id is the network's _id from the networks "
        "field. Each family is read on its own; a family whose read failed is listed in "
        "unavailable instead of being reported as empty."
    )
)
class NetworkReferences:
    network_id: str
    name: str | None
    references: strawberry.scalars.JSON  # type: ignore[name-defined]
    counts: strawberry.scalars.JSON  # type: ignore[name-defined]
    unavailable: list[str]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind, "primary_key": "network_id", "display_columns": ["name"]}

    @classmethod
    def from_manager_output(cls, obj: Any, *, redact_sensitive: bool = True) -> "NetworkReferences":
        if not isinstance(obj, dict):
            raise ValueError("Network references must be a mapping")
        payload = redact_sensitive_fields(
            {
                "network_id": str(obj.get("network_id") or ""),
                "name": obj.get("name"),
                "references": obj.get("references") or {},
                "counts": obj.get("counts") or {},
                "unavailable": list(obj.get("unavailable") or []),
            },
            redact_sensitive=redact_sensitive,
        )
        return cls(**payload)

    def to_dict(self) -> dict:
        return asdict(self)
