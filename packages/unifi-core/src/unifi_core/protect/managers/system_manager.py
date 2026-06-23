"""System management for UniFi Protect.

Provides methods to query NVR system information, health, viewers,
and firmware status from the pyunifiprotect bootstrap data.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from unifi_core.protect.managers.connection_manager import ProtectConnectionManager

logger = logging.getLogger(__name__)


class SystemManager:
    """Reads system-level data from the Protect NVR bootstrap."""

    def __init__(self, connection_manager: ProtectConnectionManager) -> None:
        self._cm = connection_manager

    @staticmethod
    def _bootstrap_collection(bootstrap: Any, name: str) -> Dict[str, Any]:
        """Return a Protect bootstrap device collection when present."""
        return getattr(bootstrap, name, None) or {}

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def get_system_info(self) -> Dict[str, Any]:
        """Return NVR model, version, uptime, and storage overview."""
        bootstrap = self._cm.client.bootstrap
        nvr = bootstrap.nvr

        uptime_seconds = int(nvr.uptime.total_seconds()) if nvr.uptime else None

        storage = nvr.storage_stats
        storage_info: Dict[str, Any] = {}
        if storage:
            recording = storage.recording_space
            storage_info = {
                "utilization_pct": storage.utilization,
                "recording_space_total_bytes": recording.total if recording else None,
                "recording_space_used_bytes": recording.used if recording else None,
                "recording_space_available_bytes": recording.available if recording else None,
                "capacity": str(storage.capacity) if storage.capacity else None,
                "remaining_capacity": str(storage.remaining_capacity) if storage.remaining_capacity else None,
            }

        return {
            "id": nvr.id,
            "name": nvr.name,
            "model": str(nvr.type),
            "hardware_platform": getattr(nvr, "hardware_platform", None),
            "firmware_version": nvr.firmware_version,
            "version": str(nvr.version),
            "host": str(nvr.host) if nvr.host else None,
            "mac": nvr.mac,
            "uptime_seconds": uptime_seconds,
            "up_since": nvr.up_since.isoformat() if nvr.up_since else None,
            "is_updating": nvr.is_updating,
            "storage": storage_info,
            "camera_count": len(self._bootstrap_collection(bootstrap, "cameras")),
            "light_count": len(self._bootstrap_collection(bootstrap, "lights")),
            "sensor_count": len(self._bootstrap_collection(bootstrap, "sensors")),
            "viewer_count": len(self._bootstrap_collection(bootstrap, "viewers")),
            "chime_count": len(self._bootstrap_collection(bootstrap, "chimes")),
        }

    async def get_health(self) -> Dict[str, Any]:
        """Return system health summary — CPU, memory, storage, temperature."""
        bootstrap = self._cm.client.bootstrap
        nvr = bootstrap.nvr
        sys_info = nvr.system_info

        cpu = sys_info.cpu
        memory = sys_info.memory
        storage = sys_info.storage

        return {
            "cpu": {
                "average_load": cpu.average_load,
                "temperature_c": cpu.temperature,
            },
            "memory": {
                "available_bytes": memory.available,
                "free_bytes": memory.free,
                "total_bytes": memory.total,
            },
            "storage": {
                "available_bytes": storage.available,
                "size_bytes": storage.size,
                "used_bytes": storage.used,
                "is_recycling": storage.is_recycling,
                "type": str(storage.type),
            },
            "is_updating": nvr.is_updating,
            "uptime_seconds": int(nvr.uptime.total_seconds()) if nvr.uptime else None,
        }

    async def list_viewers(self) -> list[Dict[str, Any]]:
        """Return a list of connected Protect viewers."""
        bootstrap = self._cm.client.bootstrap
        viewers = []
        for viewer in bootstrap.viewers.values():
            viewers.append(
                {
                    "id": viewer.id,
                    "name": viewer.name,
                    "type": viewer.type,
                    "mac": viewer.mac,
                    "host": str(viewer.host) if viewer.host else None,
                    "firmware_version": viewer.firmware_version,
                    "is_connected": viewer.is_connected,
                    "is_updating": viewer.is_updating,
                    "uptime_seconds": int(viewer.uptime.total_seconds()) if viewer.uptime else None,
                    "state": str(viewer.state) if hasattr(viewer, "state") else None,
                    "software_version": viewer.software_version if hasattr(viewer, "software_version") else None,
                    "liveview_id": viewer.liveview_id if hasattr(viewer, "liveview_id") else None,
                }
            )
        return viewers

    async def get_firmware_status(self) -> Dict[str, Any]:
        """Return firmware update availability for NVR and all devices."""
        bootstrap = self._cm.client.bootstrap
        nvr = bootstrap.nvr

        devices: list[Dict[str, Any]] = []

        # Collect firmware info from each device category
        device_collections = {
            "camera": self._bootstrap_collection(bootstrap, "cameras"),
            "light": self._bootstrap_collection(bootstrap, "lights"),
            "sensor": self._bootstrap_collection(bootstrap, "sensors"),
            "viewer": self._bootstrap_collection(bootstrap, "viewers"),
            "chime": self._bootstrap_collection(bootstrap, "chimes"),
            "bridge": self._bootstrap_collection(bootstrap, "bridges"),
            "doorlock": self._bootstrap_collection(bootstrap, "doorlocks"),
        }

        for category, collection in device_collections.items():
            for device in collection.values():
                latest_fw = getattr(device, "latest_firmware_version", None)
                current_fw = getattr(device, "firmware_version", None)
                has_update = latest_fw is not None and current_fw is not None and latest_fw != current_fw

                devices.append(
                    {
                        "id": device.id,
                        "name": device.name,
                        "type": category,
                        "model": device.type,
                        "current_firmware": current_fw,
                        "latest_firmware": latest_fw,
                        "update_available": has_update,
                        "is_updating": device.is_updating,
                    }
                )

        return {
            "nvr": {
                "id": nvr.id,
                "name": nvr.name,
                "current_firmware": nvr.firmware_version,
                "version": str(nvr.version),
                "is_updating": nvr.is_updating,
                "is_protect_updatable": nvr.is_protect_updatable,
                "is_ucore_updatable": nvr.is_ucore_updatable,
                "last_device_fw_check": (
                    nvr.last_device_fw_updates_checked_at.isoformat() if nvr.last_device_fw_updates_checked_at else None
                ),
            },
            "devices": devices,
            "total_devices": len(devices),
            "devices_with_updates": sum(1 for d in devices if d["update_available"]),
        }
