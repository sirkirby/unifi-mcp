"""Protect recognition mutation serializers."""

from typing import Any

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


@register_serializer(
    tools={
        "protect_update_known_face": {"kind": RenderKind.DETAIL},
        "protect_merge_known_faces": {"kind": RenderKind.DETAIL},
        "protect_delete_known_face": {"kind": RenderKind.DETAIL},
    },
)
class RecognitionMutationAckSerializer(Serializer):
    """Pass-through serializer for Known Face mutation acknowledgements."""

    @staticmethod
    def serialize(obj: Any) -> dict:
        if isinstance(obj, bool):
            return {"success": obj}
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        return {"result": str(obj)}
