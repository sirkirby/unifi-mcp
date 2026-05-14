"""Strawberry types for network/events.

Phase 6 PR2 Task 23 migration target. One read shape that used to live in
``unifi_api.serializers.network.events``:

- ``EventLog`` — ``unifi_list_events``, ``unifi_get_alerts``,
                 ``unifi_get_anomalies``, ``unifi_get_ips_events``,
                 ``unifi_recent_events``. EVENT_LOG kind — sort_default
                 ``time:desc`` matches Phase 3's EVENT_LOG convention.
                 The ``severity`` field is included only when present in
                 the source record (alerts / IPS events surface it).

The stream-subscription serializer (``NetworkStreamSubscriptionSerializer``)
stays in the original module — STREAM kind has its own envelope shape.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry


def _get(obj: Any, *keys: str) -> Any:
    """Return the first non-None value among the listed keys."""
    if not isinstance(obj, dict):
        return None
    for k in keys:
        v = obj.get(k)
        if v is not None:
            return v
    return None


@strawberry.type(description="A curated event-log entry.")
class EventLog:
    id: strawberry.ID | None
    key: str | None
    msg: str | None
    time: int | None
    mac: str | None
    ip: str | None
    severity: str | None
    # Tracks whether the source record was a dict (legacy serializer
    # returned ``{"id": None}`` for non-dict inputs).
    _was_dict: strawberry.Private[bool] = True

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["time", "key", "msg", "mac"],
            "sort_default": "time:desc",
        }

    @classmethod
    def from_manager_output(cls, record: Any) -> "EventLog":
        if not isinstance(record, dict):
            return cls(
                id=None,
                key=None,
                msg=None,
                time=None,
                mac=None,
                ip=None,
                severity=None,
                _was_dict=False,
            )
        return cls(
            id=_get(record, "_id", "id"),
            key=_get(record, "key", "event_type", "type"),
            msg=_get(record, "msg", "message", "description"),
            time=_get(record, "time", "timestamp", "ts"),
            mac=_get(record, "user", "mac", "ap", "ap_mac", "device_mac"),
            ip=_get(record, "ip", "src_ip"),
            severity=_get(record, "severity", "level"),
            _was_dict=True,
        )

    def to_dict(self) -> dict:
        if not self._was_dict:
            return {"id": None}
        d = asdict(self)
        d.pop("_was_dict", None)
        # Legacy contract: ``severity`` is included only when non-None.
        if d.get("severity") is None:
            d.pop("severity", None)
        return d
