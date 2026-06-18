"""Tests for CameraManager and camera tools."""

from datetime import datetime, timedelta, timezone
from enum import Enum
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.redaction import REDACTED

# ---------------------------------------------------------------------------
# Fixtures: mock pyunifiprotect Camera model data
# ---------------------------------------------------------------------------


class _FakeStateType(Enum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"


class _FakeRecordingMode(Enum):
    ALWAYS = "always"
    NEVER = "never"
    DETECTIONS = "detections"


class _FakeIRLEDMode(Enum):
    AUTO = "auto"
    ON = "on"
    OFF = "off"


class _FakeHDRMode(Enum):
    NORMAL = "normal"
    NONE = "none"
    ALWAYS_ON = "superHdr"


class _FakeVideoMode(Enum):
    DEFAULT = "default"


class _FakeSmartDetectObjectType(Enum):
    PERSON = "person"
    VEHICLE = "vehicle"


def _make_channel(
    id=0,
    name="High",
    enabled=True,
    is_rtsp_enabled=True,
    rtsp_alias="test_alias",
    width=1920,
    height=1080,
    fps=30,
    bitrate=6000,
):
    ch = MagicMock()
    ch.id = id
    ch.name = name
    ch.enabled = enabled
    ch.is_rtsp_enabled = is_rtsp_enabled
    ch.rtsp_alias = rtsp_alias
    ch.width = width
    ch.height = height
    ch.fps = fps
    ch.bitrate = bitrate
    return ch


def _make_camera(**overrides):
    """Build a mock Camera object with sensible defaults."""
    cam = MagicMock()
    cam.id = overrides.get("id", "cam-001")
    cam.name = overrides.get("name", "Front Door")
    cam.type = overrides.get("type", "UVC G4 Bullet")
    cam.market_name = overrides.get("market_name", "G4 Bullet")
    cam.state = overrides.get("state", _FakeStateType.CONNECTED)
    cam.is_connected = overrides.get("is_connected", True)
    cam.last_seen = overrides.get("last_seen", datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc))
    cam.is_recording = overrides.get("is_recording", True)
    cam.firmware_version = overrides.get("firmware_version", "4.69.55")
    cam.host = overrides.get("host", "192.168.1.100")
    cam.mac = overrides.get("mac", "AA:BB:CC:DD:EE:01")
    cam.up_since = overrides.get("up_since", datetime(2026, 3, 15, tzinfo=timezone.utc))
    cam.uptime = overrides.get("uptime", timedelta(hours=36))
    cam.is_mic_enabled = overrides.get("is_mic_enabled", True)
    cam.mic_volume = overrides.get("mic_volume", 100)
    cam.is_dark = overrides.get("is_dark", False)
    cam.is_motion_detected = overrides.get("is_motion_detected", False)
    cam.is_smart_detected = overrides.get("is_smart_detected", False)
    cam.last_motion = overrides.get("last_motion", datetime(2026, 3, 16, 11, 30, tzinfo=timezone.utc))
    cam.has_speaker = overrides.get("has_speaker", True)
    cam.has_wifi = overrides.get("has_wifi", False)

    # Recording settings
    rec = MagicMock()
    rec.mode = overrides.get("recording_mode", _FakeRecordingMode.ALWAYS)
    cam.recording_settings = rec

    # ISP settings
    isp = MagicMock()
    isp.ir_led_mode = overrides.get("ir_led_mode", _FakeIRLEDMode.AUTO)
    isp.hdr_mode = overrides.get("hdr_mode", _FakeHDRMode.NORMAL)
    cam.isp_settings = isp

    # LED settings
    led = MagicMock()
    led.is_enabled = overrides.get("status_light_enabled", True)
    cam.led_settings = led

    # Speaker settings
    speaker = MagicMock()
    speaker.volume = overrides.get("speaker_volume", 80)
    cam.speaker_settings = speaker

    # Video mode
    cam.video_mode = overrides.get("video_mode", _FakeVideoMode.DEFAULT)

    # Smart detect settings
    smart = MagicMock()
    smart.object_types = overrides.get(
        "smart_detect_types", [_FakeSmartDetectObjectType.PERSON, _FakeSmartDetectObjectType.VEHICLE]
    )
    cam.smart_detect_settings = smart

    # Feature flags
    ff = MagicMock()
    ff.is_ptz = overrides.get("is_ptz", False)
    cam.feature_flags = ff

    # Channels
    cam.channels = overrides.get(
        "channels",
        [
            _make_channel(id=0, name="High", rtsp_alias="high_alias"),
            _make_channel(id=1, name="Medium", width=1280, height=720, fps=15, bitrate=2000, rtsp_alias="med_alias"),
            _make_channel(
                id=2, name="Low", width=640, height=360, fps=10, bitrate=500, is_rtsp_enabled=False, rtsp_alias=None
            ),
        ],
    )

    # Smart detection timestamps
    cam.last_smart_detects = overrides.get("last_smart_detects", {})
    cam.last_smart_audio_detects = overrides.get("last_smart_audio_detects", {})

    # Current detection flags
    cam.is_person_currently_detected = overrides.get("is_person_currently_detected", False)
    cam.is_vehicle_currently_detected = overrides.get("is_vehicle_currently_detected", False)
    cam.is_animal_currently_detected = overrides.get("is_animal_currently_detected", False)
    cam.is_package_currently_detected = overrides.get("is_package_currently_detected", False)
    cam.is_face_currently_detected = overrides.get("is_face_currently_detected", False)
    cam.is_license_plate_currently_detected = overrides.get("is_license_plate_currently_detected", False)

    # Motion detection
    cam.is_motion_detection_on = overrides.get("is_motion_detection_on", True)

    # Motion/smart zones
    cam.motion_zones = overrides.get("motion_zones", [MagicMock()])
    cam.smart_detect_zones = overrides.get("smart_detect_zones", [MagicMock()])

    # Stats
    cam.stats = overrides.get("stats", MagicMock())

    # Async methods
    cam.get_snapshot = AsyncMock(return_value=overrides.get("snapshot_bytes", b"\xff\xd8\xff\xe0JPEG"))
    cam.get_rtsps_streams = AsyncMock(return_value=overrides.get("rtsps_streams", None))
    cam.get_ptz_presets = AsyncMock(return_value=overrides.get("ptz_presets", []))
    cam.set_ir_led_model = AsyncMock()
    cam.set_hdr_mode = AsyncMock()
    cam.set_mic_volume = AsyncMock()
    cam.set_status_light = AsyncMock()
    cam.set_speaker_volume = AsyncMock()
    cam.set_name = AsyncMock()
    cam.set_motion_detection = AsyncMock()
    cam.set_recording_mode = AsyncMock()
    cam.set_camera_zoom = AsyncMock()
    cam.ptz_goto_preset_public = AsyncMock()
    cam.reboot = AsyncMock()
    cam.save_device = AsyncMock()
    cam.dict_with_excludes = MagicMock(return_value={})

    return cam


