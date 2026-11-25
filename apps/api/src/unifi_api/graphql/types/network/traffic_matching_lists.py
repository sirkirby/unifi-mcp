"""Strawberry type for the Integration API traffic matching lists.

One type covering list + get + create. The controller's list/get/create
payloads share the same documented fields (``id``, ``name``, ``type``,
``items``); ``type`` is an opaque controller-defined string and item entries
are carried through verbatim, so ``items`` stays JSON rather than a typed
mirror of the item DTOs.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry
from unifi_core.redaction import redact_sensitive_fields


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


@strawberry.type(
    description=(
        "A reusable traffic matching list (IP/IPv4/port entries) referenced by firewall policies. "
        "Its id is an Integration API UUID scoped to the traffic-matching-list tool family — do "
        "not pass it to firewall group, firewall policy or MAC ACL tools."
    )
)
class TrafficMatchingList:
    id: strawberry.ID | None
    name: str | None
    type: str | None
    items: list[strawberry.scalars.JSON] | None  # type: ignore[name-defined]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "type"],
            "sort_default": "name:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any, *, redact_sensitive: bool = True) -> "TrafficMatchingList":
        payload = redact_sensitive_fields(
            {
                "id": _get(obj, "id"),
                "name": _get(obj, "name"),
                "type": _get(obj, "type"),
                "items": _get(obj, "items"),
            },
            redact_sensitive=redact_sensitive,
        )
        return cls(**payload)

    def to_dict(self) -> dict:
        return asdict(self)
