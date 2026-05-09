"""Network device mutation-ack serializer.

Phase 6 PR2 Task 20 migrated the read serializers to typed Strawberry classes
in ``unifi_api.graphql.types.network.device``:

- ``DeviceSerializer``           → ``Device``
- ``DeviceRadioSerializer``      → ``DeviceRadio``
- ``LldpNeighborSerializer``     → ``LldpNeighbors``
- ``RogueApSerializer``          → ``RogueAp``
- ``RfScanResultSerializer``     → ``RfScanResult``
- ``AvailableChannelSerializer`` → ``AvailableChannel``
- ``SpeedtestStatusSerializer``  → ``SpeedtestStatus``

Only the mutation-ack serializer remains here — Phase 6 is read-only and the
device-mutation tools continue to flow through REST ``/v1/actions/*`` via the
serializer registry's tool-name dispatch.
"""

from typing import Any

from unifi_api.serializers._base import RenderKind, Serializer, register_serializer


@register_serializer(
    tools={
        "unifi_adopt_device": {"kind": RenderKind.DETAIL},
        "unifi_force_provision_device": {"kind": RenderKind.DETAIL},
        "unifi_locate_device": {"kind": RenderKind.DETAIL},
        "unifi_reboot_device": {"kind": RenderKind.DETAIL},
        "unifi_rename_device": {"kind": RenderKind.DETAIL},
        "unifi_set_device_led": {"kind": RenderKind.DETAIL},
        "unifi_set_outlet_state": {"kind": RenderKind.DETAIL},
        "unifi_set_site_leds": {"kind": RenderKind.DETAIL},
        "unifi_toggle_device": {"kind": RenderKind.DETAIL},
        "unifi_trigger_rf_scan": {"kind": RenderKind.DETAIL},
        "unifi_trigger_speedtest": {"kind": RenderKind.DETAIL},
        "unifi_update_device_radio": {"kind": RenderKind.DETAIL},
        "unifi_upgrade_device": {"kind": RenderKind.DETAIL},
    },
)
class DeviceMutationAckSerializer(Serializer):
    """Generic ack for device-side mutations. All managers here return
    ``bool``; coerce to ``{"success": bool}`` to satisfy the DETAIL contract."""

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
