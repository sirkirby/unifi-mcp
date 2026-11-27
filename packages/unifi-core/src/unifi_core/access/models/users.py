"""Shared field model for Access users (read-only).

All fields are read-only: there are no user mutation tools in the Access
manifest. Users come from the UniFi OS Users application, whose rows name
these fields ``unique_id``, ``full_name``, ``employee_number``, ``roles`` and
``create_time`` (epoch seconds). ``created_at`` is coerced to an ISO 8601 string.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


class User(BaseModel):
    """Canonical Access user model (read-only)."""

    id: Optional[str] = Field(default=None, description="User UUID", json_schema_extra={"mutable": False})
    name: Optional[str] = Field(default=None, description="User display name", json_schema_extra={"mutable": False})
    employee_id: Optional[str] = Field(
        default=None, description="Employee / cardholder ID", json_schema_extra={"mutable": False}
    )
    status: Optional[str] = Field(
        default=None, description="Account status (active, inactive, etc.)", json_schema_extra={"mutable": False}
    )
    role: Optional[str] = Field(
        default=None, description="User role within the Access system", json_schema_extra={"mutable": False}
    )
    created_at: Optional[str] = Field(
        default=None, description="ISO 8601 timestamp when the user was created", json_schema_extra={"mutable": False}
    )


MUTABLE_FIELDS = frozenset()
READ_ONLY_FIELDS = frozenset(User.model_fields.keys())


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _first(obj: Any, key: str) -> Any:
    """Return ``key``'s value, treating an empty string as absent."""
    value = _get(obj, key)
    return None if value == "" else value


_UUID_SUFFIX = re.compile(r"_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _role_name(roles: Any) -> Optional[str]:
    """Name of the user's first role, from the Users application's ``roles`` list.

    A private (custom) role's ``name`` is generated (``role_private_<ms>``), so it is
    labelled by its ``system_key`` without the trailing UUID, e.g. ``custom_administrator``.
    """
    if not isinstance(roles, list):
        return None
    for role in roles:
        if _get(role, "is_private") is True:
            key = _get(role, "system_key")
            if isinstance(key, str) and key:
                return _UUID_SUFFIX.sub("", key)
        name = _get(role, "name")
        if isinstance(name, str) and name:
            return name
    return None


def _stringify_dt(value: Any) -> Optional[str]:
    """Coerce a datetime-ish value or epoch seconds to an ISO 8601 string."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except (OverflowError, OSError, ValueError):
            return None
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
        id=_first(raw, "unique_id"),
        name=_first(raw, "full_name"),
        employee_id=_first(raw, "employee_number"),
        status=_first(raw, "status"),
        role=_role_name(_get(raw, "roles")),
        created_at=_stringify_dt(_first(raw, "create_time")),
    )