def _make_nvr(**overrides):
    nvr = MagicMock()
    nvr.host = overrides.get("host", "192.168.1.1")
    return nvr


def _make_bootstrap(cameras=None, nvr=None):
    bs = MagicMock()
    bs.cameras = cameras or {}
    bs.nvr = nvr or _make_nvr()
    return bs


@pytest.fixture
def mock_cm():
    """Create a mock ProtectConnectionManager with a mocked client.bootstrap."""
    cm = MagicMock()
    cm.host = "192.168.1.1"
    cam = _make_camera()
    cm.client.bootstrap = _make_bootstrap(cameras={"cam-001": cam})
    cm.client.api_request = AsyncMock(return_value={"success": True})
    return cm


@pytest.fixture
def mock_cm_multiple_cameras():
    """CM with multiple cameras."""
    cm = MagicMock()
    cm.host = "192.168.1.1"
    cam1 = _make_camera(id="cam-001", name="Front Door")
    cam2 = _make_camera(id="cam-002", name="Back Yard", is_recording=False, recording_mode=_FakeRecordingMode.NEVER)
    cam3 = _make_camera(id="cam-003", name="Garage", is_connected=False, state=_FakeStateType.DISCONNECTED)
    cm.client.bootstrap = _make_bootstrap(cameras={"cam-001": cam1, "cam-002": cam2, "cam-003": cam3})
    cm.client.api_request = AsyncMock(return_value={"success": True})
    return cm


# ===========================================================================
# CameraManager tests
# ===========================================================================


