"""ACL rule ordering mutation ack serializer.

The ordering read shape is projected through the Strawberry type at
``unifi_api.graphql.types.network.acl_ordering``; only the reorder ack lives
here.
"""

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


@register_serializer(
    tools={
        "unifi_reorder_acl_rules": {"kind": RenderKind.DETAIL},
    },
)
class AclOrderingMutationAckSerializer(Serializer):
    """DETAIL ack for the reorder call, which returns the applied ID order."""

    @staticmethod
    def serialize(obj) -> dict:
        if isinstance(obj, list) and all(isinstance(item, str) for item in obj):
            return {"ordered_acl_rule_ids": obj}
        if isinstance(obj, bool):
            return {"success": obj}
        raw = getattr(obj, "raw", None)
        if isinstance(raw, dict):
            return raw
        if isinstance(obj, dict):
            return obj
        return {"result": str(obj)}
