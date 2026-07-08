"""Protect system serializers.

Phase 6 PR3 Task C — all four read serializers
(``ProtectSystemInfoSerializer``, ``ProtectHealthSerializer``,
``FirmwareStatusSerializer``, ``ViewerSerializer``) moved to Strawberry
types in ``unifi_api.graphql.types.protect.system``. Their tools
(``protect_get_system_info``, ``protect_get_health``,
``protect_get_firmware_status``, ``protect_list_viewers``) are listed
in ``PHASE6_TYPE_MIGRATED_TOOLS`` and dispatched via the type_registry
by both REST routes and the action endpoint.

This module now only ships ``ViewerMutationAckSerializer`` for the
``protect_update_viewer`` preview-and-confirm tool. System reboot lives
in a different module.
"""

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


@register_serializer(tools={"protect_update_viewer": {"kind": RenderKind.DETAIL}})
class ViewerMutationAckSerializer(Serializer):
    """Pass-through ack for viewer update preview/apply dicts."""

    @staticmethod
    def serialize(obj) -> dict:
        if isinstance(obj, bool):
            return {"success": obj}
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        return {"result": str(obj)}
