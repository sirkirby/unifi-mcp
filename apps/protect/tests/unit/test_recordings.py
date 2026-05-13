"""Tests for RecordingManager and recording tools."""

from datetime import datetime, timezone
from enum import Enum
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from unifi_core.exceptions import UniFiNotFoundError

# ---------------------------------------------------------------------------
# Fixtures: mock pyunifiprotect Camera model data for recordings
# ---------------------------------------------------------------------------


class _FakeRecordingMode(Enum):
    ALWAYS = "always"
    NEVER = "never"
    DETECTIONS = "detections"


def _make_video_stats(**overrides):
    """Build a mock video stats object."""
    stats = MagicMock()
    stats.recording_start = overrides.get("recording_start", datetime(2026, 3, 10, tzinfo=timezone.utc))
    stats.recording_end = overrides.get("recording_end", datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc))
    stats.timelapse_start = overrides.get("timelapse_start", None)
    stats.timelapse_end = overrides.get("timelapse_end", None)
    return stats


def _make_camera(**overrides):
    """Build a mock Camera object with recording-relevant defaults."""
    cam = MagicMock()
    cam.id = overrides.get("id", "cam-001")
    cam.name = overrides.get("name", "Front Door")
    cam.is_recording = overrides.get("is_recording", True)
    cam.has_recordings = overrides.get("has_recordings", True)

    # Recording settings
    rec = MagicMock()
    rec.mode = overrides.get("recording_mode", _FakeRecordingMode.ALWAYS)
    cam.recording_settings = rec

    # Stats with video
    video_stats = overrides.get("video_stats", _make_video_stats())
    cam.stats = MagicMock()
    cam.stats.video = video_stats

    # Async methods
    cam.get_video = AsyncMock(return_value=overrides.get("video_bytes", b"\x00\x00\x01\xb3FAKEMP4"))

    return cam


def _make_bootstrap(cameras=None):
    bs = MagicMock()
    bs.cameras = cameras or {}
    return bs


@pytest.fixture
def mock_cm():
    """Create a mock ProtectConnectionManager."""
    cm = MagicMock()
    cm.host = "192.168.1.1"
    cam = _make_camera()
    cm.client.bootstrap = _make_bootstrap(cameras={"cam-001": cam})
    return cm


@pytest.fixture
def mock_cm_multi():
    """CM with multiple cameras."""
    cm = MagicMock()
    cm.host = "192.168.1.1"
    cam1 = _make_camera(id="cam-001", name="Front Door")
    cam2 = _make_camera(
        id="cam-002",
        name="Back Yard",
        is_recording=False,
        recording_mode=_FakeRecordingMode.NEVER,
    )
    cm.client.bootstrap = _make_bootstrap(cameras={"cam-001": cam1, "cam-002": cam2})
    return cm


# ===========================================================================
# RecordingManager tests
# ===========================================================================


class TestRecordingManagerGetRecordingStatus:
    @pytest.mark.asyncio
    async def test_single_camera(self, mock_cm):
        from unifi_core.protect.managers.recording_manager import RecordingManager

        mgr = RecordingManager(mock_cm)
        result = await mgr.get_recording_status(camera_id="cam-001")
        assert result["count"] == 1
        cam = result["cameras"][0]
        assert cam["camera_id"] == "cam-001"
        assert cam["recording_mode"] == "always"
        assert cam["is_recording"] is True

    @pytest.mark.asyncio
    async def test_all_cameras(self, mock_cm_multi):
        from unifi_core.protect.managers.recording_manager import RecordingManager

        mgr = RecordingManager(mock_cm_multi)
        result = await mgr.get_recording_status()
        assert result["count"] == 2
        ids = [c["camera_id"] for c in result["cameras"]]
        assert "cam-001" in ids
        assert "cam-002" in ids

    @pytest.mark.asyncio
    async def test_camera_not_found(self, mock_cm):
        from unifi_core.protect.managers.recording_manager import RecordingManager

        mgr = RecordingManager(mock_cm)
        with pytest.raises(UniFiNotFoundError):
            await mgr.get_recording_status(camera_id="nonexistent")

    @pytest.mark.asyncio
    async def test_video_stats_included(self, mock_cm):
        from unifi_core.protect.managers.recording_manager import RecordingManager

        mgr = RecordingManager(mock_cm)
        result = await mgr.get_recording_status(camera_id="cam-001")
        cam = result["cameras"][0]
        assert cam["video_stats"]["recording_start"] is not None
        assert cam["video_stats"]["recording_end"] is not None


