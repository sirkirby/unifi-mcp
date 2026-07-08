"""Sensor management for UniFi Protect.

Provides methods to list UniFi Protect sensor devices (motion, door/window,
temperature, humidity, light level, leak detection) via the uiprotect
bootstrap data and update settings through the Protect public API.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from uiprotect.exceptions import ClientError

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.managers.connection_manager import ProtectConnectionManager
from unifi_core.protect.models.sensors import to_agent_update

logger = logging.getLogger(__name__)


class SensorManager:
    """Domain logic for UniFi Protect sensors."""

    def __init__(self, connection_manager: ProtectConnectionManager) -> None:
        self._cm = connection_manager

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_sensor_summary(sensor) -> Dict[str, Any]:
        """Format a sensor into a summary dict with essential fields."""
        # Battery status
        battery: Dict[str, Any] = {}
        if sensor.battery_status:
            battery = {
                "percentage": sensor.battery_status.percentage,
                "is_low": sensor.battery_status.is_low,
            }

        # Stats (light, humidity, temperature readings)
        stats: Dict[str, Any] = {}
        if sensor.stats:
            for stat_name in ("light", "humidity", "temperature"):
                stat = getattr(sensor.stats, stat_name, None)
                if stat:
                    stats[stat_name] = {
                        "value": stat.value,
                        "status": str(stat.status.value) if stat.status else None,
                    }

        return {
            "id": sensor.id,
            "name": sensor.name,
            "type": str(sensor.type),
            "model": sensor.market_name or str(sensor.type),
            "state": str(sensor.state.value) if sensor.state else None,
            "is_connected": sensor.is_connected,
            "firmware_version": sensor.firmware_version,
            "last_seen": sensor.last_seen.isoformat() if sensor.last_seen else None,
            "mount_type": str(sensor.mount_type.value) if sensor.mount_type else None,
            "is_motion_detected": sensor.is_motion_detected,
            "is_opened": sensor.is_opened,
            "motion_detected_at": (sensor.motion_detected_at.isoformat() if sensor.motion_detected_at else None),
            "open_status_changed_at": (
                sensor.open_status_changed_at.isoformat() if sensor.open_status_changed_at else None
            ),
            "alarm_triggered_at": (sensor.alarm_triggered_at.isoformat() if sensor.alarm_triggered_at else None),
            "leak_detected_at": (sensor.leak_detected_at.isoformat() if sensor.leak_detected_at else None),
            "tampering_detected_at": (
                sensor.tampering_detected_at.isoformat() if sensor.tampering_detected_at else None
            ),
            "battery": battery,
            "stats": stats,
            "camera_id": sensor.camera_id,
        }

    @staticmethod
    def _get_public_value(sensor: Any, key: str) -> Any:
        if isinstance(sensor, dict):
            return sensor.get(key)
        return getattr(sensor, key, None)

    @classmethod
    def _serialize_public_value(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: cls._serialize_public_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [cls._serialize_public_value(v) for v in value]
        if isinstance(value, tuple):
            return [cls._serialize_public_value(v) for v in value]
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return model_dump(mode="json", exclude_none=True)
        enum_value = getattr(value, "value", None)
        if enum_value is not None:
            return enum_value
        return value

    @staticmethod
    def _raise_public_api_error(operation: str, sensor_id: str, exc: Exception) -> None:
        message = str(exc)
        message_lower = message.lower()
        if "404" in message or "not found" in message_lower:
            raise UniFiNotFoundError("sensor", sensor_id) from exc
        raise ValueError(
            f"Failed to {operation} for sensor {sensor_id}: {message}. "
            "Verify the sensor ID with protect_list_sensors and ensure "
            "UNIFI_PROTECT_API_KEY or UNIFI_API_KEY has Protect public API access."
        ) from exc

    # ------------------------------------------------------------------
    # Read-only methods
    # ------------------------------------------------------------------

    async def list_sensors(self) -> List[Dict[str, Any]]:
        """Return all sensors as summary dicts."""
        sensors = self._cm.client.bootstrap.sensors
        return [self._format_sensor_summary(sensor) for sensor in sensors.values()]

    # ------------------------------------------------------------------
    # Mutation methods (preview / apply)
    # ------------------------------------------------------------------

    async def update_sensor_settings(self, sensor_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Return current and proposed sensor settings for preview."""
        self._cm.require_public_api_key("update sensor settings")
        try:
            sensor = await self._cm.client.get_sensor_public(sensor_id)
        except ClientError as exc:
            self._raise_public_api_error("preview sensor settings update", sensor_id, exc)

        current_state = to_agent_update(
            {key: self._serialize_public_value(self._get_public_value(sensor, key)) for key in settings.keys()}
        )
        proposed_changes = to_agent_update(
            {key: self._serialize_public_value(value) for key, value in settings.items()}
        )
        sensor_name = self._get_public_value(sensor, "name") or sensor_id

        return {
            "sensor_id": sensor_id,
            "sensor_name": sensor_name,
            "current_state": current_state,
            "proposed_changes": proposed_changes,
        }

    async def apply_sensor_settings(self, sensor_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Apply sensor settings through the Protect public API after confirmation."""
        self._cm.require_public_api_key("update sensor settings")
        try:
            sensor = await self._cm.client.update_sensor_public(sensor_id, **settings)
        except ClientError as exc:
            self._raise_public_api_error("update sensor settings", sensor_id, exc)

        sensor_name = self._get_public_value(sensor, "name") or sensor_id
        updated_state = to_agent_update(
            {key: self._serialize_public_value(self._get_public_value(sensor, key)) for key in settings.keys()}
        )

        return {
            "sensor_id": sensor_id,
            "sensor_name": sensor_name,
            "applied": to_agent_update({key: self._serialize_public_value(value) for key, value in settings.items()}),
            "updated_state": updated_state,
        }
