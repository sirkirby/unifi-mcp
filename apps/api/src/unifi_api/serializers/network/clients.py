"""Network client mutation-ack serializer.

Phase 6 PR2 Task 19 migrated the read serializers (``ClientSerializer``,
``BlockedClientSerializer``, ``ClientLookupSerializer``) to typed Strawberry
classes in ``unifi_api.graphql.types.network.client``. Only the mutation-ack
serializer remains here — Phase 6 is read-only and the eight client-mutation
tools continue to flow through REST ``/v1/actions/*`` via the serializer
registry's tool-name dispatch.
"""

from typing import Any

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


@register_serializer(
    tools={
        "unifi_block_client": {"kind": RenderKind.DETAIL},
        "unifi_unblock_client": {"kind": RenderKind.DETAIL},
        "unifi_forget_client": {"kind": RenderKind.DETAIL},
        "unifi_rename_client": {"kind": RenderKind.DETAIL},
        "unifi_force_reconnect_client": {"kind": RenderKind.DETAIL},
        "unifi_set_client_ip_settings": {"kind": RenderKind.DETAIL},
        "unifi_set_client_fixed_ap": {"kind": RenderKind.DETAIL},
        "unifi_authorize_guest": {"kind": RenderKind.DETAIL},
        "unifi_unauthorize_guest": {"kind": RenderKind.DETAIL},
    },
)
class ClientMutationAckSerializer(Serializer):
    """Generic ack for client-side mutations. All underlying managers
    return ``bool`` — coerce to ``{"success": bool}``."""

    @staticmethod
    def serialize(obj: Any) -> dict:
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