class TestRecordingManagerListRecordings:
    @pytest.mark.asyncio
    async def test_with_time_range(self, mock_cm):
        from unifi_core.protect.managers.recording_manager import RecordingManager

        mgr = RecordingManager(mock_cm)
        start = datetime(2026, 3, 16, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc)
        result = await mgr.list_recordings("cam-001", start=start, end=end)
        assert result["camera_id"] == "cam-001"
        assert result["requested_start"] == start.isoformat()
        assert result["requested_end"] == end.isoformat()
        assert result["is_recording"] is True

    @pytest.mark.asyncio
    async def test_default_time_range(self, mock_cm):
        from unifi_core.protect.managers.recording_manager import RecordingManager

        mgr = RecordingManager(mock_cm)
        result = await mgr.list_recordings("cam-001")
        assert result["camera_id"] == "cam-001"
        assert result["requested_start"] is not None
        assert result["requested_end"] is not None

    @pytest.mark.asyncio
    async def test_camera_not_found(self, mock_cm):
        from unifi_core.protect.managers.recording_manager import RecordingManager

        mgr = RecordingManager(mock_cm)
        with pytest.raises(UniFiNotFoundError):
            await mgr.list_recordings("nonexistent")

    @pytest.mark.asyncio
    async def test_includes_note(self, mock_cm):
        from unifi_core.protect.managers.recording_manager import RecordingManager

        mgr = RecordingManager(mock_cm)
        result = await mgr.list_recordings("cam-001")
        assert "note" in result
        assert "continuous streams" in result["note"]


class TestRecordingManagerExportClip:
    @pytest.mark.asyncio
    async def test_success(self, mock_cm):
        from unifi_core.protect.managers.recording_manager import RecordingManager

        mgr = RecordingManager(mock_cm)
        start = datetime(2026, 3, 16, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 16, 10, 30, tzinfo=timezone.utc)
        result = await mgr.export_clip("cam-001", start=start, end=end)
        assert result["exported"] is True
        assert result["size_bytes"] > 0
        assert result["duration_seconds"] == 1800
        assert result["content_type"] == "video/mp4"

    @pytest.mark.asyncio
    async def test_no_recording_available(self, mock_cm):
        from unifi_core.protect.managers.recording_manager import RecordingManager

        cam = mock_cm.client.bootstrap.cameras["cam-001"]
        cam.get_video = AsyncMock(return_value=None)
        mgr = RecordingManager(mock_cm)
        start = datetime(2026, 3, 16, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 16, 10, 30, tzinfo=timezone.utc)
        result = await mgr.export_clip("cam-001", start=start, end=end)
        assert result["exported"] is False
        assert "No recording available" in result["message"]

    @pytest.mark.asyncio
    async def test_timelapse_export(self, mock_cm):
        from unifi_core.protect.managers.recording_manager import RecordingManager

        mgr = RecordingManager(mock_cm)
        start = datetime(2026, 3, 16, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 16, 10, 30, tzinfo=timezone.utc)
        result = await mgr.export_clip("cam-001", start=start, end=end, fps=4)
        assert result["exported"] is True
        assert result["is_timelapse"] is True
        assert result["fps"] == 4
        cam = mock_cm.client.bootstrap.cameras["cam-001"]
        cam.get_video.assert_awaited_once()
        call_kwargs = cam.get_video.call_args[1]
        assert call_kwargs["fps"] == 4

    @pytest.mark.asyncio
    async def test_invalid_time_range(self, mock_cm):
        from unifi_core.protect.managers.recording_manager import RecordingManager

        mgr = RecordingManager(mock_cm)
        start = datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 16, 10, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="End time must be after start time"):
            await mgr.export_clip("cam-001", start=start, end=end)

    @pytest.mark.asyncio
    async def test_exceeds_max_duration(self, mock_cm):
        from unifi_core.protect.managers.recording_manager import RecordingManager

        mgr = RecordingManager(mock_cm)
        start = datetime(2026, 3, 16, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 16, 3, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="Maximum export duration"):
            await mgr.export_clip("cam-001", start=start, end=end)

    @pytest.mark.asyncio
    async def test_camera_not_found(self, mock_cm):
        from unifi_core.protect.managers.recording_manager import RecordingManager

        mgr = RecordingManager(mock_cm)
        start = datetime(2026, 3, 16, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 16, 10, 30, tzinfo=timezone.utc)
        with pytest.raises(UniFiNotFoundError):
            await mgr.export_clip("nonexistent", start=start, end=end)


