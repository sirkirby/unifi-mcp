"""Port forward mutation ack serializer.

Phase 6 PR2 Task 22 migrated the read shape (PortForward LIST + DETAIL) to
a Strawberry type at ``unifi_api.graphql.types.network.port_forward``. Only
the mutation ack remains here — it covers create/update/toggle/delete for
port forward rules.
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
        "unifi_create_port_forward": {"kind": RenderKind.DETAIL},
        "unifi_create_simple_port_forward": {"kind": RenderKind.DETAIL},
        "unifi_update_port_forward": {"kind": RenderKind.DETAIL},
        "unifi_toggle_port_forward": {"kind": RenderKind.DETAIL},
        "unifi_delete_port_forward": {"kind": RenderKind.DETAIL},
    },
)
class PortForwardMutationAckSerializer(Serializer):
    """DETAIL ack for port forward mutations.

    ``create_*`` returns a dict (or None); ``update_*`` / ``toggle_*`` /
    ``delete_*`` return ``bool`` (the manager result the /v1/actions
    dispatcher serializes)."""

    @staticmethod
    def serialize(obj) -> dict:
        if isinstance(obj, bool):
            return {"success": obj}
        if isinstance(obj, dict):
            return obj
        raw = getattr(obj, "raw", None)
        if isinstance(raw, dict):
            return raw
        if obj is None:
            return {"success": False}
        return {"result": str(obj)}
