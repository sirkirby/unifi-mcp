"""Camera management for UniFi Protect.

Provides methods to query camera state, fetch snapshots, manage streams,
update settings, and control PTZ functions via the pyunifiprotect bootstrap data.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from typing import Any, Dict, List, Optional

from uiprotect.data.types import IRLEDMode, PublicHdrMode, RecordingMode

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.managers.connection_manager import ProtectConnectionManager
from unifi_core.protect.models.cameras import normalize_hdr_mode, to_controller_update

logger = logging.getLogger(__name__)

PTZ_MIN_SPEED = -1000
PTZ_MAX_SPEED = 1000
PTZ_MAX_DURATION_MS = 5000

# Public kind -> raw camera key. Protect has no uiprotect model for these.
DETECTION_AREA_KINDS = {
    "line": "smartDetectLines",
    "zone": "smartDetectZones",
    "loiter_zone": "smartDetectLoiterZones",
}


class CameraManager:
    """Reads and mutates camera data from the Protect NVR bootstrap."""

    def __init__(self, connection_manager: ProtectConnectionManager) -> None:
        self._cm = connection_manager

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_camera(self, camera_id: str):
        """Retrieve a Camera object by ID, raising UniFiNotFoundError if not found."""
        cameras = self._cm.client.bootstrap.cameras
        camera = cameras.get(camera_id)
        if camera is None:
            raise UniFiNotFoundError("camera", camera_id)
        return camera

    @staticmethod
    def _is_ptz(camera) -> bool:
        return (
            bool(camera.feature_flags.is_ptz)
            if camera.feature_flags and hasattr(camera.feature_flags, "is_ptz")
            else False
        )

    def _get_ptz_camera(self, camera_id: str):
        camera = self._get_camera(camera_id)
        if not self._is_ptz(camera):
            raise ValueError(f"Camera {camera_id} ({camera.name}) does not support PTZ")
        return camera

    @staticmethod
    def _validate_ptz_speed(value: Optional[float], field: str) -> int:
        speed = int(value or 0)
        if speed < PTZ_MIN_SPEED or speed > PTZ_MAX_SPEED:
            raise ValueError(f"{field} must be between {PTZ_MIN_SPEED} and {PTZ_MAX_SPEED}")
        return speed

    @staticmethod
    def _validate_ptz_duration(duration_ms: int) -> int:
        duration = int(duration_ms)
        if duration < 0 or duration > PTZ_MAX_DURATION_MS:
            raise ValueError(f"duration_ms must be between 0 and {PTZ_MAX_DURATION_MS}")
        return duration

    async def _send_ptz_continuous(
        self,
        camera_id: str,
        *,
        x: int = 0,
        y: int = 0,
        z: int = 0,
        duration_ms: int = 250,
    ) -> Dict[str, Any]:
        """Send a UniFi Protect PTZ continuous-move command and stop after duration."""
        payload = {"type": "continuous", "payload": {"x": x, "y": y, "z": z}}
        result = await self._cm.client.api_request(f"cameras/{camera_id}/move", method="post", json=payload)

        if duration_ms and any((x, y, z)):
            await asyncio.sleep(duration_ms / 1000)
            stop_payload = {"type": "continuous", "payload": {"x": 0, "y": 0, "z": 0}}
            await self._cm.client.api_request(f"cameras/{camera_id}/move", method="post", json=stop_payload)

        return {"command": payload, "controller_response": result}

    @staticmethod
    def _format_camera_summary(camera) -> Dict[str, Any]:
        """Format a camera into a summary dict with essential fields."""
        recording_mode = None
        if camera.recording_settings:
            recording_mode = str(camera.recording_settings.mode.value)

        return {
            "id": camera.id,
            "name": camera.name,
            "type": str(camera.type),
            "model": camera.market_name or str(camera.type),
            "state": str(camera.state.value) if camera.state else None,
            "is_connected": camera.is_connected,
            "last_seen": camera.last_seen.isoformat() if camera.last_seen else None,
            "recording_mode": recording_mode,
            "is_recording": camera.is_recording,
            "is_ptz": CameraManager._is_ptz(camera),
        }

    # ------------------------------------------------------------------
    # Read-only methods
    # ------------------------------------------------------------------

    async def list_cameras(self) -> List[Dict[str, Any]]:
        """Return all cameras as summary dicts."""
        cameras = self._cm.client.bootstrap.cameras
        return [self._format_camera_summary(cam) for cam in cameras.values()]

    async def get_camera(self, camera_id: str) -> Dict[str, Any]:
        """Return detailed information for a single camera."""
        camera = self._get_camera(camera_id)

        summary = self._format_camera_summary(camera)

        # ISP settings
        isp = camera.isp_settings
        ir_led_mode = str(isp.ir_led_mode.value) if isp and isp.ir_led_mode else None
        hdr_mode_value = None
        if isp and isp.hdr_mode is not None:
            hdr_mode_value = str(isp.hdr_mode.value)

        # Channel info
        channels = []
        for ch in camera.channels:
            channels.append(
                {
                    "id": ch.id,
                    "name": ch.name,
                    "enabled": ch.enabled,
                    "is_rtsp_enabled": ch.is_rtsp_enabled,
                    "width": ch.width,
                    "height": ch.height,
                    "fps": ch.fps,
                    "bitrate": ch.bitrate,
                }
            )

        # Smart detection info
        smart_detect_types = []
        if camera.smart_detect_settings and camera.smart_detect_settings.object_types:
            smart_detect_types = [str(t.value) for t in camera.smart_detect_settings.object_types]

        # Feature flags for capabilities
        is_ptz = self._is_ptz(camera)

        detail = {
            **summary,
            "firmware_version": camera.firmware_version,
            "ip_address": str(camera.host) if camera.host else None,
            "mac": camera.mac,
            "up_since": camera.up_since.isoformat() if camera.up_since else None,
            "uptime_seconds": int(camera.uptime.total_seconds()) if camera.uptime else None,
            "mic_enabled": camera.is_mic_enabled,
            "mic_volume": camera.mic_volume,
            "status_light_enabled": camera.led_settings.is_enabled if camera.led_settings else None,
            "ir_led_mode": ir_led_mode,
            "hdr_mode": hdr_mode_value,
            "video_mode": str(camera.video_mode.value) if camera.video_mode else None,
            "is_dark": camera.is_dark,
            "is_motion_detected": camera.is_motion_detected,
            "last_motion": camera.last_motion.isoformat() if camera.last_motion else None,
            "smart_detect_types": smart_detect_types,
            "is_ptz": is_ptz,
            "channels": channels,
            "has_speaker": camera.has_speaker,
            "has_wifi": camera.has_wifi,
            "speaker_volume": camera.speaker_settings.volume if camera.speaker_settings else None,
        }

        return detail

    async def get_snapshot(self, camera_id: str, width: Optional[int] = None, height: Optional[int] = None) -> bytes:
        """Fetch a JPEG snapshot from the camera.

        Returns raw JPEG bytes. The tool layer handles base64 encoding.
        """
        camera = self._get_camera(camera_id)
        snapshot = await camera.get_snapshot(width=width, height=height)
        if snapshot is None:
            raise RuntimeError(f"Failed to get snapshot from camera {camera_id}: camera returned None")
        return snapshot

    async def get_camera_streams(self, camera_id: str) -> Dict[str, Any]:
        """Extract RTSP/RTSPS stream information from camera channels.

        Returns channel-based stream info. For RTSPS URLs via public API,
        the camera must have RTSP enabled on the desired channel.
        """
        camera = self._get_camera(camera_id)

        streams: Dict[str, Any] = {}
        for ch in camera.channels:
            if ch.is_rtsp_enabled and ch.rtsp_alias:
                streams[ch.name] = {
                    "channel_id": ch.id,
                    "enabled": ch.enabled,
                    "rtsp_alias": ch.rtsp_alias,
                    **self._rtsp_stream_urls(ch.rtsp_alias),
                    "width": ch.width,
                    "height": ch.height,
                    "fps": ch.fps,
                    "bitrate": ch.bitrate,
                }

        # Also try to get RTSPS streams from the public API if available
        rtsps_info: Dict[str, Any] = {}
        try:
            rtsps = await camera.get_rtsps_streams()
            if rtsps:
                for quality in rtsps.get_active_stream_qualities():
                    url = rtsps.get_stream_url(quality)
                    if url:
                        rtsps_info[quality] = url
        except Exception as exc:
            logger.debug("Could not fetch RTSPS streams for camera %s: %s", camera_id, exc)

        return {
            "camera_id": camera_id,
            "camera_name": camera.name,
            "channels": streams,
            "rtsps_streams": rtsps_info,
        }

    async def get_camera_analytics(self, camera_id: str) -> Dict[str, Any]:
        """Get motion/smart detection analytics for a camera.

        Returns current detection state and last-detected timestamps.
        Full analytics history is not available via pyunifiprotect;
        use the events API for historical data.
        """
        camera = self._get_camera(camera_id)

        # Current detection state
        detections: Dict[str, Any] = {
            "is_motion_detected": camera.is_motion_detected,
            "is_smart_detected": camera.is_smart_detected,
            "last_motion": camera.last_motion.isoformat() if camera.last_motion else None,
        }

        # Smart detection details
        smart_detects: Dict[str, str] = {}
        if camera.last_smart_detects:
            for detect_type, timestamp in camera.last_smart_detects.items():
                smart_detects[str(detect_type.value)] = timestamp.isoformat()

        smart_audio_detects: Dict[str, str] = {}
        if camera.last_smart_audio_detects:
            for detect_type, timestamp in camera.last_smart_audio_detects.items():
                smart_audio_detects[str(detect_type.value)] = timestamp.isoformat()

        # Current smart detection boolean flags
        detection_flags: Dict[str, bool] = {
            "person": camera.is_person_currently_detected,
            "vehicle": camera.is_vehicle_currently_detected,
            "animal": camera.is_animal_currently_detected,
        }

        # Additional detection types if supported
        for attr, label in [
            ("is_package_currently_detected", "package"),
            ("is_face_currently_detected", "face"),
            ("is_license_plate_currently_detected", "license_plate"),
        ]:
            if hasattr(camera, attr):
                detection_flags[label] = getattr(camera, attr)

        # Motion zones count
        motion_zone_count = len(camera.motion_zones) if camera.motion_zones else 0
        smart_zone_count = len(camera.smart_detect_zones) if camera.smart_detect_zones else 0

        # Recording stats from camera stats if available
        stats_info: Dict[str, Any] = {}
        if camera.stats:
            stats = camera.stats
            if hasattr(stats, "video") and stats.video:
                video = stats.video
                stats_info["video"] = {
                    "recording_start": video.recording_start.isoformat()
                    if hasattr(video, "recording_start") and video.recording_start
                    else None,
                    "recording_end": video.recording_end.isoformat()
                    if hasattr(video, "recording_end") and video.recording_end
                    else None,
                    "timelapse_start": video.timelapse_start.isoformat()
                    if hasattr(video, "timelapse_start") and video.timelapse_start
                    else None,
                    "timelapse_end": video.timelapse_end.isoformat()
                    if hasattr(video, "timelapse_end") and video.timelapse_end
                    else None,
                }
            if hasattr(stats, "storage") and stats.storage:
                stats_info["storage_used_bytes"] = stats.storage.used if hasattr(stats.storage, "used") else None

        return {
            "camera_id": camera_id,
            "camera_name": camera.name,
            "detections": detections,
            "smart_detects": smart_detects,
            "smart_audio_detects": smart_audio_detects,
            "currently_detected": detection_flags,
            "motion_zone_count": motion_zone_count,
            "smart_detect_zone_count": smart_zone_count,
            "stats": stats_info,
            "note": "For historical event data, use the events API tools.",
        }

    # ------------------------------------------------------------------
    # Mutation methods
    # ------------------------------------------------------------------

    async def _validate_settings(self, camera, settings: Dict[str, Any]) -> Dict[str, Any]:
        settings = to_controller_update(settings)
        if not settings:
            raise ValueError("No supported camera settings provided")
        if "ir_led_mode" in settings:
            IRLEDMode(settings["ir_led_mode"])
        if "hdr_mode" in settings and not camera.feature_flags.has_hdr:
            raise ValueError("Cannot update HDR: this camera does not support HDR")
        if "mic_volume" in settings and not camera.feature_flags.has_mic:
            raise ValueError("Cannot update microphone volume: this camera has no microphone")
        if settings.keys() & {"hdr_mode", "mic_volume"}:
            self._cm.require_public_api_key("update camera HDR or microphone volume")
            await self._cm.validate_public_id_portability(
                resource_type="cameras", bootstrap_collection="cameras", public_list_method="get_cameras_public"
            )
        return settings

    async def update_camera_settings(self, camera_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Update camera settings. Returns dict with current and proposed state.

        Supported settings keys:
        - ir_led_mode: str (auto, on, off, autoFilterOnly)
        - hdr_mode: str (auto, off, always)
        - mic_enabled: bool
        - mic_volume: int (1-100; public API requires an API key)
        - status_light_on: bool
        - speaker_volume: int (0-100)
        - name: str
        - motion_detection: bool
        """
        camera = self._get_camera(camera_id)
        settings = await self._validate_settings(camera, settings)

        current_state: Dict[str, Any] = {}
        proposed_changes: Dict[str, Any] = {}

        for key, value in settings.items():
            if key == "ir_led_mode":
                current_state["ir_led_mode"] = str(camera.isp_settings.ir_led_mode.value)
                proposed_changes["ir_led_mode"] = value
            elif key == "hdr_mode":
                current_isp_hdr = camera.isp_settings.hdr_mode
                current_state["hdr_mode"] = (
                    "off"
                    if not camera.hdr_mode
                    else normalize_hdr_mode(current_isp_hdr.value)
                    if current_isp_hdr
                    else None
                )
                # Normalize so the preview shows what will actually be applied
                # (and rejects invalid values before confirmation).
                proposed_changes["hdr_mode"] = normalize_hdr_mode(value)
            elif key == "mic_enabled":
                current_state["mic_enabled"] = camera.is_mic_enabled
                proposed_changes["mic_enabled"] = value
            elif key == "mic_volume":
                current_state["mic_volume"] = camera.mic_volume
                proposed_changes["mic_volume"] = value
            elif key == "status_light_on":
                current_state["status_light_on"] = camera.led_settings.is_enabled if camera.led_settings else None
                proposed_changes["status_light_on"] = value
            elif key == "speaker_volume":
                current_vol = camera.speaker_settings.volume if camera.speaker_settings else None
                current_state["speaker_volume"] = current_vol
                proposed_changes["speaker_volume"] = value
            elif key == "name":
                current_state["name"] = camera.name
                proposed_changes["name"] = value
            elif key == "motion_detection":
                current_state["motion_detection"] = camera.is_motion_detection_on
                proposed_changes["motion_detection"] = value
            else:
                logger.warning("Unknown camera setting key: %s", key)

        return {
            "camera_id": camera_id,
            "camera_name": camera.name,
            "current_state": current_state,
            "proposed_changes": proposed_changes,
        }

    async def apply_camera_settings(self, camera_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Apply camera settings after confirmation.

        Calls the appropriate pyunifiprotect setter methods.
        """
        camera = self._get_camera(camera_id)
        settings = await self._validate_settings(camera, settings)
        applied: List[str] = []
        errors: List[str] = []

        for key, value in settings.items():
            try:
                if key == "ir_led_mode":
                    mode = IRLEDMode(value)
                    await camera.set_ir_led_model(mode)
                    applied.append(f"ir_led_mode={value}")
                elif key == "hdr_mode":
                    mode = normalize_hdr_mode(value)
                    await camera.set_hdr_mode_public(PublicHdrMode.ON if mode == "always" else PublicHdrMode(mode))
                    applied.append(f"hdr_mode={mode}")
                elif key == "mic_enabled":
                    # Microphone enablement remains a separate session-auth setting.
                    data_before = camera.dict_with_excludes()
                    camera.is_mic_enabled = value
                    await camera.save_device(data_before)
                    applied.append(f"mic_enabled={value}")
                elif key == "mic_volume":
                    await camera.set_mic_volume_public(value)
                    applied.append(f"mic_volume={value}")
                elif key == "status_light_on":
                    await camera.set_status_light(bool(value))
                    applied.append(f"status_light_on={value}")
                elif key == "speaker_volume":
                    await camera.set_speaker_volume(int(value))
                    applied.append(f"speaker_volume={value}")
                elif key == "name":
                    await camera.set_name(str(value))
                    applied.append(f"name={value}")
                elif key == "motion_detection":
                    await camera.set_motion_detection(bool(value))
                    applied.append(f"motion_detection={value}")
                else:
                    errors.append(f"Unknown setting: {key}")
            except Exception as exc:
                logger.error("Failed to apply camera setting %s (%s)", key, type(exc).__name__)
                errors.append(f"{key}: {exc}")

        result: Dict[str, Any] = {
            "camera_id": camera_id,
            "camera_name": camera.name,
            "applied": applied,
        }
        if errors:
            result["errors"] = errors

        return result

    async def toggle_recording(self, camera_id: str, enabled: bool) -> Dict[str, Any]:
        """Return current and proposed recording state for preview."""
        camera = self._get_camera(camera_id)
        current_mode = str(camera.recording_settings.mode.value) if camera.recording_settings else "unknown"
        proposed_mode = RecordingMode.ALWAYS.value if enabled else RecordingMode.NEVER.value

        return {
            "camera_id": camera_id,
            "camera_name": camera.name,
            "current_recording_mode": current_mode,
            "proposed_recording_mode": proposed_mode,
            "is_recording": camera.is_recording,
        }

    async def apply_toggle_recording(self, camera_id: str, enabled: bool) -> Dict[str, Any]:
        """Apply recording mode change after confirmation."""
        camera = self._get_camera(camera_id)
        mode = RecordingMode.ALWAYS if enabled else RecordingMode.NEVER
        await camera.set_recording_mode(mode)
        return {
            "camera_id": camera_id,
            "camera_name": camera.name,
            "recording_mode": mode.value,
            "enabled": enabled,
        }

    @staticmethod
    def _get_rtsp_channel(camera: Any, quality: str) -> Any:
        """Return the camera channel matching a quality name (high/medium/low).

        Channels are named "High"/"Medium"/"Low" on the controller; match
        case-insensitively and raise an actionable error otherwise.
        """
        wanted = quality.strip().lower()
        for channel in camera.channels or []:
            if channel.name and channel.name.lower() == wanted:
                return channel
        available = ", ".join(c.name for c in (camera.channels or []) if c.name)
        raise ValueError(f"Camera has no '{quality}' channel. Available channels: {available}")

    def _rtsp_stream_urls(self, alias: str) -> Dict[str, str]:
        """Build the RTSPS/RTSP URLs for a channel alias from the NVR host."""
        host = str(self._cm.client.bootstrap.nvr.host) if self._cm.client.bootstrap.nvr.host else self._cm.host
        return {
            "rtsps_url": f"rtsps://{host}:7441/{alias}",
            "rtsp_url": f"rtsp://{host}:7447/{alias}",
        }

    async def toggle_rtsp(self, camera_id: str, enabled: bool, quality: str = "high") -> Dict[str, Any]:
        """Return current and proposed RTSP state for a channel (preview)."""
        camera = self._get_camera(camera_id)
        channel = self._get_rtsp_channel(camera, quality)
        return {
            "camera_id": camera_id,
            "camera_name": camera.name,
            "quality": quality,
            "channel_name": channel.name,
            "current_rtsp_enabled": channel.is_rtsp_enabled,
            "proposed_rtsp_enabled": enabled,
        }

    async def apply_toggle_rtsp(self, camera_id: str, enabled: bool, quality: str = "high") -> Dict[str, Any]:
        """Enable or disable RTSP publishing on a channel after confirmation.

        Mutates ``channel.is_rtsp_enabled`` and persists via the diff-based
        ``save_device`` flow (the same pattern used for ``mic_enabled``). The
        controller assigns ``rtsp_alias`` server-side when RTSP is first
        enabled; the resulting stream URLs are returned (and redacted at the
        tool boundary).
        """
        camera = self._get_camera(camera_id)
        channel = self._get_rtsp_channel(camera, quality)

        if channel.is_rtsp_enabled != enabled:
            data_before = camera.dict_with_excludes()
            channel.is_rtsp_enabled = enabled
            await camera.save_device(data_before)

        result: Dict[str, Any] = {
            "camera_id": camera_id,
            "camera_name": camera.name,
            "quality": quality,
            "channel_name": channel.name,
            "rtsp_enabled": channel.is_rtsp_enabled,
        }
        if channel.is_rtsp_enabled and channel.rtsp_alias:
            result["rtsp_alias"] = channel.rtsp_alias
            result.update(self._rtsp_stream_urls(channel.rtsp_alias))
        return result

    # ------------------------------------------------------------------
    # Detection areas (crossing lines, smart-detect zones, loiter zones)
    # ------------------------------------------------------------------

    async def _read_raw_camera(self, camera_id: str) -> Dict[str, Any]:
        """Read the camera fresh from the NVR as a raw dict.

        uiprotect has no model for crossing lines and its bootstrap cache can
        be stale after a write, so detection areas are always read from the NVR.
        """
        self._get_camera(camera_id)
        raw = await self._cm.client.api_request(f"cameras/{camera_id}", method="get")
        if not isinstance(raw, dict):
            raise RuntimeError(f"Unexpected response reading camera {camera_id}")
        return raw

    @staticmethod
    def _find_detection_area(raw: Dict[str, Any], kind: str, area_id: str) -> Dict[str, Any]:
        """Return the raw item of ``kind`` with ``area_id``, raising ValueError if absent."""
        for item in raw.get(DETECTION_AREA_KINDS[kind]) or []:
            if str(item.get("id")) == area_id:
                return item
        raise ValueError(f"Camera has no {kind} with id '{area_id}'")

    @staticmethod
    def _check_detection_area_rename(
        raw: Dict[str, Any], kind: str, area_id: str, new_name: str
    ) -> tuple[Dict[str, Any], str]:
        """Validate a rename against the camera's current data; return the item and trimmed name."""
        if kind not in DETECTION_AREA_KINDS:
            raise ValueError(f"Unknown kind '{kind}'. Use one of: {', '.join(DETECTION_AREA_KINDS)}")
        name = new_name.strip() if isinstance(new_name, str) else ""
        if not name:
            raise ValueError("new_name must not be blank")
        item = CameraManager._find_detection_area(raw, kind, area_id)
        if item.get("name") == name:
            return item, name
        for other in raw.get(DETECTION_AREA_KINDS[kind]) or []:
            if other is not item and str(other.get("name") or "").strip().casefold() == name.casefold():
                raise ValueError(f"Another {kind} on this camera is already named '{name}'")
        return item, name

    async def list_camera_detection_areas(self, camera_id: str) -> Dict[str, Any]:
        """List a camera's crossing lines, smart-detect zones and loiter zones."""
        raw = await self._read_raw_camera(camera_id)
        areas: List[Dict[str, Any]] = []
        for kind, key in DETECTION_AREA_KINDS.items():
            for item in raw.get(key) or []:
                area: Dict[str, Any] = {
                    "id": str(item.get("id")),
                    "name": item.get("name"),
                    "kind": kind,
                    "object_types": item.get("objectTypes") or [],
                }
                if kind == "line":
                    area["direction"] = item.get("direction")
                areas.append(area)
        return {"camera_id": camera_id, "camera_name": raw.get("name"), "areas": areas, "count": len(areas)}

    async def rename_camera_detection_area(
        self, camera_id: str, kind: str, area_id: str, new_name: str
    ) -> Dict[str, Any]:
        """Return current and proposed name for a detection area (preview)."""
        raw = await self._read_raw_camera(camera_id)
        item, name = self._check_detection_area_rename(raw, kind, area_id, new_name)
        return {
            "camera_id": camera_id,
            "camera_name": raw.get("name"),
            "kind": kind,
            "area_id": area_id,
            "current_name": item.get("name"),
            "proposed_name": name,
        }

    async def apply_rename_camera_detection_area(
        self, camera_id: str, kind: str, area_id: str, new_name: str
    ) -> Dict[str, Any]:
        """Rename one crossing line, smart-detect zone or loiter zone after confirmation.

        Protect replaces the whole list on write, so the camera is read fresh,
        the matching item's ``name`` is the only value changed, and the whole
        list is sent back. The camera is then read again and every item of the
        list is compared with what was read before; any difference raises.

        Known risk: an edit made in the Protect app between the read and the
        write is overwritten; the read-back reports it.
        """
        raw = await self._read_raw_camera(camera_id)
        item, name = self._check_detection_area_rename(raw, kind, area_id, new_name)
        previous_name = item.get("name")
        result: Dict[str, Any] = {
            "camera_id": camera_id,
            "camera_name": raw.get("name"),
            "kind": kind,
            "area_id": area_id,
            "previous_name": previous_name,
            "name": name,
        }
        if previous_name == name:
            return {**result, "changed": False}

        key = DETECTION_AREA_KINDS[kind]
        expected = copy.deepcopy(raw[key])
        for item in expected:
            if str(item.get("id")) == area_id:
                item["name"] = name
        await self._cm.client.api_request(f"cameras/{camera_id}", method="patch", json={key: expected})

        after = (await self._read_raw_camera(camera_id)).get(key) or []
        problems = self._diff_detection_areas(expected, after)
        if problems:
            raise RuntimeError(
                f"The rename of {kind} '{area_id}' on camera {camera_id} was sent to the NVR, "
                "but the read-back differs from what was sent: " + "; ".join(problems)
            )
        return {**result, "changed": True, "verified": True}

    @staticmethod
    def _diff_detection_areas(expected: List[Dict[str, Any]], actual: List[Dict[str, Any]]) -> List[str]:
        """Describe every difference between two lists of raw detection areas, matched by id."""
        actual_by_id = {str(item.get("id")): item for item in actual}
        problems: List[str] = []
        for want in expected:
            item_id = str(want.get("id"))
            got = actual_by_id.pop(item_id, None)
            if got is None:
                problems.append(f"item {item_id} is missing")
                continue
            for field in sorted(set(want) | set(got)):
                if want.get(field) != got.get(field):
                    problems.append(f"item {item_id} {field}: expected {want.get(field)!r}, got {got.get(field)!r}")
        problems.extend(f"item {item_id} was added" for item_id in actual_by_id)
        return problems

    async def ptz_goto_preset(self, camera_id: str, preset_slot: int) -> Dict[str, Any]:
        """Move a PTZ camera to a named preset position.

        Uses the public API ptz_goto_preset_public method.
        """
        camera = self._get_camera(camera_id)

        # Verify camera is PTZ capable
        self._get_ptz_camera(camera_id)

        # Fetch available presets for validation
        presets = await camera.get_ptz_presets()
        preset_slots = [p.slot for p in presets] if presets else []

        if preset_slots and preset_slot not in preset_slots:
            raise ValueError(f"Preset slot {preset_slot} not found. Available slots: {preset_slots}")

        await camera.ptz_goto_preset_public(slot=preset_slot)

        return {
            "camera_id": camera_id,
            "camera_name": camera.name,
            "preset_slot": preset_slot,
            "available_presets": [{"slot": p.slot, "name": p.name, "id": p.id} for p in (presets or [])],
        }

    async def ptz_move(
        self, camera_id: str, pan: Optional[float] = None, tilt: Optional[float] = None, duration_ms: int = 250
    ) -> Dict[str, Any]:
        """Move a PTZ camera using the Protect continuous movement API."""
        camera = self._get_ptz_camera(camera_id)
        x = self._validate_ptz_speed(pan, "pan")
        y = self._validate_ptz_speed(tilt, "tilt")
        duration = self._validate_ptz_duration(duration_ms)

        result: Dict[str, Any] = {
            "camera_id": camera_id,
            "camera_name": camera.name,
            "movement": {"pan": x, "tilt": y, "duration_ms": duration},
        }

        command = await self._send_ptz_continuous(camera_id, x=x, y=y, z=0, duration_ms=duration)
        result["controller_response"] = command["controller_response"]
        result["actions_taken"] = [f"pan={x}", f"tilt={y}", f"duration_ms={duration}"]

        return result

    async def ptz_zoom(self, camera_id: str, zoom_speed: int = 0, duration_ms: int = 250) -> Dict[str, Any]:
        """Zoom a PTZ camera using the Protect continuous movement API."""
        camera = self._get_ptz_camera(camera_id)
        z = self._validate_ptz_speed(zoom_speed, "zoom_speed")
        duration = self._validate_ptz_duration(duration_ms)

        command = await self._send_ptz_continuous(camera_id, x=0, y=0, z=z, duration_ms=duration)
        return {
            "camera_id": camera_id,
            "camera_name": camera.name,
            "movement": {"zoom_speed": z, "duration_ms": duration},
            "controller_response": command["controller_response"],
            "actions_taken": [f"zoom_speed={z}", f"duration_ms={duration}"],
        }

    async def reboot_camera(self, camera_id: str) -> Dict[str, Any]:
        """Return camera info for reboot preview."""
        camera = self._get_camera(camera_id)
        return {
            "camera_id": camera_id,
            "camera_name": camera.name,
            "state": str(camera.state.value) if camera.state else None,
            "is_connected": camera.is_connected,
            "firmware_version": camera.firmware_version,
        }

    async def apply_reboot_camera(self, camera_id: str) -> Dict[str, Any]:
        """Execute camera reboot after confirmation."""
        camera = self._get_camera(camera_id)
        await camera.reboot()
        return {
            "camera_id": camera_id,
            "camera_name": camera.name,
            "status": "reboot_initiated",
        }
