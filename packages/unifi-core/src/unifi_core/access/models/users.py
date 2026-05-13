"""Shared field model for Access users (read-only).

All fields are read-only: there are no user mutation tools in the Access
manifest. The ``created_at`` field is coerced to an ISO 8601 string via
``_stringify_dt`` to handle datetime objects from the controller layer.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class User(BaseModel):
    """Canonical Access user model (read-only)."""

    id: Optional[str] = Field(default=None, description="User UUID", json_schema_extra={"mutable": False})
    name: Optional[str] = Field(default=None, description="User display name", json_schema_extra={"mutable": False})
    employee_id: Optional[str] = Field(default=None, description="Employee / cardholder ID", json_schema_extra={"mutable": False})
    status: Optional[str] = Field(default=None, description="Account status (active, inactive, etc.)", json_schema_extra={"mutable": False})
    role: Optional[str] = Field(default=None, description="User role within the Access system", json_schema_extra={"mutable": False})
    created_at: Optional[str] = Field(default=None, description="ISO 8601 timestamp when the user was created", json_schema_extra={"mutable": False})


MUTABLE_FIELDS = frozenset()
READ_ONLY_FIELDS = frozenset(User.model_fields.keys())


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _stringify_dt(value: Any) -> Optional[str]:
    """Coerce a datetime-ish value to ISO 8601 string for serialization."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:
            return None
    return str(value)


def from_controller(raw: Any) -> User:
    """Build a User from a manager dict or object."""
    return User(
        id=_get(raw, "id"),
        name=_get(raw, "name"),
        employee_id=_get(raw, "employee_id"),
        status=_get(raw, "status"),
        role=_get(raw, "role"),
        created_at=_stringify_dt(_get(raw, "created_at")),
    )
