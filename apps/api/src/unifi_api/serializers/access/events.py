"""Access event stream + recent-buffer serializers.

Phase 6 PR4 Task B — read serializers (``EventDetailSerializer``,
``ActivitySummarySerializer``, and the LIST half of
``AccessEventSerializer``) moved to Strawberry types in
``unifi_api.graphql.types.access.events``. Their tools
(``access_list_events``, ``access_get_event``,
``access_get_activity_summary``) are listed in
``PHASE6_TYPE_MIGRATED_TOOLS`` and dispatched via the type_registry.

Two serializers stay here because they cannot move to a typed read
surface without rewriting the SSE stream generator:

  - ``AccessEventSerializer`` (``access_recent_events``) — EVENT_LOG
    pass-through for the buffer-snapshot read; the SSE streamer at
    ``routes/streams/access.py`` and ``routes/streams/access_per_door.py``
    calls ``serializer.serialize`` directly per broadcast event, so the
    serializer must remain dict-shaped.
  - ``AccessStreamSubscriptionSerializer`` (``access_subscribe_events``) —
    STREAM kind shim that returns ``{stream_url, transport: "sse",
    buffer_size, instructions}``.
"""

from typing import Any

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _event_payload(obj) -> dict:
    return {
        "id": _get(obj, "id"),
        "type": _get(obj, "type"),
        "timestamp": _get(obj, "timestamp") or _get(obj, "time"),
        "door_id": _get(obj, "door_id"),
        "user_id": _get(obj, "user_id"),
        "credential_id": _get(obj, "credential_id"),
        "message": _get(obj, "message"),
        "result": _get(obj, "result"),
    }


@register_serializer(
    tools={
        "access_recent_events": {"kind": RenderKind.EVENT_LOG},
    },
)
class AccessEventSerializer(Serializer):
    """EVENT_LOG pass-through for the recent-events SSE stream.

    Stays as a serializer because ``routes/streams/access.py`` calls
    ``serializer.serialize`` directly per broadcast event (mirrors
    protect's ``RecentEventsSerializer`` pattern).
    """

    kind = RenderKind.EVENT_LOG
    primary_key = "id"
    display_columns = ["type", "timestamp", "door_id", "user_id", "result"]
    sort_default = "timestamp:desc"

    @staticmethod
    def serialize(obj) -> dict:
        return _event_payload(obj)


@register_serializer(tools={"access_subscribe_events": {"kind": RenderKind.STREAM}})
class AccessStreamSubscriptionSerializer(Serializer):
    """Phase 4B: returns the SSE URL where live events are streamed.

    The MCP tool call exposes this metadata so consumers can discover the
    rich-API stream surface; rich-API clients connect to
    ``GET /v1/streams/access/events``.
    """

    @staticmethod
    def serialize(obj) -> dict:
        if isinstance(obj, dict):
            return {
                "stream_url": "/v1/streams/access/events",
                "transport": "sse",
                "buffer_size": obj.get("buffer_size"),
                "instructions": obj.get("instructions"),
            }
        return {"stream_url": "/v1/streams/access/events", "transport": "sse"}
