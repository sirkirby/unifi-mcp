"""ACL rule mutation ack serializer.

Phase 6 PR2 Task 22 migrated the read shape (AclRule LIST + DETAIL) to a
Strawberry type at ``unifi_api.graphql.types.network.acl``. Only the
mutation ack remains here — it covers create/update/delete for ACL rules.
"""

from typing import Any

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


@register_serializer(
    tools={
        "unifi_create_acl_rule": {"kind": RenderKind.DETAIL},
        "unifi_update_acl_rule": {"kind": RenderKind.DETAIL},
        "unifi_delete_acl_rule": {"kind": RenderKind.DETAIL},
        "unifi_set_acl_rule_order": {"kind": RenderKind.DETAIL},
    },
)
class AclMutationAckSerializer(Serializer):
    """DETAIL ack for ACL rule mutations.

    ``create_acl_rule`` returns the created dict; update + delete return
    ``bool``."""

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
