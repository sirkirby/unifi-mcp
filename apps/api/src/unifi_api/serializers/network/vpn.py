"""VPN serializers (Phase 4A PR1 Cluster 3).

Phase 6 PR2 Task 21 migrated the read shapes (VPN client/server list + detail)
to Strawberry types at ``unifi_api.graphql.types.network.vpn``. Only the
mutation ack remains here.
"""

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


@register_serializer(
    tools={
        "unifi_update_vpn_client_state": {"kind": RenderKind.DETAIL},
        "unifi_delete_vpn_client": {"kind": RenderKind.DETAIL},
        "unifi_update_vpn_server_state": {"kind": RenderKind.DETAIL},
    },
)
class VpnMutationAckSerializer(Serializer):
    """DETAIL ack for VPN state-mutation tools.

    State updates return Core write-verification results; delete returns bool."""

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
