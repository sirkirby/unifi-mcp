"""Protect sensor serializers.

Phase 6 PR3 Task C — the single read serializer (``SensorSerializer``)
moved to a Strawberry type in
``unifi_api.graphql.types.protect.sensors``. The
``protect_list_sensors`` tool is listed in
``PHASE6_TYPE_MIGRATED_TOOLS`` and dispatched via the type_registry by
both the REST route and the action endpoint.

This module now only ships ``SensorMutationAckSerializer`` for the
``protect_update_sensor_settings`` preview-and-confirm tool, which still
flows through the manager's preview/apply path and produces dict acks.
"""

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


@register_serializer(tools={"protect_update_sensor_settings": {"kind": RenderKind.DETAIL}})
class SensorMutationAckSerializer(Serializer):
    """Pass-through ack for sensor settings preview/apply dicts."""

    @staticmethod
    def serialize(obj) -> dict:
        if isinstance(obj, bool):
            return {"success": obj}
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        return {"result": str(obj)}
