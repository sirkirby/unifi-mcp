"""Protect Alarm Manager mutation serializers.

Phase 6 PR3 Task B — the read serializers (``AlarmStatusSerializer``,
``AlarmProfileSerializer``) moved to Strawberry types in
``unifi_api.graphql.types.protect.alarms``. Their tools
(``protect_alarm_get_status``, ``protect_alarm_list_profiles``) are
listed in ``PHASE6_TYPE_MIGRATED_TOOLS`` and dispatched via the
type_registry by both REST routes and the action endpoint.

This module now only ships ``AlarmMutationAckSerializer`` for
arm/disarm preview-and-confirm tools, which still flow through the
manager's preview path and produce dict acks.
"""

from typing import Any

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


@register_serializer(
    tools={
        "protect_alarm_arm": {"kind": RenderKind.DETAIL},
        "protect_alarm_disarm": {"kind": RenderKind.DETAIL},
        "protect_alarm_update_rule": {"kind": RenderKind.DETAIL},
        "protect_alarm_create_rule": {"kind": RenderKind.DETAIL},
        "protect_alarm_delete_rule": {"kind": RenderKind.DETAIL},
    },
)
class AlarmMutationAckSerializer(Serializer):
    """Pass-through for alarm mutation acks (arm/disarm + rule CRUD).

    Coerces bare bools into ``{armed: bool}`` for backwards compatibility
    with the historical arm/disarm shapes. Rule-CRUD tools always return
    dicts (created/updated rule body or ``{deleted, rule_id}``) so they
    flow through identity.
    """

    kind = RenderKind.DETAIL

    @staticmethod
    def serialize(obj: Any) -> dict:
        if isinstance(obj, bool):
            return {"armed": obj}
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        return {"result": str(obj)}
