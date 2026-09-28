"""Threat management mutation acknowledgement with persistence classification."""

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


@register_serializer(tools={"unifi_update_threat_management_settings": {"kind": RenderKind.DETAIL}})
class ThreatManagementMutationAckSerializer(Serializer):
    @staticmethod
    def serialize(obj) -> dict:
        return obj.to_dict()