class TestCameraManagerListCameras:
    @pytest.mark.asyncio
    async def test_empty_cameras(self):
        from unifi_core.protect.managers.camera_manager import CameraManager

        cm = MagicMock()
        cm.client.bootstrap = _make_bootstrap(cameras={})
        mgr = CameraManager(cm)
        cameras = await mgr.list_cameras()
        assert cameras == []

    @pytest.mark.asyncio
    async def test_single_camera(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        cameras = await mgr.list_cameras()
        assert len(cameras) == 1
        cam = cameras[0]
        assert cam["id"] == "cam-001"
        assert cam["name"] == "Front Door"
        assert cam["is_connected"] is True
        assert cam["is_recording"] is True
        assert cam["recording_mode"] == "always"
        assert cam["is_ptz"] is False

    @pytest.mark.asyncio
    async def test_multiple_cameras(self, mock_cm_multiple_cameras):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm_multiple_cameras)
        cameras = await mgr.list_cameras()
        assert len(cameras) == 3
        names = [c["name"] for c in cameras]
        assert "Front Door" in names
        assert "Back Yard" in names
        assert "Garage" in names


class TestCameraManagerGetCamera:
    @pytest.mark.asyncio
    async def test_basic_fields(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        detail = await mgr.get_camera("cam-001")
        assert detail["id"] == "cam-001"
        assert detail["name"] == "Front Door"
        assert detail["firmware_version"] == "4.69.55"
        assert detail["ip_address"] == "192.168.1.100"
        assert detail["mac"] == "AA:BB:CC:DD:EE:01"
        assert detail["mic_enabled"] is True
        assert detail["mic_volume"] == 100
        assert detail["status_light_enabled"] is True
        assert detail["ir_led_mode"] == "auto"
        assert detail["hdr_mode"] == "normal"
        assert detail["has_speaker"] is True

    @pytest.mark.asyncio
    async def test_channels(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        detail = await mgr.get_camera("cam-001")
        assert len(detail["channels"]) == 3
        high = detail["channels"][0]
        assert high["name"] == "High"
        assert high["width"] == 1920
        assert high["height"] == 1080

    @pytest.mark.asyncio
    async def test_smart_detect_types(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        detail = await mgr.get_camera("cam-001")
        assert "person" in detail["smart_detect_types"]
        assert "vehicle" in detail["smart_detect_types"]

    @pytest.mark.asyncio
    async def test_not_found(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        with pytest.raises(UniFiNotFoundError):
            await mgr.get_camera("nonexistent")


class TestCameraManagerGetSnapshot:
    @pytest.mark.asyncio
    async def test_success(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        result = await mgr.get_snapshot("cam-001")
        assert isinstance(result, bytes)
        assert result == b"\xff\xd8\xff\xe0JPEG"

    @pytest.mark.asyncio
    async def test_with_dimensions(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        cam = mock_cm.client.bootstrap.cameras["cam-001"]
        await mgr.get_snapshot("cam-001", width=640, height=480)
        cam.get_snapshot.assert_awaited_once_with(width=640, height=480)

    @pytest.mark.asyncio
    async def test_none_snapshot_raises(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        cam = mock_cm.client.bootstrap.cameras["cam-001"]
        cam.get_snapshot = AsyncMock(return_value=None)
        mgr = CameraManager(mock_cm)
        with pytest.raises(RuntimeError, match="Failed to get snapshot"):
            await mgr.get_snapshot("cam-001")

    @pytest.mark.asyncio
    async def test_not_found(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        with pytest.raises(UniFiNotFoundError):
            await mgr.get_snapshot("nonexistent")


class TestCameraManagerGetCameraStreams:
    @pytest.mark.asyncio
    async def test_channels_with_rtsp(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        streams = await mgr.get_camera_streams("cam-001")
        assert streams["camera_id"] == "cam-001"
        assert "High" in streams["channels"]
        assert "Medium" in streams["channels"]
        # Low channel has is_rtsp_enabled=False
        assert "Low" not in streams["channels"]

        high = streams["channels"]["High"]
        assert "rtsps_url" in high
        assert "rtsp_url" in high
        assert high["width"] == 1920

    @pytest.mark.asyncio
    async def test_not_found(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        with pytest.raises(UniFiNotFoundError):
            await mgr.get_camera_streams("nonexistent")


class TestCameraManagerGetCameraAnalytics:
    @pytest.mark.asyncio
    async def test_basic_analytics(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        analytics = await mgr.get_camera_analytics("cam-001")
        assert analytics["camera_id"] == "cam-001"
        assert analytics["detections"]["is_motion_detected"] is False
        assert analytics["currently_detected"]["person"] is False
        assert analytics["motion_zone_count"] == 1
        assert analytics["smart_detect_zone_count"] == 1

    @pytest.mark.asyncio
    async def test_with_smart_detects(self):
        from unifi_core.protect.managers.camera_manager import CameraManager

        ts = datetime(2026, 3, 16, 11, 45, tzinfo=timezone.utc)
        cam = _make_camera(
            last_smart_detects={_FakeSmartDetectObjectType.PERSON: ts},
            is_person_currently_detected=True,
        )
        cm = MagicMock()
        cm.client.bootstrap = _make_bootstrap(cameras={"cam-001": cam})
        mgr = CameraManager(cm)
        analytics = await mgr.get_camera_analytics("cam-001")
        assert analytics["smart_detects"]["person"] == ts.isoformat()
        assert analytics["currently_detected"]["person"] is True


class TestCameraManagerUpdateCameraSettings:
    @pytest.mark.asyncio
    async def test_preview(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        result = await mgr.update_camera_settings("cam-001", {"status_light_on": False})
        assert result["camera_id"] == "cam-001"
        assert result["current_state"]["status_light_on"] is True
        assert result["proposed_changes"]["status_light_on"] is False

    @pytest.mark.asyncio
    async def test_multiple_settings(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        result = await mgr.update_camera_settings(
            "cam-001",
            {
                "ir_led_mode": "on",
                "mic_volume": 50,
            },
        )
        assert "ir_led_mode" in result["current_state"]
        assert "mic_volume" in result["current_state"]
        assert result["proposed_changes"]["ir_led_mode"] == "on"
        assert result["proposed_changes"]["mic_volume"] == 50


class TestCameraManagerApplyCameraSettings:
    @pytest.mark.asyncio
    async def test_apply_status_light(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        cam = mock_cm.client.bootstrap.cameras["cam-001"]
        result = await mgr.apply_camera_settings("cam-001", {"status_light_on": False})
        assert "status_light_on=False" in result["applied"]
        cam.set_status_light.assert_awaited_once_with(False)

    @pytest.mark.asyncio
    async def test_apply_mic_volume(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        cam = mock_cm.client.bootstrap.cameras["cam-001"]
        result = await mgr.apply_camera_settings("cam-001", {"mic_volume": 50})
        assert "mic_volume=50" in result["applied"]
        cam.set_mic_volume.assert_awaited_once_with(50)

    @pytest.mark.asyncio
    async def test_apply_error_handling(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        cam = mock_cm.client.bootstrap.cameras["cam-001"]
        cam.set_status_light = AsyncMock(side_effect=RuntimeError("API error"))
        mgr = CameraManager(mock_cm)
        result = await mgr.apply_camera_settings("cam-001", {"status_light_on": False})
        assert "errors" in result
        assert any("API error" in e for e in result["errors"])


class TestCameraManagerToggleRecording:
    @pytest.mark.asyncio
    async def test_preview_enable(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        result = await mgr.toggle_recording("cam-001", True)
        assert result["current_recording_mode"] == "always"
        assert result["proposed_recording_mode"] == "always"

    @pytest.mark.asyncio
    async def test_preview_disable(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        result = await mgr.toggle_recording("cam-001", False)
        assert result["proposed_recording_mode"] == "never"

    @pytest.mark.asyncio
    async def test_apply(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        cam = mock_cm.client.bootstrap.cameras["cam-001"]
        result = await mgr.apply_toggle_recording("cam-001", False)
        assert result["recording_mode"] == "never"
        cam.set_recording_mode.assert_awaited_once()


class TestCameraManagerPTZ:
    @pytest.mark.asyncio
    async def test_ptz_not_supported(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        with pytest.raises(ValueError, match="does not support PTZ"):
            await mgr.ptz_goto_preset("cam-001", 1)

    @pytest.mark.asyncio
    async def test_ptz_preset_success(self):
        from unifi_core.protect.managers.camera_manager import CameraManager

        preset = MagicMock()
        preset.slot = 1
        preset.name = "Front"
        preset.id = "preset-1"
        cam = _make_camera(is_ptz=True, ptz_presets=[preset])
        cm = MagicMock()
        cm.client.bootstrap = _make_bootstrap(cameras={"cam-001": cam})
        mgr = CameraManager(cm)
        result = await mgr.ptz_goto_preset("cam-001", 1)
        assert result["preset_slot"] == 1
        cam.ptz_goto_preset_public.assert_awaited_once_with(slot=1)

    @pytest.mark.asyncio
    async def test_ptz_preset_invalid_slot(self):
        from unifi_core.protect.managers.camera_manager import CameraManager

        preset = MagicMock()
        preset.slot = 1
        preset.name = "Front"
        preset.id = "preset-1"
        cam = _make_camera(is_ptz=True, ptz_presets=[preset])
        cm = MagicMock()
        cm.client.bootstrap = _make_bootstrap(cameras={"cam-001": cam})
        mgr = CameraManager(cm)
        with pytest.raises(ValueError, match="Preset slot 99 not found"):
            await mgr.ptz_goto_preset("cam-001", 99)

    @pytest.mark.asyncio
    async def test_ptz_move_pan_tilt(self):
        from unifi_core.protect.managers.camera_manager import CameraManager

        cam = _make_camera(is_ptz=True)
        cm = MagicMock()
        cm.client.bootstrap = _make_bootstrap(cameras={"cam-001": cam})
        cm.client.api_request = AsyncMock(return_value={"success": True})
        mgr = CameraManager(cm)
        result = await mgr.ptz_move("cam-001", pan=100, tilt=-50, duration_ms=0)
        assert result["movement"] == {"pan": 100, "tilt": -50, "duration_ms": 0}
        cm.client.api_request.assert_awaited_once_with(
            "cameras/cam-001/move",
            method="post",
            json={"type": "continuous", "payload": {"x": 100, "y": -50, "z": 0}},
        )

    @pytest.mark.asyncio
    async def test_ptz_move_auto_stops_after_duration(self):
        from unifi_core.protect.managers.camera_manager import CameraManager

        cam = _make_camera(is_ptz=True)
        cm = MagicMock()
        cm.client.bootstrap = _make_bootstrap(cameras={"cam-001": cam})
        cm.client.api_request = AsyncMock(return_value={"success": True})
        mgr = CameraManager(cm)
        with patch("unifi_core.protect.managers.camera_manager.asyncio.sleep", new=AsyncMock()) as sleep:
            await mgr.ptz_move("cam-001", pan=100, duration_ms=250)
        sleep.assert_awaited_once_with(0.25)
        assert cm.client.api_request.await_count == 2
        cm.client.api_request.assert_any_await(
            "cameras/cam-001/move",
            method="post",
            json={"type": "continuous", "payload": {"x": 0, "y": 0, "z": 0}},
        )

    @pytest.mark.asyncio
    async def test_ptz_zoom(self):
        from unifi_core.protect.managers.camera_manager import CameraManager

        cam = _make_camera(is_ptz=True)
        cm = MagicMock()
        cm.client.bootstrap = _make_bootstrap(cameras={"cam-001": cam})
        cm.client.api_request = AsyncMock(return_value={"success": True})
        mgr = CameraManager(cm)
        result = await mgr.ptz_zoom("cam-001", zoom_speed=750, duration_ms=0)
        assert result["movement"] == {"zoom_speed": 750, "duration_ms": 0}
        cm.client.api_request.assert_awaited_once_with(
            "cameras/cam-001/move",
            method="post",
            json={"type": "continuous", "payload": {"x": 0, "y": 0, "z": 750}},
        )

    @pytest.mark.asyncio
    async def test_ptz_speed_validation(self):
        from unifi_core.protect.managers.camera_manager import CameraManager

        cam = _make_camera(is_ptz=True)
        cm = MagicMock()
        cm.client.bootstrap = _make_bootstrap(cameras={"cam-001": cam})
        cm.client.api_request = AsyncMock()
        mgr = CameraManager(cm)
        with pytest.raises(ValueError, match="pan must be between"):
            await mgr.ptz_move("cam-001", pan=1001)


class TestCameraManagerReboot:
    @pytest.mark.asyncio
    async def test_preview(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        result = await mgr.reboot_camera("cam-001")
        assert result["camera_id"] == "cam-001"
        assert result["state"] == "CONNECTED"
        assert result["is_connected"] is True

    @pytest.mark.asyncio
    async def test_apply(self, mock_cm):
        from unifi_core.protect.managers.camera_manager import CameraManager

        mgr = CameraManager(mock_cm)
        cam = mock_cm.client.bootstrap.cameras["cam-001"]
        result = await mgr.apply_reboot_camera("cam-001")
        assert result["status"] == "reboot_initiated"
        cam.reboot.assert_awaited_once()


# ===========================================================================
# Camera tools tests
# ===========================================================================


@pytest.fixture
def mock_camera_manager():
    """Patch camera_manager in the tools module."""
    mgr = MagicMock()
    with patch("unifi_protect_mcp.tools.cameras.camera_manager", mgr):
        yield mgr


class TestProtectListCamerasTool:
    @pytest.mark.asyncio
    async def test_success(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_list_cameras

        mock_camera_manager.list_cameras = AsyncMock(return_value=[{"id": "cam-001", "name": "Front Door"}])
        result = await protect_list_cameras()
        assert result["success"] is True
        assert result["data"]["count"] == 1
        assert result["data"]["cameras"][0]["id"] == "cam-001"

    @pytest.mark.asyncio
    async def test_empty(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_list_cameras

        mock_camera_manager.list_cameras = AsyncMock(return_value=[])
        result = await protect_list_cameras()
        assert result["success"] is True
        assert result["data"]["count"] == 0

    @pytest.mark.asyncio
    async def test_error(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_list_cameras

        mock_camera_manager.list_cameras = AsyncMock(side_effect=RuntimeError("connection lost"))
        result = await protect_list_cameras()
        assert result["success"] is False
        assert "connection lost" in result["error"]


class TestProtectGetCameraTool:
    @pytest.mark.asyncio
    async def test_success(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_get_camera

        mock_camera_manager.get_camera = AsyncMock(
            return_value={"id": "cam-001", "name": "Front Door", "firmware_version": "4.69.55"}
        )
        result = await protect_get_camera("cam-001")
        assert result["success"] is True
        assert result["data"]["id"] == "cam-001"

    @pytest.mark.asyncio
    async def test_not_found(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_get_camera

        mock_camera_manager.get_camera = AsyncMock(side_effect=ValueError("Camera not found: bad-id"))
        result = await protect_get_camera("bad-id")
        assert result["success"] is False
        assert "Camera not found" in result["error"]

    @pytest.mark.asyncio
    async def test_error(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_get_camera

        mock_camera_manager.get_camera = AsyncMock(side_effect=RuntimeError("boom"))
        result = await protect_get_camera("cam-001")
        assert result["success"] is False
        assert "boom" in result["error"]


class TestProtectGetSnapshotTool:
    @pytest.mark.asyncio
    async def test_include_image(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_get_snapshot

        mock_camera_manager.get_snapshot = AsyncMock(return_value=b"\xff\xd8JPEG")
        result = await protect_get_snapshot("cam-001", include_image=True)
        assert result["success"] is True
        assert "image_base64" in result["data"]
        assert result["data"]["content_type"] == "image/jpeg"

    @pytest.mark.asyncio
    async def test_reference_url(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_get_snapshot

        result = await protect_get_snapshot("cam-001", include_image=False)
        assert result["success"] is True
        assert "snapshot_url" in result["data"]
        assert "cam-001" in result["data"]["snapshot_url"]

    @pytest.mark.asyncio
    async def test_snapshot_error(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_get_snapshot

        mock_camera_manager.get_snapshot = AsyncMock(side_effect=RuntimeError("camera offline"))
        result = await protect_get_snapshot("cam-001", include_image=True)
        assert result["success"] is False
        assert "camera offline" in result["error"]

    @pytest.mark.asyncio
    async def test_not_found(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_get_snapshot

        mock_camera_manager.get_snapshot = AsyncMock(side_effect=ValueError("Camera not found: x"))
        result = await protect_get_snapshot("x", include_image=True)
        assert result["success"] is False
        assert "Camera not found" in result["error"]


class TestProtectGetCameraStreamsTool:
    @pytest.mark.asyncio
    async def test_success(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_get_camera_streams

        mock_camera_manager.get_camera_streams = AsyncMock(
            return_value={
                "camera_id": "cam-001",
                "channels": {"High": {"rtsp_alias": "abc123", "rtsps_url": "rtsps://nvr.local/abc123"}},
                "rtsps_streams": {"High": "rtsps://nvr.local/abc123"},
            }
        )
        result = await protect_get_camera_streams("cam-001")
        assert result["success"] is True
        assert "High" in result["data"]["channels"]
        assert result["data"]["channels"]["High"]["rtsp_alias"] == REDACTED
        assert result["data"]["channels"]["High"]["rtsps_url"] == REDACTED
        assert result["data"]["rtsps_streams"] == REDACTED

    @pytest.mark.asyncio
    async def test_policy_disabled_returns_raw_stream_urls(self, mock_camera_manager, monkeypatch):
        from unifi_protect_mcp.tools.cameras import protect_get_camera_streams

        monkeypatch.setenv("UNIFI_PROTECT_REDACT_SENSITIVE_FIELDS", "false")
        mock_camera_manager.get_camera_streams = AsyncMock(
            return_value={
                "camera_id": "cam-001",
                "channels": {"High": {"rtsp_alias": "abc123", "rtsps_url": "rtsps://nvr.local/abc123"}},
                "rtsps_streams": {"High": "rtsps://nvr.local/abc123"},
            }
        )
        result = await protect_get_camera_streams("cam-001")
        assert result["success"] is True
        assert result["data"]["channels"]["High"]["rtsp_alias"] == "abc123"
        assert result["data"]["channels"]["High"]["rtsps_url"] == "rtsps://nvr.local/abc123"
        assert result["data"]["rtsps_streams"]["High"] == "rtsps://nvr.local/abc123"

    @pytest.mark.asyncio
    async def test_error(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_get_camera_streams

        mock_camera_manager.get_camera_streams = AsyncMock(side_effect=RuntimeError("fail"))
        result = await protect_get_camera_streams("cam-001")
        assert result["success"] is False


class TestProtectGetCameraAnalyticsTool:
    @pytest.mark.asyncio
    async def test_success(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_get_camera_analytics

        mock_camera_manager.get_camera_analytics = AsyncMock(
            return_value={"camera_id": "cam-001", "detections": {"is_motion_detected": False}}
        )
        result = await protect_get_camera_analytics("cam-001")
        assert result["success"] is True
        assert result["data"]["camera_id"] == "cam-001"

    @pytest.mark.asyncio
    async def test_error(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_get_camera_analytics

        mock_camera_manager.get_camera_analytics = AsyncMock(side_effect=RuntimeError("err"))
        result = await protect_get_camera_analytics("cam-001")
        assert result["success"] is False


class TestProtectUpdateCameraSettingsTool:
    @pytest.mark.asyncio
    async def test_preview(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_update_camera_settings

        mock_camera_manager.update_camera_settings = AsyncMock(
            return_value={
                "camera_id": "cam-001",
                "camera_name": "Front Door",
                "current_state": {"status_light_on": True},
                "proposed_changes": {"status_light_on": False},
            }
        )
        result = await protect_update_camera_settings("cam-001", {"status_light_on": False}, confirm=False)
        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["preview"]["current"]["status_light_on"] is True
        assert result["preview"]["proposed"]["status_light_on"] is False

    @pytest.mark.asyncio
    async def test_confirm(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_update_camera_settings

        mock_camera_manager.update_camera_settings = AsyncMock(
            return_value={
                "camera_id": "cam-001",
                "camera_name": "Front Door",
                "current_state": {"status_light_on": True},
                "proposed_changes": {"status_light_on": False},
            }
        )
        mock_camera_manager.apply_camera_settings = AsyncMock(
            return_value={"camera_id": "cam-001", "applied": ["status_light_on=False"]}
        )
        result = await protect_update_camera_settings("cam-001", {"status_light_on": False}, confirm=True)
        assert result["success"] is True
        assert "applied" in result["data"]

    @pytest.mark.asyncio
    async def test_empty_settings(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_update_camera_settings

        result = await protect_update_camera_settings("cam-001", {}, confirm=False)
        assert result["success"] is False
        assert "No settings provided" in result["error"]

    @pytest.mark.asyncio
    async def test_error(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_update_camera_settings

        mock_camera_manager.update_camera_settings = AsyncMock(side_effect=RuntimeError("boom"))
        result = await protect_update_camera_settings("cam-001", {"name": "test"}, confirm=False)
        assert result["success"] is False


class TestProtectToggleRecordingTool:
    @pytest.mark.asyncio
    async def test_preview(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_toggle_recording

        mock_camera_manager.toggle_recording = AsyncMock(
            return_value={
                "camera_id": "cam-001",
                "camera_name": "Front Door",
                "current_recording_mode": "always",
                "proposed_recording_mode": "never",
                "is_recording": True,
            }
        )
        result = await protect_toggle_recording("cam-001", enabled=False, confirm=False)
        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["action"] == "toggle"

    @pytest.mark.asyncio
    async def test_confirm(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_toggle_recording

        mock_camera_manager.toggle_recording = AsyncMock(
            return_value={
                "camera_id": "cam-001",
                "camera_name": "Front Door",
                "current_recording_mode": "always",
                "proposed_recording_mode": "never",
                "is_recording": True,
            }
        )
        mock_camera_manager.apply_toggle_recording = AsyncMock(
            return_value={"camera_id": "cam-001", "recording_mode": "never", "enabled": False}
        )
        result = await protect_toggle_recording("cam-001", enabled=False, confirm=True)
        assert result["success"] is True
        assert result["data"]["recording_mode"] == "never"


class TestProtectPTZMoveTool:
    @pytest.mark.asyncio
    async def test_preview(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_ptz_move

        mock_camera_manager.get_camera = AsyncMock(return_value={"id": "cam-001", "name": "Front Door", "is_ptz": True})
        result = await protect_ptz_move("cam-001", pan=100, tilt=0)
        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["preview"]["proposed"]["pan"] == 100

    @pytest.mark.asyncio
    async def test_confirm(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_ptz_move

        mock_camera_manager.ptz_move = AsyncMock(
            return_value={"camera_id": "cam-001", "actions_taken": ["pan=100", "tilt=0", "duration_ms=250"]}
        )
        result = await protect_ptz_move("cam-001", pan=100, confirm=True)
        assert result["success"] is True
        assert "pan=100" in result["data"]["actions_taken"]

    @pytest.mark.asyncio
    async def test_not_ptz(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_ptz_move

        mock_camera_manager.ptz_move = AsyncMock(side_effect=ValueError("does not support PTZ"))
        result = await protect_ptz_move("cam-001", pan=100, confirm=True)
        assert result["success"] is False
        assert "PTZ" in result["error"]


class TestProtectPTZZoomTool:
    @pytest.mark.asyncio
    async def test_preview(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_ptz_zoom

        mock_camera_manager.get_camera = AsyncMock(return_value={"id": "cam-001", "name": "Front Door", "is_ptz": True})
        result = await protect_ptz_zoom("cam-001", zoom_speed=750)
        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["preview"]["proposed"]["zoom_speed"] == 750

    @pytest.mark.asyncio
    async def test_confirm(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_ptz_zoom

        mock_camera_manager.ptz_zoom = AsyncMock(
            return_value={"camera_id": "cam-001", "actions_taken": ["zoom_speed=750", "duration_ms=250"]}
        )
        result = await protect_ptz_zoom("cam-001", zoom_speed=750, confirm=True)
        assert result["success"] is True
        assert "zoom_speed=750" in result["data"]["actions_taken"]


class TestProtectPTZPresetTool:
    @pytest.mark.asyncio
    async def test_preview(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_ptz_preset

        mock_camera_manager.get_camera = AsyncMock(return_value={"id": "cam-001", "name": "Front Door", "is_ptz": True})
        result = await protect_ptz_preset("cam-001", preset_slot=1)
        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["preview"]["proposed"]["preset_slot"] == 1

    @pytest.mark.asyncio
    async def test_success(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_ptz_preset

        mock_camera_manager.ptz_goto_preset = AsyncMock(
            return_value={"camera_id": "cam-001", "preset_slot": 1, "available_presets": []}
        )
        result = await protect_ptz_preset("cam-001", preset_slot=1, confirm=True)
        assert result["success"] is True
        assert result["data"]["preset_slot"] == 1

    @pytest.mark.asyncio
    async def test_error(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_ptz_preset

        mock_camera_manager.ptz_goto_preset = AsyncMock(side_effect=ValueError("not found"))
        result = await protect_ptz_preset("cam-001", preset_slot=99, confirm=True)
        assert result["success"] is False


class TestProtectRebootCameraTool:
    @pytest.mark.asyncio
    async def test_preview(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_reboot_camera

        mock_camera_manager.reboot_camera = AsyncMock(
            return_value={
                "camera_id": "cam-001",
                "camera_name": "Front Door",
                "state": "CONNECTED",
                "is_connected": True,
                "firmware_version": "4.69.55",
            }
        )
        result = await protect_reboot_camera("cam-001", confirm=False)
        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["action"] == "reboot"
        assert len(result.get("warnings", [])) > 0

    @pytest.mark.asyncio
    async def test_confirm(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_reboot_camera

        mock_camera_manager.reboot_camera = AsyncMock(
            return_value={
                "camera_id": "cam-001",
                "camera_name": "Front Door",
                "state": "CONNECTED",
                "is_connected": True,
                "firmware_version": "4.69.55",
            }
        )
        mock_camera_manager.apply_reboot_camera = AsyncMock(
            return_value={"camera_id": "cam-001", "status": "reboot_initiated"}
        )
        result = await protect_reboot_camera("cam-001", confirm=True)
        assert result["success"] is True
        assert result["data"]["status"] == "reboot_initiated"

    @pytest.mark.asyncio
    async def test_error(self, mock_camera_manager):
        from unifi_protect_mcp.tools.cameras import protect_reboot_camera

        mock_camera_manager.reboot_camera = AsyncMock(side_effect=RuntimeError("failed"))
        result = await protect_reboot_camera("cam-001", confirm=False)
        assert result["success"] is False
