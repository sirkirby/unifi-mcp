"""Shared field model for Access visitors (read + create).

Mirrors the Strawberry type in
``unifi_api.graphql.types.access.visitors``.

- ``Visitor`` — access_list_visitors + access_get_visitor +
  access_create_visitor (mutable fields only)

Factory helpers:
- ``from_controller``      — normalise the raw manager dict → Visitor
- ``to_controller_create`` — translate a Visitor → manager create payload

``MUTABLE_FIELDS`` drives the cross-layer symmetry test: the Strawberry
type must expose every field listed here.

Naming note: the canonical model uses ``valid_from`` / ``valid_until``
(read-shape names). The MCP tool accepts ``access_start`` / ``access_end``
from callers and builds the model with ``valid_from=access_start``,
``valid_until=access_end``. ``to_controller_create`` translates back to
``access_start`` / ``access_end`` for the manager's expected signature.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Pydantic domain model
# ---------------------------------------------------------------------------


class Visitor(BaseModel):
    """Canonical Access visitor model (read + mutable create fields)."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="Visitor UUID",
        json_schema_extra={"mutable": False},
    )
    host_user_id: Optional[str] = Field(
        default=None,
        description="UUID of the host user who created the pass",
        json_schema_extra={"mutable": False},
    )
    status: Optional[str] = Field(
        default=None,
        description="Visitor status (active, expired, etc.)",
        json_schema_extra={"mutable": False},
    )
    credential_count: Optional[int] = Field(
        default=None,
        description="Number of credentials associated with this visitor",
        json_schema_extra={"mutable": False},
    )

    # --- mutable (accepted by create) ---
    name: Optional[str] = Field(
        default=None,
        description="Visitor display name",
    )
    valid_from: Optional[str] = Field(
        default=None,
        description="Start of access period (ISO 8601)",
    )
    valid_until: Optional[str] = Field(
        default=None,
        description="End of access period (ISO 8601)",
    )
    email: Optional[str] = Field(
        default=None,
        description="Visitor email address for notifications",
    )
    phone: Optional[str] = Field(
        default=None,
        description="Visitor phone number",
    )


# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------

MUTABLE_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in Visitor.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True)
)

READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in Visitor.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True) is False
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ---------------------------------------------------------------------------
# Public factory helpers
# ---------------------------------------------------------------------------


def from_controller(raw: Any) -> Visitor:
    """Build a Visitor from a manager dict or object.

    Coalesces:
    - ``valid_from`` / ``access_start`` → ``valid_from``
    - ``valid_until`` / ``access_end``  → ``valid_until``
    """
    valid_from = _get(raw, "valid_from") or _get(raw, "access_start")
    valid_until = _get(raw, "valid_until") or _get(raw, "access_end")
    return Visitor(
        id=_get(raw, "id"),
        host_user_id=_get(raw, "host_user_id"),
        status=_get(raw, "status"),
        credential_count=_get(raw, "credential_count"),
        name=_get(raw, "name"),
        valid_from=valid_from,
        valid_until=valid_until,
        email=_get(raw, "email"),
        phone=_get(raw, "phone"),
    )


def to_controller_create(model: Visitor) -> Dict[str, Any]:
    """Produce the payload for ``apply_create_visitor(name, access_start, access_end, **extra)``.

    Translates ``valid_from`` → ``access_start`` and
    ``valid_until`` → ``access_end`` to match the manager's expected
    signature. ``email`` and ``phone`` are included only when not None.
    """
    payload: Dict[str, Any] = {
        "name": model.name,
        "access_start": model.valid_from,
        "access_end": model.valid_until,
    }
    if model.email is not None:
        payload["email"] = model.email
    if model.phone is not None:
        payload["phone"] = model.phone
    return payload
