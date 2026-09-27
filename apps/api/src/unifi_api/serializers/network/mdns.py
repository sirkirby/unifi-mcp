"""mDNS settings mutation acknowledgement."""

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


@register_serializer(tools={"unifi_update_mdns_settings": {"kind": RenderKind.DETAIL}})
class MdnsMutationAckSerializer(Serializer):
    @staticmethod
    def serialize(obj) -> dict:
        return obj.to_dict()
