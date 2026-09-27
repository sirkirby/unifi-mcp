"""Verified NAT mutation acknowledgement registration."""

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


@register_serializer(
    tools={
        "unifi_create_nat_rule": {"kind": RenderKind.DETAIL},
        "unifi_update_nat_rule": {"kind": RenderKind.DETAIL},
        "unifi_delete_nat_rule": {"kind": RenderKind.DETAIL},
        "unifi_toggle_nat_rule": {"kind": RenderKind.DETAIL},
    },
)
class NatMutationAckSerializer(Serializer):
    """The base serializer preserves WriteVerificationResult.success."""

    @staticmethod
    def serialize(obj) -> dict:
        if isinstance(obj, bool):
            return {"success": obj}
        if isinstance(obj, dict):
            return obj
        return {"success": False}
