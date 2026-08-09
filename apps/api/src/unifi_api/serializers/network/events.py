"""Network event-stream serializers (post-Phase-6-Task-23).

Phase 6 PR2 Task 23 migrated the EVENT_LOG read shape (covering
``unifi_list_events``, ``unifi_get_alerts``, ``unifi_get_anomalies``,
``unifi_get_ips_events``) to a Strawberry ``EventLog`` type at
``unifi_api.graphql.types.network.event``.

``unifi_recent_events`` keeps a serializer here because the SSE stream
generator (``unifi_api.services.stream_generator.sse_event_stream``) calls
``serializer.serialize(event)`` on each broadcast event — a per-event dict
shaping path that the typed projection layer doesn't yet replace.
``unifi_subscribe_events`` keeps its STREAM-kind subscription serializer.

Field mapping delegates to ``event_log_from_controller`` in ``unifi-core`` so
both controller event shapes (legacy ``/stat/event`` flat keys and v2
``/system-log/all`` nested ``parameters``) are handled in exactly one place.
"""

from unifi_core.network.models.events import event_log_from_controller

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


@register_serializer(tools={"unifi_recent_events": {"kind": RenderKind.EVENT_LOG}})
class NetworkRecentEventsSerializer(Serializer):
    """Per-event EVENT_LOG shape consumed by the SSE stream generator."""

    primary_key = "id"
    sort_default = "time:desc"
    display_columns = ["time", "key", "msg", "mac"]

    @staticmethod
    def serialize(record) -> dict:
        if not isinstance(record, dict):
            return {"id": None}
        out = event_log_from_controller(record).model_dump()
        # Legacy contract: ``severity`` is included only when non-None.
        if out.get("severity") is None:
            out.pop("severity", None)
        return out


@register_serializer(tools={"unifi_subscribe_events": {"kind": RenderKind.STREAM}})
class NetworkStreamSubscriptionSerializer(Serializer):
    """Phase 4B precursor — returns the SSE URL + buffer metadata.

    Replaces the Phase 4A handle pattern.
    """

    @staticmethod
    def serialize(obj) -> dict:
        if isinstance(obj, dict):
            return {
                "stream_url": "/v1/streams/network/events",
                "transport": "sse",
                "buffer_size": obj.get("buffer_size"),
                "instructions": obj.get("instructions"),
            }
        return {"stream_url": "/v1/streams/network/events", "transport": "sse"}
