"""Dynamic DNS serializers.

The read shape (list/detail) lives in the Strawberry type at
``unifi_api.graphql.types.network.dynamic_dns.DynamicDns``. Only the
mutation ack is served here, for the create/update/delete tools.
"""

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


@register_serializer(
    tools={
        "unifi_create_dynamic_dns": {"kind": RenderKind.DETAIL},
        "unifi_update_dynamic_dns": {"kind": RenderKind.DETAIL},
        "unifi_delete_dynamic_dns": {"kind": RenderKind.DETAIL},
    },
)
class DynamicDnsMutationAckSerializer(Serializer):
    """DETAIL ack for Dynamic DNS create/update/delete operations.

    ``create_dynamic_dns`` returns the created dict; ``update_*`` / ``delete_*``
    return ``bool``. Coerce both to a DETAIL-shaped payload."""

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
