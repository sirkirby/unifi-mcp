"""Shared field model for Network event log entries.

Mirrors the Strawberry type in
``unifi_api.graphql.types.network.event``:

- ``EventLog`` — list_events + recent_events

Read-only domain: no create/update/delete tools exist for event records.

Factory helper:
- ``event_log_from_controller`` — normalise raw dict → EventLog

MUTABLE_FIELDS = frozenset() (all fields are read-only).
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# EventLog
# ---------------------------------------------------------------------------


class EventLog(BaseModel):
    """Canonical event-log entry model (read-only)."""

    id: Optional[str] = Field(
        default=None,
        description="Event record ID (_id or id)",
        json_schema_extra={"mutable": False},
    )
    key: Optional[str] = Field(
        default=None,
        description="Event type key (e.g., 'EVT_WU_Disconnected')",
        json_schema_extra={"mutable": False},
    )
    msg: Optional[str] = Field(
        default=None,
        description="Human-readable event description",
        json_schema_extra={"mutable": False},
    )
    time: Optional[int] = Field(
        default=None,
        description="Unix epoch timestamp of the event",
        json_schema_extra={"mutable": False},
    )
    mac: Optional[str] = Field(
        default=None,
        description="Associated client or device MAC address",
        json_schema_extra={"mutable": False},
    )
    ip: Optional[str] = Field(
        default=None,
        description="Associated IP address (alerts / IPS events)",
        json_schema_extra={"mutable": False},
    )
    severity: Optional[str] = Field(
        default=None,
        description="Severity level when present (alerts / IPS events)",
        json_schema_extra={"mutable": False},
    )


MUTABLE_FIELDS: frozenset[str] = frozenset()
READ_ONLY_FIELDS: frozenset[str] = frozenset(EventLog.model_fields.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, *keys: str) -> Any:
    """Return the first non-None value among the listed keys."""
    if not isinstance(obj, dict):
        return None
    for k in keys:
        v = obj.get(k)
        if v is not None:
            return v
    return None


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def event_log_from_controller(record: Any) -> EventLog:
    """Build an EventLog from a controller API response dict."""
    if not isinstance(record, dict):
        return EventLog()
    return EventLog(
        id=_get(record, "_id", "id"),
        key=_get(record, "key", "event_type", "type"),
        msg=_get(record, "msg", "message", "description"),
        time=_get(record, "time", "timestamp", "ts"),
        mac=_get(record, "user", "mac", "ap", "ap_mac", "device_mac"),
        ip=_get(record, "ip", "src_ip"),
        severity=_get(record, "severity", "level"),
    )
