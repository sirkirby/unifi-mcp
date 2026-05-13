"""Strawberry types for access/credentials.

Phase 6 PR4 Task B migration target. The single read serializer
(``CredentialSerializer``) maps to one Strawberry class:

- ``Credential`` — access_list_credentials + access_get_credential

Resource-registered (LIST + DETAIL paths). Mutation acks
(``access_create_credential`` / ``access_revoke_credential``) stay in
``serializers/access/credentials.py`` — both flow through the manager's
preview path and produce dict acks.
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


@strawberry.type(description="A UniFi Access credential (NFC, PIN, etc.).")
class Credential:
    """Mirrors ``CredentialSerializer.serialize`` projection byte-for-byte."""

    id: strawberry.ID | None
    user_id: str | None
    type: str | None
    status: str | None
    expiry: str | None
    last_used: str | None
    token: str | None
    pin_code: str | None

    # Context for relationship edges — NOT in SDL, NOT in to_dict().
    _controller_id: strawberry.Private[str | None] = None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["user_id", "type", "status", "expiry"],
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "Credential":
        return cls(
            id=_get(obj, "id"),
            user_id=_get(obj, "user_id"),
            type=_get(obj, "type"),
            status=_get(obj, "status"),
            expiry=_get(obj, "expiry"),
            last_used=_get(obj, "last_used"),
            token=_get(obj, "token"),
            pin_code=_get(obj, "pin_code"),
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: v for k, v in out.items() if not k.startswith("_") and not callable(v)}
