"""Gateway (USG) settings serializer.

The read shape (detail) is projected by the Strawberry type at
``unifi_api.graphql.types.network.gateway_settings.GatewaySettings``. Only the
mutation ack for the update tool remains here.
"""

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


@register_serializer(
    tools={
        "unifi_update_gateway_settings": {"kind": RenderKind.DETAIL},
    },
)
class GatewaySettingsMutationAckSerializer(Serializer):
    """DETAIL ack for the gateway settings update tool.

    ``update_gateway_settings`` returns a result dict from the tool layer."""

    @staticmethod
    def serialize(obj) -> dict:
        if isinstance(obj, bool):
            return {"success": obj}
        if isinstance(obj, dict):
            return obj
        raw = getattr(obj, "raw", None)
        if isinstance(raw, dict):
            return raw
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        return {"result": str(obj)}
