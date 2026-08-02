"""Access credential mutation serializers.

Phase 6 PR4 Task B — the read serializer (``CredentialSerializer``) moved
to a Strawberry type in ``unifi_api.graphql.types.access.credentials``.
The ``access_list_credentials`` / ``access_get_credential`` tools are
listed in ``PHASE6_TYPE_MIGRATED_TOOLS`` and dispatched via the
type_registry by both the REST routes and the action endpoint.

This module now only ships ``CredentialMutationAckSerializer`` for the
``access_create_credential`` / ``access_revoke_credential`` mutation tools.
The API action dispatcher invokes their manager mutation methods and
this serializer projects the resulting dict acknowledgements.
"""

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


@register_serializer(
    tools={
        "access_create_credential": {"kind": RenderKind.DETAIL},
        "access_revoke_credential": {"kind": RenderKind.DETAIL},
    },
)
class CredentialMutationAckSerializer(Serializer):
    """Pass-through ack for credential mutation dicts."""

    kind = RenderKind.DETAIL

    @staticmethod
    def serialize(obj) -> dict:
        if isinstance(obj, bool):
            return {"success": obj}
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        return {"result": str(obj)}
