"""Shared field model for Access credentials (read + create).

Mirrors the Strawberry type in
``unifi_api.graphql.types.access.credentials``.

- ``Credential`` — access_list_credentials + access_get_credential +
  access_create_credential (mutable fields only)

Factory helpers:
- ``from_controller``      — normalise the raw manager dict → Credential
- ``to_controller_create`` — translate a Credential → manager create payload

``MUTABLE_FIELDS`` drives the cross-layer symmetry test: the Strawberry
type must expose every field listed here.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Pydantic domain model
# ---------------------------------------------------------------------------


class Credential(BaseModel):
    """Canonical Access credential model (read + mutable create fields)."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="Credential UUID",
        json_schema_extra={"mutable": False},
    )
    status: Optional[str] = Field(
        default=None,
        description="Credential status (active, revoked, expired, etc.)",
        json_schema_extra={"mutable": False},
    )
    expiry: Optional[str] = Field(
        default=None,
        description="Expiry timestamp (ISO 8601)",
        json_schema_extra={"mutable": False},
    )
    last_used: Optional[str] = Field(
        default=None,
        description="Timestamp of last use (ISO 8601)",
        json_schema_extra={"mutable": False},
    )

    # --- mutable (accepted by create) ---
    type: Optional[str] = Field(
        default=None,
        description="Credential type: nfc, pin, or mobile",
    )
    user_id: Optional[str] = Field(
        default=None,
        description="UUID of the user this credential is assigned to",
    )
    token: Optional[str] = Field(
        default=None,
        description="NFC token value (NFC credentials only)",
    )
    pin_code: Optional[str] = Field(
        default=None,
        description="PIN code value (PIN credentials only)",
    )


# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------

MUTABLE_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in Credential.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True)
)

READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in Credential.model_fields.items()
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


def from_controller(raw: Any) -> Credential:
    """Build a Credential from a manager dict or object.

    Coalesces:
    - ``last_used`` / ``last_used_at`` → ``last_used``
    - ``expiry`` / ``expires_at`` → ``expiry``
    """
    last_used = _get(raw, "last_used") or _get(raw, "last_used_at")
    expiry = _get(raw, "expiry") or _get(raw, "expires_at")
    return Credential(
        id=_get(raw, "id"),
        status=_get(raw, "status"),
        expiry=expiry,
        last_used=last_used,
        type=_get(raw, "type"),
        user_id=_get(raw, "user_id"),
        token=_get(raw, "token"),
        pin_code=_get(raw, "pin_code"),
    )


def to_controller_create(model: Credential) -> Dict[str, Any]:
    """Produce the payload for ``apply_create_credential(credential_type, data)``.

    The manager signature is ``apply_create_credential(credential_type, data)``
    where it builds ``{"type": credential_type, **data}`` before posting.
    We therefore return a dict that separates ``type`` (passed as the first
    positional arg) from the ``data`` dict — callers should unpack as:

        payload = to_controller_create(model)
        await mgr.apply_create_credential(payload["credential_type"], payload["data"])
    """
    data: Dict[str, Any] = {}
    if model.user_id is not None:
        data["user_id"] = model.user_id
    if model.token is not None:
        data["token"] = model.token
    if model.pin_code is not None:
        data["pin_code"] = model.pin_code
    return {
        "credential_type": model.type,
        "data": data,
    }