class TestRecordingManagerDeleteRecording:
    @pytest.mark.asyncio
    async def test_not_supported(self, mock_cm):
        from unifi_core.protect.managers.recording_manager import RecordingManager

        mgr = RecordingManager(mock_cm)
        start = datetime(2026, 3, 16, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 16, 10, 30, tzinfo=timezone.utc)
        result = await mgr.delete_recording("cam-001", start=start, end=end)
        assert result["supported"] is False
        assert "not supported" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_camera_not_found(self, mock_cm):
        from unifi_core.protect.managers.recording_manager import RecordingManager

        mgr = RecordingManager(mock_cm)
        start = datetime(2026, 3, 16, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 16, 10, 30, tzinfo=timezone.utc)
        with pytest.raises(UniFiNotFoundError):
            await mgr.delete_recording("nonexistent", start=start, end=end)


# ===========================================================================
# Recording tools tests
# ===========================================================================


@pytest.fixture
def mock_recording_manager():
    """Patch recording_manager in the tools module."""
    mgr = MagicMock()
    with patch("unifi_protect_mcp.tools.recordings.recording_manager", mgr):
        yield mgr


class TestProtectGetRecordingStatusTool:
    @pytest.mark.asyncio
    async def test_success_all(self, mock_recording_manager):
        from unifi_protect_mcp.tools.recordings import protect_get_recording_status

        mock_recording_manager.get_recording_status = AsyncMock(
            return_value={
                "cameras": [{"camera_id": "cam-001", "is_recording": True}],
                "count": 1,
            }
        )
        result = await protect_get_recording_status()
        assert result["success"] is True
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_success_single(self, mock_recording_manager):
        from unifi_protect_mcp.tools.recordings import protect_get_recording_status

        mock_recording_manager.get_recording_status = AsyncMock(
            return_value={
                "cameras": [{"camera_id": "cam-001", "is_recording": True}],
                "count": 1,
            }
        )
        result = await protect_get_recording_status(camera_id="cam-001")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_camera_not_found(self, mock_recording_manager):
        from unifi_protect_mcp.tools.recordings import protect_get_recording_status

        mock_recording_manager.get_recording_status = AsyncMock(side_effect=ValueError("Camera not found: bad-id"))
        result = await protect_get_recording_status(camera_id="bad-id")
        assert result["success"] is False
        assert "Camera not found" in result["error"]

    @pytest.mark.asyncio
    async def test_error(self, mock_recording_manager):
        from unifi_protect_mcp.tools.recordings import protect_get_recording_status

        mock_recording_manager.get_recording_status = AsyncMock(side_effect=RuntimeError("connection lost"))
        result = await protect_get_recording_status()
        assert result["success"] is False
        assert "connection lost" in result["error"]


