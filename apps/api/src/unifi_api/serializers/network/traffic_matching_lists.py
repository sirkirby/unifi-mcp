"""Traffic matching list mutation ack serializer.

The read shape (list + get) is projected through the Strawberry type at
``unifi_api.graphql.types.network.traffic_matching_lists``; only the mutation
ack lives here — it covers create and delete.
"""

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


@register_serializer(
    tools={
        "unifi_create_traffic_matching_list": {"kind": RenderKind.DETAIL},
        "unifi_delete_traffic_matching_list": {"kind": RenderKind.DETAIL},
    },
)
class TrafficMatchingListMutationAckSerializer(Serializer):
    """DETAIL ack for traffic matching list mutations.

    ``create`` returns the created dict; ``delete`` returns ``bool``.
    """

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
