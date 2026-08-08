"""Network (LAN/VLAN) serializer.

Phase 6 PR2 Task 21 migrated the read shape (list/detail) to a Strawberry
type at ``unifi_api.graphql.types.network.network.Network``. Only the
mutation ack remains here.
"""

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


@register_serializer(
    tools={
        "unifi_create_network": {"kind": RenderKind.DETAIL},
        "unifi_update_network": {"kind": RenderKind.DETAIL},
        "unifi_delete_network": {"kind": RenderKind.DETAIL},
    },
)
class NetworkMutationAckSerializer(Serializer):
    """DETAIL ack for network create/update.

    Create/update return Core write-verification results; delete returns bool."""

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