class TestProtectListRecordingsTool:
    @pytest.mark.asyncio
    async def test_success(self, mock_recording_manager):
        from unifi_protect_mcp.tools.recordings import protect_list_recordings

        mock_recording_manager.list_recordings = AsyncMock(return_value={"camera_id": "cam-001", "is_recording": True})
        result = await protect_list_recordings("cam-001")
        assert result["success"] is True
        assert result["data"]["camera"] == "cam-001"

    @pytest.mark.asyncio
    async def test_with_time_range(self, mock_recording_manager):
        from unifi_protect_mcp.tools.recordings import protect_list_recordings

        mock_recording_manager.list_recordings = AsyncMock(return_value={"camera_id": "cam-001"})
        result = await protect_list_recordings(
            "cam-001",
            start="2026-03-16T10:00:00Z",
            end="2026-03-16T12:00:00Z",
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_error(self, mock_recording_manager):
        from unifi_protect_mcp.tools.recordings import protect_list_recordings

        mock_recording_manager.list_recordings = AsyncMock(side_effect=RuntimeError("fail"))
        result = await protect_list_recordings("cam-001")
        assert result["success"] is False


class TestProtectExportClipTool:
    @pytest.mark.asyncio
    async def test_success(self, mock_recording_manager):
        from unifi_protect_mcp.tools.recordings import protect_export_clip

        mock_recording_manager.export_clip = AsyncMock(
            return_value={
                "camera_id": "cam-001",
                "exported": True,
                "size_bytes": 1024000,
            }
        )
        result = await protect_export_clip(
            "cam-001",
            start="2026-03-16T10:00:00Z",
            end="2026-03-16T10:30:00Z",
        )
        assert result["success"] is True
        assert result["data"]["exported"] is True

    @pytest.mark.asyncio
    async def test_invalid_start_time(self, mock_recording_manager):
        from unifi_protect_mcp.tools.recordings import protect_export_clip

        result = await protect_export_clip("cam-001", start="bad-date", end="2026-03-16T10:30:00Z")
        assert result["success"] is False
        assert "Invalid start time" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_end_time(self, mock_recording_manager):
        from unifi_protect_mcp.tools.recordings import protect_export_clip

        result = await protect_export_clip("cam-001", start="2026-03-16T10:00:00Z", end="bad-date")
        assert result["success"] is False
        assert "Invalid end time" in result["error"]

    @pytest.mark.asyncio
    async def test_error(self, mock_recording_manager):
        from unifi_protect_mcp.tools.recordings import protect_export_clip

        mock_recording_manager.export_clip = AsyncMock(side_effect=ValueError("End time must be after start time"))
        result = await protect_export_clip(
            "cam-001",
            start="2026-03-16T12:00:00Z",
            end="2026-03-16T10:00:00Z",
        )
        assert result["success"] is False
        assert "End time" in result["error"]


class TestProtectDeleteRecordingTool:
    @pytest.mark.asyncio
    async def test_not_supported(self, mock_recording_manager):
        from unifi_protect_mcp.tools.recordings import protect_delete_recording

        mock_recording_manager.delete_recording = AsyncMock(
            return_value={
                "camera_id": "cam-001",
                "supported": False,
                "message": "Individual recording deletion is not supported by the uiprotect API.",
            }
        )
        result = await protect_delete_recording(
            "cam-001",
            start="2026-03-16T10:00:00Z",
            end="2026-03-16T10:30:00Z",
        )
        assert result["success"] is False
        assert "not supported" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_invalid_times(self, mock_recording_manager):
        from unifi_protect_mcp.tools.recordings import protect_delete_recording

        result = await protect_delete_recording("cam-001", start="bad", end="bad")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_error(self, mock_recording_manager):
        from unifi_protect_mcp.tools.recordings import protect_delete_recording

        mock_recording_manager.delete_recording = AsyncMock(side_effect=RuntimeError("connection error"))
        result = await protect_delete_recording(
            "cam-001",
            start="2026-03-16T10:00:00Z",
            end="2026-03-16T10:30:00Z",
        )
        assert result["success"] is False
