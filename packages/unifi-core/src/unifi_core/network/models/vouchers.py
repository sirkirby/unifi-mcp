"""Shared field model for Network hotspot voucher resources.

Mirrors the Strawberry type in
``unifi_api.graphql.types.network.voucher``:

- ``Voucher`` — list_vouchers + get_voucher_details

Vouchers are read-only at the model layer: the create tool builds its
payload from tool parameters directly (no JSON Schema validator exists
for vouchers). MUTABLE_FIELDS = frozenset().

Factory helper:
- ``voucher_from_controller`` — normalise raw → Voucher
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Voucher
# ---------------------------------------------------------------------------


class Voucher(BaseModel):
    """Canonical hotspot voucher model (read-only output shape)."""

    id: Optional[str] = Field(
        default=None,
        description="Voucher UUID (_id from controller)",
        json_schema_extra={"mutable": False},
    )
    code: Optional[str] = Field(
        default=None,
        description="Voucher code used for guest login",
        json_schema_extra={"mutable": False},
    )
    status: Optional[str] = Field(
        default=None,
        description="Voucher status (e.g., 'VALID_ONE', 'USED_MULTIPLE')",
        json_schema_extra={"mutable": False},
    )
    duration: Optional[int] = Field(
        default=None,
        description="Duration in minutes the voucher is valid after activation",
        json_schema_extra={"mutable": False},
    )
    qos_overwrite: bool = Field(
        default=False,
        description="True when QoS limits are applied to this voucher",
        json_schema_extra={"mutable": False},
    )
    created_at: Optional[int] = Field(
        default=None,
        description="Unix epoch timestamp when the voucher was created",
        json_schema_extra={"mutable": False},
    )
    used_at: Optional[int] = Field(
        default=None,
        description="Unix epoch timestamp when the voucher was first used",
        json_schema_extra={"mutable": False},
    )


MUTABLE_FIELDS: frozenset[str] = frozenset()
READ_ONLY_FIELDS: frozenset[str] = frozenset(Voucher.model_fields.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def voucher_from_controller(obj: Any) -> Voucher:
    """Build a Voucher from a controller API response dict or object."""
    return Voucher(
        id=_get(obj, "_id") or _get(obj, "id"),
        code=_get(obj, "code"),
        status=_get(obj, "status"),
        duration=_get(obj, "duration"),
        qos_overwrite=bool(_get(obj, "qos_overwrite", False)),
        created_at=_get(obj, "create_time") or _get(obj, "created_at"),
        used_at=_get(obj, "used_at") or _get(obj, "end_time"),
    )
