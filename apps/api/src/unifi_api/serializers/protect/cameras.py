"""Protect camera mutation serializers.

Phase 6 PR3 Task A — the read serializers (``CameraSerializer``,
``CameraAnalyticsSerializer``, ``CameraStreamsSerializer``,
``SnapshotSerializer``) moved to Strawberry types in
``unifi_api.graphql.types.protect.cameras``. Their tools are listed in
``PHASE6_TYPE_MIGRATED_TOOLS`` and dispatched via the type_registry by
both REST routes and the action endpoint.

This module now only ships ``CameraMutationAckSerializer`` for the
PTZ/reboot/toggle/update preview-and-confirm tools, which still flow
through the manager's preview path and produce dict acks.
"""

from typing import Any

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


@register_serializer(
    tools={
        "protect_ptz_move": {"kind": RenderKind.DETAIL},
        "protect_ptz_preset": {"kind": RenderKind.DETAIL},
        "protect_ptz_zoom": {"kind": RenderKind.DETAIL},
        "protect_reboot_camera": {"kind": RenderKind.DETAIL},
        "protect_toggle_recording": {"kind": RenderKind.DETAIL},
        "protect_toggle_rtsp": {"kind": RenderKind.DETAIL},
        "protect_update_camera_settings": {"kind": RenderKind.DETAIL},
    },
)
class CameraMutationAckSerializer(Serializer):
    """Generic ack for camera-side mutations. Manager methods here return
    ``Dict[str, Any]`` (preview shape); bool fallback for completeness."""

    @staticmethod
    def serialize(obj) -> dict:
        if isinstance(obj, bool):
            return {"success": obj}
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        return {"result": str(obj)}
