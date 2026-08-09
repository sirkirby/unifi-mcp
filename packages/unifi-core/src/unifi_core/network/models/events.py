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

import re
from typing import Any, Iterator, Optional

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
# v2 ``/system-log/all`` support
# ---------------------------------------------------------------------------
#
# Modern controllers (Network 9.x+) serve events from the v2 system-log API,
# which does not carry the flat ``user``/``msg``/``ip`` keys the legacy
# ``/stat/event`` API used. Instead each event has a ``parameters`` map keyed
# by the actor's *role*, and a ``message_raw`` template referencing those roles:
#
#     {
#       "key": "TRAFFIC_BLOCKED_KNOWN_SOURCE_CLIENT",
#       "message_raw": "{SRC_CLIENT} was blocked from accessing {DST_IP} ...",
#       "parameters": {
#         "SRC_CLIENT": {"id": "aa:bb:...", "ip": "10.0.0.5", "name": "camera"},
#         "DST_IP":     {"id": "52.70.82.252", "name": "52.70.82.252"},
#         "TRIGGER":    {"id": "...", "name": "block cameras to external"}
#       }
#     }
#
# ``id`` holds a MAC for client/device roles but an IP for address roles such
# as ``DST_IP``, so MAC extraction is both role-scoped and shape-validated.

#: Actor roles that carry a MAC in ``id``, most-specific first.
_MAC_ACTOR_ROLES: tuple[str, ...] = (
    "SRC_CLIENT",
    "CLIENT",
    "DST_CLIENT",
    "SRC_DEVICE",
    "DEVICE",
    "AP",
    "GATEWAY",
)

_MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
_PLACEHOLDER_RE = re.compile(r"\{([A-Z0-9_]+)\}")


def _parameters(record: Any) -> dict[str, Any]:
    """Return the v2 ``parameters`` map, or an empty dict."""
    if not isinstance(record, dict):
        return {}
    params = record.get("parameters")
    return params if isinstance(params, dict) else {}


def _actors(record: Any) -> Iterator[dict[str, Any]]:
    """Yield MAC-bearing actor dicts in role-priority order."""
    params = _parameters(record)
    for role in _MAC_ACTOR_ROLES:
        actor = params.get(role)
        if isinstance(actor, dict):
            yield actor


def _primary_actor(record: Any) -> Optional[dict[str, Any]]:
    """Return the highest-priority actor whose ``id`` is shaped like a MAC.

    ``mac`` and ``ip`` are both read from this single actor so they always
    describe the *same* device. Reading them independently would happily
    pair a client's MAC with the reporting console's IP — e.g. a
    ``THREAT_DETECTED`` event, where ``SRC_CLIENT`` is the offender but only
    the ``DEVICE`` (gateway) carries an ``ip``.
    """
    for actor in _actors(record):
        candidate = actor.get("id")
        if isinstance(candidate, str) and _MAC_RE.match(candidate):
            return actor
    return None


def _actor_mac(record: Any) -> Optional[str]:
    """Return the primary actor's MAC."""
    actor = _primary_actor(record)
    return actor.get("id") if actor else None


def _actor_ip(record: Any) -> Optional[str]:
    """Return the primary actor's IP.

    Falls back to the first actor carrying an IP only when no MAC-bearing
    actor exists, since with no MAC there is no pairing to get wrong.
    """
    actor = _primary_actor(record)
    if actor is not None:
        candidate = actor.get("ip")
        return candidate if isinstance(candidate, str) and candidate else None

    for other in _actors(record):
        candidate = other.get("ip")
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _actor_label(actor: Any) -> Optional[str]:
    """Best human-readable label for an actor dict."""
    if not isinstance(actor, dict):
        return None
    for key in ("name", "hostname", "id"):
        value = actor.get(key)
        if value:
            return str(value)
    return None


def _render_message(record: Any) -> Optional[str]:
    """Interpolate a v2 ``message_raw`` template against ``parameters``.

    Unknown placeholders are left intact rather than blanked, so an
    unrecognised role degrades to the raw template instead of a sentence
    with holes in it. Falls back to ``title_raw`` when no template exists.
    """
    if not isinstance(record, dict):
        return None

    template = _get(record, "message_raw", "messageRaw")
    if not isinstance(template, str) or not template:
        title = _get(record, "title_raw", "titleRaw")
        return title if isinstance(title, str) and title else None

    params = _parameters(record)

    def _substitute(match: re.Match[str]) -> str:
        label = _actor_label(params.get(match.group(1)))
        return label if label is not None else match.group(0)

    return _PLACEHOLDER_RE.sub(_substitute, template)


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def event_log_from_controller(record: Any) -> EventLog:
    """Build an EventLog from a controller API response dict.

    Handles both the legacy ``/stat/event`` flat shape and the v2
    ``/system-log/all`` nested shape. Legacy keys win when present so
    older controllers are unaffected.
    """
    if not isinstance(record, dict):
        return EventLog()
    return EventLog(
        id=_get(record, "_id", "id"),
        key=_get(record, "key", "event_type", "type"),
        msg=_get(record, "msg", "message", "description") or _render_message(record),
        time=_get(record, "time", "timestamp", "ts"),
        mac=_get(record, "user", "mac", "ap", "ap_mac", "device_mac") or _actor_mac(record),
        ip=_get(record, "ip", "src_ip") or _actor_ip(record),
        severity=_get(record, "severity", "level"),
    )
