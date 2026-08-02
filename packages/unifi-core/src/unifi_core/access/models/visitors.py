"""Shared field model for the Access Developer API visitor family.

The controller uses separate ``first_name`` / ``last_name`` fields and epoch
seconds for ``start_time`` / ``end_time``. MCP and API callers retain the
stable ``name`` plus ISO-8601 ``valid_from`` / ``valid_until`` dialect; the
helpers below translate at the boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

_STATUS_NAMES = {
    1: "upcoming",
    2: "visited",
    3: "visiting",
    4: "cancelled",
    5: "no_visit",
    6: "active",
}


class Visitor(BaseModel):
    """Canonical Access Developer API visitor model."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="Access Developer API visitor UUID",
        json_schema_extra={"mutable": False},
    )
    host_user_id: Optional[str] = Field(
        default=None,
        description="Legacy host-user UUID when supplied by the controller",
        json_schema_extra={"mutable": False},
    )
    status: Optional[str] = Field(
        default=None,
        description="Normalized visitor status",
        json_schema_extra={"mutable": False},
    )
    credential_count: Optional[int] = Field(
        default=None,
        description="Number of credentials associated with this visitor",
        json_schema_extra={"mutable": False},
    )
    access_policy_ids: Optional[list[str]] = Field(
        default=None,
        description="Developer API access-policy UUIDs currently assigned to the visitor",
        json_schema_extra={"mutable": False},
    )

    # --- mutable (accepted by create) ---
    name: Optional[str] = Field(default=None, description="Visitor display name")
    first_name: Optional[str] = Field(
        default=None,
        description="Explicit Developer API first name; provide with last_name to override name splitting",
    )
    last_name: Optional[str] = Field(
        default=None,
        description="Explicit Developer API last name; provide with first_name to override name splitting",
    )
    valid_from: Optional[str] = Field(default=None, description="Start of access period (ISO 8601 with timezone)")
    valid_until: Optional[str] = Field(default=None, description="End of access period (ISO 8601 with timezone)")
    email: Optional[str] = Field(default=None, description="Visitor email address for notifications")
    phone: Optional[str] = Field(default=None, description="Visitor mobile phone number")
    company: Optional[str] = Field(default=None, description="Visitor company")
    visit_reason: Optional[str] = Field(default=None, description="Reason for the visit")
    remarks: Optional[str] = Field(default=None, description="Operator notes about the visit")


MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in Visitor.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in Visitor.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True) is False
)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _epoch_to_iso(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = int(value)
        except ValueError:
            return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def _status_name(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        return _STATUS_NAMES.get(value, str(value))
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return str(value).lower()
    return _STATUS_NAMES.get(numeric, str(value))


def _credential_count(raw: Any) -> int | None:
    existing = _get(raw, "credential_count")
    if existing is not None:
        return int(existing)

    count = 0
    present = False
    for key in ("nfc_cards", "license_plates"):
        values = _get(raw, key)
        if isinstance(values, list):
            count += len(values)
            present = True
    for key in ("pin_code", "qr_code"):
        value = _get(raw, key)
        if value:
            count += 1
            present = True
    return count if present else None


def from_controller(raw: Any) -> Visitor:
    """Normalize a Developer API visitor dict or compatible legacy object."""
    first_name = _get(raw, "first_name")
    last_name = _get(raw, "last_name")
    name = _get(raw, "name")
    if not name:
        name = " ".join(str(part).strip() for part in (first_name, last_name) if part and str(part).strip()) or None

    return Visitor(
        id=_get(raw, "id"),
        host_user_id=_get(raw, "host_user_id"),
        status=_status_name(_get(raw, "status")),
        credential_count=_credential_count(raw),
        access_policy_ids=_get(raw, "access_policy_ids"),
        name=name,
        first_name=first_name,
        last_name=last_name,
        valid_from=_epoch_to_iso(_get(raw, "valid_from") or _get(raw, "access_start") or _get(raw, "start_time")),
        valid_until=_epoch_to_iso(_get(raw, "valid_until") or _get(raw, "access_end") or _get(raw, "end_time")),
        email=_get(raw, "email"),
        phone=_get(raw, "phone") or _get(raw, "mobile_phone"),
        company=_get(raw, "company"),
        visit_reason=_get(raw, "visit_reason"),
        remarks=_get(raw, "remarks"),
    )


def to_controller_create(model: Visitor) -> Dict[str, Any]:
    """Produce the tool-facing arguments accepted by ``VisitorManager``."""
    payload: Dict[str, Any] = {
        "name": model.name,
        "access_start": model.valid_from,
        "access_end": model.valid_until,
    }
    for key in ("first_name", "last_name", "email", "phone", "company", "visit_reason", "remarks"):
        value = getattr(model, key)
        if value is not None:
            payload[key] = value
    return payload
