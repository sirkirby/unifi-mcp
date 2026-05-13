"""Strawberry types for access/visitors.

Phase 6 PR4 Task B migration target. The single read serializer
(``VisitorSerializer``) maps to one Strawberry class:

- ``Visitor`` — access_list_visitors + access_get_visitor

Resource-registered (LIST + DETAIL paths). Mutation acks
(``access_create_visitor`` / ``access_delete_visitor``) stay in
``serializers/access/visitors.py`` — both flow through the manager's
preview path and produce dict acks.

VisitorManager surfaces ``valid_from`` / ``valid_until`` (with
``access_start`` / ``access_end`` fallbacks). ``from_manager_output``
normalizes across both, mirroring the old serializer byte-for-byte.
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


@strawberry.type(description="A UniFi Access visitor (time-bounded guest pass).")
class Visitor:
    """Mirrors ``VisitorSerializer.serialize`` projection byte-for-byte."""

    id: strawberry.ID | None
    name: str | None
    host_user_id: str | None
    valid_from: str | None
    valid_until: str | None
    status: str | None
    credential_count: int | None
    email: str | None
    phone: str | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": [
                "name",
                "host_user_id",
                "valid_from",
                "valid_until",
                "status",
            ],
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "Visitor":
        return cls(
            id=_get(obj, "id"),
            name=_get(obj, "name"),
            host_user_id=_get(obj, "host_user_id"),
            valid_from=_get(obj, "valid_from") or _get(obj, "access_start"),
            valid_until=_get(obj, "valid_until") or _get(obj, "access_end"),
            status=_get(obj, "status"),
            credential_count=_get(obj, "credential_count"),
            email=_get(obj, "email"),
            phone=_get(obj, "phone"),
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: v for k, v in out.items() if not k.startswith("_") and not callable(v)}
