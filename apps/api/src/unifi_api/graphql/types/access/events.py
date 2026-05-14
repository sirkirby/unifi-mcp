"""Strawberry types for access/events (Phase 6 PR4 Task B).

Read serializers migrated from ``unifi_api.serializers.access.events``:

- ``Event`` — access_list_events (EVENT_LOG, resource-registered) AND
  access_get_event (DETAIL). Both old serializers
  (``AccessEventSerializer`` LIST and ``EventDetailSerializer`` DETAIL)
  shared the same ``_event_payload`` projection; one typed class covers
  both. Mirrors the dict shape byte-for-byte.
- ``ActivitySummary`` — access_get_activity_summary (DETAIL). Pass-
  through for the activity histogram payload (``activities/histogram``)
  with ``period_start`` / ``period_end`` / ``total_events`` /
  ``granted_count`` / ``denied_count`` / ``top_users`` / ``buckets``,
  surfacing catalog-level fields with ``None`` fallbacks.

Serializers that stay in the dict registry (NOT migrated):

- ``AccessEventSerializer`` (``access_recent_events``) — the SSE stream
  generator at ``routes/streams/access.py`` calls
  ``serializer.serialize`` directly per broadcast event; can't move to a
  type without rewriting the streamer (mirrors protect's
  ``RecentEventsSerializer``).
- ``AccessStreamSubscriptionSerializer`` (``access_subscribe_events``) —
  STREAM kind; thin shim returning the SSE URL metadata.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Annotated, Any

import strawberry
from strawberry.types import Info

if TYPE_CHECKING:
    from unifi_api.graphql.types.access.doors import Door
    from unifi_api.graphql.types.access.users import User


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


@strawberry.type(
    name="AccessEvent",
    description="A UniFi Access event row (list + detail share this shape).",
)
class Event:
    """Mirrors ``_event_payload`` projection byte-for-byte.

    Used for both ``access_list_events`` (EVENT_LOG) and
    ``access_get_event`` (DETAIL) — the old serializers had identical
    payloads, so a single typed class covers both. ``access_recent_events``
    intentionally stays as a serializer because the SSE streamer calls
    ``.serialize`` directly per broadcast event.
    """

    id: strawberry.ID | None
    type: str | None
    timestamp: str | None
    door_id: str | None
    user_id: str | None
    credential_id: str | None
    result: str | None

    # Context for relationship edges — NOT in SDL, NOT in to_dict().
    _controller_id: strawberry.Private[str | None] = None
    _door_id: strawberry.Private[str | None] = None
    _user_id: strawberry.Private[str | None] = None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["type", "timestamp", "door_id", "user_id", "result"],
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "Event":
        door_id = _get(obj, "door_id")
        user_id = _get(obj, "user_id")
        inst = cls(
            id=_get(obj, "id"),
            type=_get(obj, "type"),
            timestamp=_get(obj, "timestamp") or _get(obj, "time"),
            door_id=door_id,
            user_id=user_id,
            credential_id=_get(obj, "credential_id"),
            result=_get(obj, "result"),
        )
        inst._door_id = door_id
        inst._user_id = user_id
        return inst

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: v for k, v in out.items() if not k.startswith("_") and not callable(v)}

    @strawberry.field(description="The door this event references.")
    async def door(
        self,
        info: Info,
    ) -> Annotated["Door", strawberry.lazy("unifi_api.graphql.types.access.doors")] | None:
        from unifi_api.graphql.resolvers.access import _fetch_doors
        from unifi_api.graphql.types.access.doors import Door

        if not self._controller_id or not self._door_id:
            return None
        all_doors = await _fetch_doors(info.context, self._controller_id)
        for d in all_doors:
            d_id = d.get("id") if isinstance(d, dict) else getattr(d, "id", None)
            if d_id == self._door_id:
                inst = Door.from_manager_output(d)
                inst._controller_id = self._controller_id
                return inst
        return None

    @strawberry.field(description="The user this event references.")
    async def user(
        self,
        info: Info,
    ) -> Annotated["User", strawberry.lazy("unifi_api.graphql.types.access.users")] | None:
        from unifi_api.graphql.resolvers.access import _fetch_users
        from unifi_api.graphql.types.access.users import User

        if not self._controller_id or not self._user_id:
            return None
        all_users = await _fetch_users(info.context, self._controller_id)
        for u in all_users:
            u_id = u.get("id") if isinstance(u, dict) else getattr(u, "id", None)
            if u_id == self._user_id:
                inst = User.from_manager_output(u)
                inst._controller_id = self._controller_id
                return inst
        return None


@strawberry.type(description="Access activity histogram summary.")
class ActivitySummary:
    """Mirrors ``ActivitySummarySerializer.serialize`` projection
    byte-for-byte for the ``activities/histogram`` payload."""

    period_start: str | None
    period_end: str | None
    total_events: int | None
    granted_count: int | None
    denied_count: int | None
    top_users: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    buckets: strawberry.scalars.JSON | None  # type: ignore[name-defined]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "ActivitySummary":
        if not isinstance(obj, dict):
            if hasattr(obj, "model_dump"):
                obj = obj.model_dump()
            else:
                return cls(
                    period_start=None,
                    period_end=None,
                    total_events=None,
                    granted_count=None,
                    denied_count=None,
                    top_users=None,
                    buckets=None,
                )
        return cls(
            period_start=obj.get("period_start") or obj.get("since"),
            period_end=obj.get("period_end") or obj.get("until"),
            total_events=obj.get("total_events") or obj.get("total"),
            granted_count=obj.get("granted_count"),
            denied_count=obj.get("denied_count"),
            top_users=obj.get("top_users"),
            buckets=obj.get("buckets") or obj.get("histogram"),
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: v for k, v in out.items() if not k.startswith("_") and not callable(v)}
