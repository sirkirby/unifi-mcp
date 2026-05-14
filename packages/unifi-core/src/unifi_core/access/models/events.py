"""Shared field models for Access events (read-only).

Two classes:
- ``Event`` — an access event row (door open, denial, etc.).
- ``ActivitySummary`` — aggregated histogram summary over a time window.

All fields are read-only; there are no event mutation tools. The
``timestamp``, ``period_start``, and ``period_end`` fields are coerced
to ISO 8601 strings via ``_stringify_dt``. The ``top_users`` and
``buckets`` fields are JSON pass-throughs (dict or list).
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class Event(BaseModel):
    """Canonical Access event model (read-only)."""

    id: Optional[str] = Field(default=None, description="Event UUID", json_schema_extra={"mutable": False})
    type: Optional[str] = Field(
        default=None, description="Event type (door_open, access_denied, etc.)", json_schema_extra={"mutable": False}
    )
    timestamp: Optional[str] = Field(
        default=None, description="ISO 8601 timestamp when the event occurred", json_schema_extra={"mutable": False}
    )
    door_id: Optional[str] = Field(
        default=None, description="Door UUID associated with the event", json_schema_extra={"mutable": False}
    )
    user_id: Optional[str] = Field(
        default=None, description="User UUID associated with the event", json_schema_extra={"mutable": False}
    )
    credential_id: Optional[str] = Field(
        default=None, description="Credential UUID used in the event", json_schema_extra={"mutable": False}
    )
    result: Optional[str] = Field(
        default=None, description="Event result (granted, denied, etc.)", json_schema_extra={"mutable": False}
    )


class ActivitySummary(BaseModel):
    """Canonical Access activity histogram summary model (read-only)."""

    period_start: Optional[str] = Field(
        default=None, description="ISO 8601 start of the summary period", json_schema_extra={"mutable": False}
    )
    period_end: Optional[str] = Field(
        default=None, description="ISO 8601 end of the summary period", json_schema_extra={"mutable": False}
    )
    total_events: Optional[int] = Field(
        default=None, description="Total event count in the period", json_schema_extra={"mutable": False}
    )
    granted_count: Optional[int] = Field(
        default=None, description="Count of granted access events", json_schema_extra={"mutable": False}
    )
    denied_count: Optional[int] = Field(
        default=None, description="Count of denied access events", json_schema_extra={"mutable": False}
    )
    top_users: Optional[Any] = Field(
        default=None, description="Top users by event count (JSON pass-through)", json_schema_extra={"mutable": False}
    )
    buckets: Optional[Any] = Field(
        default=None, description="Histogram buckets (JSON pass-through)", json_schema_extra={"mutable": False}
    )


MUTABLE_FIELDS: frozenset[str] = frozenset()
READ_ONLY_FIELDS: frozenset[str] = frozenset(Event.model_fields.keys()) | frozenset(ActivitySummary.model_fields.keys())


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


def event_from_controller(raw: Any) -> Event:
    """Build an Event from a manager dict or object."""
    return Event(
        id=_get(raw, "id"),
        type=_get(raw, "type"),
        timestamp=_stringify_dt(_get(raw, "timestamp") or _get(raw, "time")),
        door_id=_get(raw, "door_id"),
        user_id=_get(raw, "user_id"),
        credential_id=_get(raw, "credential_id"),
        result=_get(raw, "result"),
    )


def activity_summary_from_controller(raw: Any) -> ActivitySummary:
    """Build an ActivitySummary from a manager dict or object."""
    if not isinstance(raw, dict):
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump()
        else:
            raw = {}
    return ActivitySummary(
        period_start=_stringify_dt(raw.get("period_start") or raw.get("since")),
        period_end=_stringify_dt(raw.get("period_end") or raw.get("until")),
        total_events=raw.get("total_events") or raw.get("total"),
        granted_count=raw.get("granted_count"),
        denied_count=raw.get("denied_count"),
        top_users=raw.get("top_users"),
        buckets=raw.get("buckets") or raw.get("histogram"),
    )
