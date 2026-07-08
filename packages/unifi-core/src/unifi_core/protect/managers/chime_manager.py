"""Chime management for UniFi Protect.

Provides methods to list, update, and trigger UniFi Protect chime devices
via the uiprotect bootstrap data.

Key API surface on ``Chime``:
- ``play(volume=None, repeat_times=None, ringtone_id=None, track_no=None)`` -- play chime tone
- ``play_buzzer()`` -- play buzzer sound
- ``set_volume(level)`` -- set speaker volume (deprecated, use set_volume_for_camera_public)
- ``set_repeat_times(value)`` -- set repeat count (deprecated, use set_ring_settings_public)
- ``ring_settings`` -- per-camera ring configuration
- ``speaker_track_list`` -- available ringtones/tracks
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from uiprotect.exceptions import ClientError

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.managers.connection_manager import ProtectConnectionManager
from unifi_core.protect.models.chimes import to_ring_setting_update

logger = logging.getLogger(__name__)


class ChimeManager:
    """Domain logic for UniFi Protect chimes."""

    def __init__(self, connection_manager: ProtectConnectionManager) -> None:
        self._cm = connection_manager

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_chime(self, chime_id: str):
        """Retrieve a Chime object by ID, raising UniFiNotFoundError if not found."""
        chimes = self._cm.client.bootstrap.chimes
        chime = chimes.get(chime_id)
        if chime is None:
            raise UniFiNotFoundError("chime", chime_id)
        return chime

    @staticmethod
    def _format_chime_summary(chime) -> Dict[str, Any]:
        """Format a chime into a summary dict with essential fields."""
        # Ring settings per camera
        ring_settings: List[Dict[str, Any]] = []
        for rs in chime.ring_settings or []:
            ring_settings.append(
                {
                    "camera_id": rs.camera_id,
                    "volume": rs.volume,
                    "repeat_times": rs.repeat_times,
                    "ringtone_id": rs.ringtone_id,
                    "track_no": rs.track_no,
                }
            )

        # Available tracks
        tracks: List[Dict[str, Any]] = []
        for track in chime.speaker_track_list or []:
            tracks.append(
                {
                    "track_no": track.track_no,
                    "name": track.name,
                    "state": track.state,
                }
            )

        return {
            "id": chime.id,
            "name": chime.name,
            "type": str(chime.type),
            "model": chime.market_name or str(chime.type),
            "state": str(chime.state.value) if chime.state else None,
            "is_connected": chime.is_connected,
            "firmware_version": chime.firmware_version,
            "last_seen": chime.last_seen.isoformat() if chime.last_seen else None,
            "volume": chime.volume,
            "last_ring": chime.last_ring.isoformat() if chime.last_ring else None,
            "camera_ids": list(chime.camera_ids) if chime.camera_ids else [],
            "repeat_times": chime.repeat_times,
            "ring_settings": ring_settings,
            "available_tracks": tracks,
        }

    @staticmethod
    def _get_public_value(obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    @staticmethod
    def _get_ring_setting_value(setting: Any, key: str) -> Any:
        aliases = {
            "camera_id": "cameraId",
            "repeat_times": "repeatTimes",
            "ringtone_id": "ringtoneId",
        }
        if isinstance(setting, dict):
            if key in setting:
                return setting[key]
            return setting.get(aliases.get(key, key))
        value = getattr(setting, key, None)
        enum_value = getattr(value, "value", None)
        return enum_value if enum_value is not None else value

    @classmethod
    def _ring_setting_to_agent(cls, setting: Any) -> Dict[str, Any]:
        data = {
            "camera_id": cls._get_ring_setting_value(setting, "camera_id"),
            "volume": cls._get_ring_setting_value(setting, "volume"),
            "repeat_times": cls._get_ring_setting_value(setting, "repeat_times"),
            "ringtone_id": cls._get_ring_setting_value(setting, "ringtone_id"),
        }
        return {key: value for key, value in data.items() if value is not None}

    @staticmethod
    def _raise_public_api_error(operation: str, chime_id: str, exc: Exception) -> None:
        message = str(exc)
        message_lower = message.lower()
        if "404" in message or "not found" in message_lower:
            raise UniFiNotFoundError("chime", chime_id) from exc
        raise ValueError(
            f"Failed to {operation} for chime {chime_id}: {message}. "
            "Verify the chime ID and camera ID with protect_list_chimes and ensure "
            "UNIFI_PROTECT_API_KEY or UNIFI_API_KEY has Protect public API access."
        ) from exc

    @classmethod
    def _find_ring_setting(cls, ring_settings: List[Dict[str, Any]], camera_id: str) -> Dict[str, Any] | None:
        for setting in ring_settings:
            if setting.get("camera_id") == camera_id:
                return setting
        return None

    @classmethod
    def _ring_setting_to_public_request(cls, chime_id: str, setting: Dict[str, Any]) -> Dict[str, Any]:
        camera_id = setting.get("camera_id")
        missing = [key for key in ("camera_id", "volume", "repeat_times") if setting.get(key) is None]
        if missing:
            joined = ", ".join(missing)
            raise ValueError(
                f"Cannot update chime ring settings for chime {chime_id}: current ring setting "
                f"for camera {camera_id or '<unknown>'} is missing required field(s): {joined}."
            )

        payload: Dict[str, Any] = {
            "cameraId": str(camera_id),
            "volume": int(setting["volume"]),
            "repeatTimes": int(setting["repeat_times"]),
        }
        if setting.get("ringtone_id") is not None:
            payload["ringtoneId"] = setting["ringtone_id"]
        return payload

    @classmethod
    def _prepare_ring_settings_update(
        cls,
        chime_id: str,
        public_chime: Any,
        settings: Dict[str, Any],
    ) -> Dict[str, Any]:
        ring_update = to_ring_setting_update(settings)
        camera_id = ring_update["camera_id"]
        camera_ids = cls._get_public_value(public_chime, "camera_ids") or []
        if camera_ids and camera_id not in camera_ids:
            raise ValueError(
                f"Camera {camera_id} is not paired with chime {chime_id}. "
                "Verify camera_id and chime_id with protect_list_chimes."
            )

        raw_ring_settings = cls._get_public_value(public_chime, "ring_settings") or []
        ring_settings = [cls._ring_setting_to_agent(item) for item in raw_ring_settings]
        current = cls._find_ring_setting(ring_settings, camera_id)
        if current is None:
            raise ValueError(
                f"Camera {camera_id} does not have a ring setting on chime {chime_id}. "
                "Verify camera_id and chime_id with protect_list_chimes."
            )

        proposed = dict(current)
        for key in ("volume", "repeat_times"):
            if key in ring_update:
                proposed[key] = ring_update[key]

        request_ring_settings: List[Dict[str, Any]] = []
        preserved_ring_settings: List[Dict[str, Any]] = []
        for setting in ring_settings:
            item = proposed if setting.get("camera_id") == camera_id else setting
            request_ring_settings.append(cls._ring_setting_to_public_request(chime_id, item))
            if setting.get("camera_id") != camera_id:
                preserved_ring_settings.append(setting)

        return {
            "camera_id": camera_id,
            "current": current,
            "proposed": proposed,
            "request_ring_settings": request_ring_settings,
            "preserved_ring_settings": preserved_ring_settings,
        }

    # ------------------------------------------------------------------
    # Read-only methods
    # ------------------------------------------------------------------

    async def list_chimes(self) -> List[Dict[str, Any]]:
        """Return all chimes as summary dicts."""
        chimes = self._cm.client.bootstrap.chimes
        return [self._format_chime_summary(chime) for chime in chimes.values()]

    # ------------------------------------------------------------------
    # Mutation methods (preview / apply)
    # ------------------------------------------------------------------

    async def update_chime(self, chime_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Return current and proposed chime state for preview.

        Supported settings keys:
        - volume: int (0-100) -- speaker volume
        - repeat_times: int (1-6) -- how many times to repeat ring
        - name: str -- device name
        - camera_id: str -- when supplied, volume/repeat_times apply to that camera's ring setting
        """
        if "camera_id" in settings:
            self._cm.require_public_api_key("update chime ring settings")
            try:
                public_chime = await self._cm.client.get_chime_public(chime_id)
            except ClientError as exc:
                self._raise_public_api_error("preview chime ring settings update", chime_id, exc)
            prepared = self._prepare_ring_settings_update(chime_id, public_chime, settings)
            return {
                "chime_id": chime_id,
                "chime_name": self._get_public_value(public_chime, "name") or chime_id,
                "current_state": prepared["current"],
                "proposed_changes": prepared["proposed"],
                "preserved_ring_settings": prepared["preserved_ring_settings"],
            }

        chime = self._get_chime(chime_id)

        current_state: Dict[str, Any] = {}
        proposed_changes: Dict[str, Any] = {}

        for key, value in settings.items():
            if key == "volume":
                current_state["volume"] = chime.volume
                proposed_changes["volume"] = value
            elif key == "repeat_times":
                current_state["repeat_times"] = chime.repeat_times
                proposed_changes["repeat_times"] = value
            elif key == "name":
                current_state["name"] = chime.name
                proposed_changes["name"] = value
            else:
                logger.warning("Unknown chime setting key: %s", key)

        return {
            "chime_id": chime_id,
            "chime_name": chime.name,
            "current_state": current_state,
            "proposed_changes": proposed_changes,
        }

    async def apply_chime_settings(self, chime_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Apply chime settings after confirmation."""
        if "camera_id" in settings:
            self._cm.require_public_api_key("update chime ring settings")
            try:
                public_chime = await self._cm.client.get_chime_public(chime_id)
                prepared = self._prepare_ring_settings_update(chime_id, public_chime, settings)
                updated = await self._cm.client.update_chime_public(
                    chime_id,
                    ring_settings=prepared["request_ring_settings"],
                )
            except ClientError as exc:
                self._raise_public_api_error("update chime ring settings", chime_id, exc)

            updated_ring_settings = [
                self._ring_setting_to_agent(item) for item in (self._get_public_value(updated, "ring_settings") or [])
            ]
            updated_state = (
                self._find_ring_setting(
                    updated_ring_settings,
                    prepared["camera_id"],
                )
                or prepared["proposed"]
            )
            return {
                "chime_id": chime_id,
                "chime_name": self._get_public_value(updated, "name")
                or self._get_public_value(public_chime, "name")
                or chime_id,
                "applied": prepared["proposed"],
                "updated_state": updated_state,
            }

        chime = self._get_chime(chime_id)
        applied: List[str] = []
        errors: List[str] = []

        for key, value in settings.items():
            try:
                if key == "volume":
                    await chime.set_volume(int(value))
                    applied.append(f"volume={value}")
                elif key == "repeat_times":
                    await chime.set_repeat_times(int(value))
                    applied.append(f"repeat_times={value}")
                elif key == "name":
                    await chime.set_name(str(value))
                    applied.append(f"name={value}")
                else:
                    errors.append(f"Unknown setting: {key}")
            except Exception as exc:
                logger.error("Error applying chime setting %s=%s: %s", key, value, exc, exc_info=True)
                errors.append(f"{key}: {exc}")

        result: Dict[str, Any] = {
            "chime_id": chime_id,
            "chime_name": chime.name,
            "applied": applied,
        }
        if errors:
            result["errors"] = errors

        return result

    async def trigger_chime(
        self,
        chime_id: str,
        volume: Optional[int] = None,
        repeat_times: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Play the chime tone.

        Uses the Chime.play() API to trigger the sound.
        """
        chime = self._get_chime(chime_id)

        kwargs: Dict[str, Any] = {}
        if volume is not None:
            kwargs["volume"] = volume
        if repeat_times is not None:
            kwargs["repeat_times"] = repeat_times

        await chime.play(**kwargs)

        return {
            "chime_id": chime_id,
            "chime_name": chime.name,
            "triggered": True,
            "volume": volume if volume is not None else chime.volume,
            "repeat_times": repeat_times if repeat_times is not None else chime.repeat_times,
        }
