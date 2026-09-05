"""System mutation ack serializer (post-Phase-6-Task-23).

Phase 6 PR2 Task 23 migrated all nine read shapes (alarms, backups,
system info, network health, site settings, SNMP settings, event types,
auto-backup settings, top clients, speedtest results) to Strawberry types
at ``unifi_api.graphql.types.network.system``.

Only the mutation ack remains here — covering archive/backup/autobackup
mutations that pass through dict / coerce bool to ``{"success": <bool>}``.
"""

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


@register_serializer(
    tools={
        "unifi_archive_alarm": {"kind": RenderKind.DETAIL},
        "unifi_archive_all_alarms": {"kind": RenderKind.DETAIL},
        "unifi_create_backup": {"kind": RenderKind.DETAIL},
        "unifi_delete_backup": {"kind": RenderKind.DETAIL},
        "unifi_update_autobackup_settings": {"kind": RenderKind.DETAIL},
        "unifi_update_mgmt_settings": {"kind": RenderKind.DETAIL},
    },
)
class SystemMutationAckSerializer(Serializer):
    """DETAIL ack for system mutations.

    Managers return ``bool`` (archive/delete/update) or ``Optional[Dict]``
    (``create_backup``). Bool maps to ``{"success": <bool>}``; dicts pass
    through; ``None`` maps to ``{"success": False}``.
    """

    @staticmethod
    def serialize(obj) -> dict:
        if isinstance(obj, bool):
            return {"success": obj}
        if isinstance(obj, dict):
            return obj
        if obj is None:
            return {"success": False}
        raw = getattr(obj, "raw", None)
        if isinstance(raw, dict):
            return raw
        return {"result": str(obj)}
