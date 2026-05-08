"""Firewall mutation ack serializer.

Phase 6 PR2 Task 22 migrated the read shapes (firewall rules, firewall groups,
firewall zones) to Strawberry types at
``unifi_api.graphql.types.network.firewall``. Only the cross-cutting mutation
ack remains here — it covers create/update/delete/toggle for both firewall
policies and firewall groups.
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
        "unifi_create_firewall_policy": {"kind": RenderKind.DETAIL},
        "unifi_update_firewall_policy": {"kind": RenderKind.DETAIL},
        "unifi_delete_firewall_policy": {"kind": RenderKind.DETAIL},
        "unifi_toggle_firewall_policy": {"kind": RenderKind.DETAIL},
        "unifi_create_firewall_group": {"kind": RenderKind.DETAIL},
        "unifi_update_firewall_group": {"kind": RenderKind.DETAIL},
        "unifi_delete_firewall_group": {"kind": RenderKind.DETAIL},
    },
)
class FirewallMutationAckSerializer(Serializer):
    """DETAIL ack for firewall policy + group mutations.

    ``create_*`` returns a dict or ``FirewallPolicy``; ``update_*`` /
    ``delete_*`` / ``toggle_*`` return ``bool``."""

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
