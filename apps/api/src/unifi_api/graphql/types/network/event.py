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

Field mapping delegates to ``event_log_from_controller`` in ``unifi-core`` so
both controller event shapes (legacy ``/stat/event`` flat keys and v2
``/system-log/all`` nested ``parameters``) are handled in exactly one place.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry
from unifi_core.network.models.events import event_log_from_controller


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
        return cls(**event_log_from_controller(record).model_dump(), _was_dict=True)

    def to_dict(self) -> dict:
        if not self._was_dict:
            return {"id": None}
        d = asdict(self)
        d.pop("_was_dict", None)
        # Legacy contract: ``severity`` is included only when non-None.
        if d.get("severity") is None:
            d.pop("severity", None)
        return d
