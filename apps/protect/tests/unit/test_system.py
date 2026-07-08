"""Tests for SystemManager and system tools."""

from datetime import datetime, timedelta, timezone
from enum import Enum
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from uiprotect.exceptions import BadRequest

from unifi_core.exceptions import UniFiNotFoundError

# ---------------------------------------------------------------------------
# Fixtures: mock pyunifiprotect data models
# ---------------------------------------------------------------------------


class _FakeStorageType(Enum):
    HDD = "hdd"


def _make_nvr(**overrides):
    """Build a mock NVR object with sensible defaults."""
    nvr = MagicMock()
    nvr.id = overrides.get("id", "nvr-001")
    nvr.name = overrides.get("name", "Test NVR")
    nvr.type = overrides.get("type", "UDR")
    nvr.hardware_platform = overrides.get("hardware_platform", "unvr")
    nvr.firmware_version = overrides.get("firmware_version", "4.0.10")
    nvr.version = overrides.get("version", "4.0.10")
    nvr.host = overrides.get("host", "192.168.1.1")
    nvr.mac = overrides.get("mac", "AA:BB:CC:DD:EE:FF")
    nvr.uptime = overrides.get("uptime", timedelta(hours=48))
    nvr.up_since = overrides.get("up_since", datetime(2026, 3, 15, tzinfo=timezone.utc))
    nvr.is_updating = overrides.get("is_updating", False)

    # storage_stats
    recording = MagicMock()
    recording.total = 1_000_000_000
    recording.used = 500_000_000
    recording.available = 500_000_000
    storage = MagicMock()
    storage.utilization = 50.0
    storage.recording_space = recording
    storage.capacity = timedelta(days=14)
    storage.remaining_capacity = timedelta(days=7)
    nvr.storage_stats = storage

    # system_info
    cpu = MagicMock()
    cpu.average_load = 0.42
    cpu.temperature = 55.0
    mem = MagicMock()
    mem.available = 2_000_000_000
    mem.free = 1_000_000_000
    mem.total = 4_000_000_000
    stor = MagicMock()
    stor.available = 500_000_000
    stor.size = 1_000_000_000
    stor.used = 500_000_000
    stor.is_recycling = False
    stor.type = _FakeStorageType.HDD
    sys_info = MagicMock()
    sys_info.cpu = cpu
    sys_info.memory = mem
    sys_info.storage = stor
    nvr.system_info = sys_info

    # firmware
    nvr.is_protect_updatable = False
    nvr.is_ucore_updatable = False
    nvr.last_device_fw_updates_checked_at = datetime(2026, 3, 16, tzinfo=timezone.utc)

    return nvr


def _make_viewer(**overrides):
    v = MagicMock()
    v.id = overrides.get("id", "viewer-001")
    v.name = overrides.get("name", "Office Viewer")
    v.type = overrides.get("type", "UP Viewport")
    v.mac = overrides.get("mac", "11:22:33:44:55:66")
    v.host = overrides.get("host", "192.168.1.50")
    v.firmware_version = overrides.get("firmware_version", "2.0.1")
    v.is_connected = overrides.get("is_connected", True)
    v.is_updating = overrides.get("is_updating", False)
    v.uptime = overrides.get("uptime", timedelta(hours=24))
    v.state = overrides.get("state", "CONNECTED")
    v.software_version = overrides.get("software_version", "2.0.1")
    v.liveview_id = overrides.get("liveview_id", "lv-001")
    v.latest_firmware_version = overrides.get("latest_firmware_version", "2.0.1")
    return v


def _make_public_viewer(**overrides):
    return SimpleNamespace(
        id=overrides.get("id", "viewer-001"),
        name=overrides.get("name", "Office Viewer"),
        liveview_id=overrides.get("liveview_id", "lv-001"),
    )


def _make_public_liveview(**overrides):
    return SimpleNamespace(
        id=overrides.get("id", "lv-002"),
        name=overrides.get("name", "Lobby Liveview"),
    )


def _make_camera(**overrides):
    c = MagicMock()
    c.id = overrides.get("id", "cam-001")
    c.name = overrides.get("name", "Front Door")
    c.type = overrides.get("type", "G4 Bullet")
    c.firmware_version = overrides.get("firmware_version", "4.69.55")
    c.latest_firmware_version = overrides.get("latest_firmware_version", "4.69.55")
    c.is_updating = overrides.get("is_updating", False)
    return c


def _make_bootstrap(
    nvr=None, cameras=None, lights=None, sensors=None, viewers=None, chimes=None, bridges=None, doorlocks=None
):
    bs = MagicMock()
    bs.nvr = nvr or _make_nvr()
    bs.cameras = cameras or {}
    bs.lights = lights or {}
    bs.sensors = sensors or {}
    bs.viewers = viewers or {}
    bs.chimes = chimes or {}
    bs.bridges = bridges or {}
    bs.doorlocks = doorlocks or {}
    return bs


@pytest.fixture
def mock_cm():
    """Create a mock ProtectConnectionManager with a mocked client.bootstrap."""
    cm = MagicMock()
    cm.client.bootstrap = _make_bootstrap()
    return cm


# ===========================================================================
# SystemManager tests
# ===========================================================================


class TestSystemManagerGetSystemInfo:
    @pytest.mark.asyncio
    async def test_basic_fields(self, mock_cm):
        from unifi_core.protect.managers.system_manager import SystemManager

        mgr = SystemManager(mock_cm)
        info = await mgr.get_system_info()

        assert info["id"] == "nvr-001"
        assert info["name"] == "Test NVR"
        assert info["model"] == "UDR"
        assert info["firmware_version"] == "4.0.10"
        assert info["uptime_seconds"] == 48 * 3600
        assert info["is_updating"] is False
        assert info["camera_count"] == 0
        assert "storage" in info

    @pytest.mark.asyncio
    async def test_storage_info(self, mock_cm):
        from unifi_core.protect.managers.system_manager import SystemManager

        mgr = SystemManager(mock_cm)
        info = await mgr.get_system_info()

        storage = info["storage"]
        assert storage["utilization_pct"] == 50.0
        assert storage["recording_space_total_bytes"] == 1_000_000_000
        assert storage["recording_space_used_bytes"] == 500_000_000

    @pytest.mark.asyncio
    async def test_device_counts(self):
        from unifi_core.protect.managers.system_manager import SystemManager

        bs = _make_bootstrap(
            cameras={"c1": _make_camera()},
            viewers={"v1": _make_viewer()},
        )
        cm = MagicMock()
        cm.client.bootstrap = bs

        mgr = SystemManager(cm)
        info = await mgr.get_system_info()
        assert info["camera_count"] == 1
        assert info["viewer_count"] == 1

    @pytest.mark.asyncio
    async def test_none_uptime(self):
        from unifi_core.protect.managers.system_manager import SystemManager

        nvr = _make_nvr(uptime=None, up_since=None)
        cm = MagicMock()
        cm.client.bootstrap = _make_bootstrap(nvr=nvr)

        mgr = SystemManager(cm)
        info = await mgr.get_system_info()
        assert info["uptime_seconds"] is None
        assert info["up_since"] is None

    @pytest.mark.asyncio
    async def test_missing_hardware_platform(self):
        from unifi_core.protect.managers.system_manager import SystemManager

        nvr = _make_nvr()
        del nvr.hardware_platform
        cm = MagicMock()
        cm.client.bootstrap = _make_bootstrap(nvr=nvr)

        mgr = SystemManager(cm)
        info = await mgr.get_system_info()
        assert info["hardware_platform"] is None


class TestSystemManagerGetHealth:
    @pytest.mark.asyncio
    async def test_health_fields(self, mock_cm):
        from unifi_core.protect.managers.system_manager import SystemManager

        mgr = SystemManager(mock_cm)
        health = await mgr.get_health()

        assert health["cpu"]["average_load"] == 0.42
        assert health["cpu"]["temperature_c"] == 55.0
        assert health["memory"]["total_bytes"] == 4_000_000_000
        assert health["storage"]["size_bytes"] == 1_000_000_000
        assert health["is_updating"] is False


class TestSystemManagerListViewers:
    @pytest.mark.asyncio
    async def test_empty_viewers(self, mock_cm):
        from unifi_core.protect.managers.system_manager import SystemManager

        mgr = SystemManager(mock_cm)
        viewers = await mgr.list_viewers()
        assert viewers == []

    @pytest.mark.asyncio
    async def test_with_viewer(self):
        from unifi_core.protect.managers.system_manager import SystemManager

        viewer = _make_viewer()
        bs = _make_bootstrap(viewers={"v1": viewer})
        cm = MagicMock()
        cm.client.bootstrap = bs

        mgr = SystemManager(cm)
        viewers = await mgr.list_viewers()
        assert len(viewers) == 1
        assert viewers[0]["id"] == "viewer-001"
        assert viewers[0]["name"] == "Office Viewer"
        assert viewers[0]["is_connected"] is True


class TestSystemManagerUpdateViewer:
    @pytest.mark.asyncio
    async def test_missing_api_key_fails_before_public_get_call(self):
        from unifi_core.protect.managers.system_manager import SystemManager

        cm = MagicMock()
        cm.require_public_api_key = MagicMock(
            side_effect=ValueError(
                "Cannot update viewer: UniFi Protect public Integration API access requires an API key."
            )
        )
        cm.client.get_viewer_public = AsyncMock()
        mgr = SystemManager(cm)

        with pytest.raises(ValueError, match="requires an API key"):
            await mgr.update_viewer("viewer-001", {"name": "Lobby Viewer"})

        cm.require_public_api_key.assert_called_once_with("update viewer")
        cm.client.get_viewer_public.assert_not_called()

    @pytest.mark.asyncio
    async def test_preview_returns_current_and_proposed_name_and_liveview(self):
        from unifi_core.protect.managers.system_manager import SystemManager

        cm = MagicMock()
        cm.require_public_api_key = MagicMock()
        cm.client.get_viewer_public = AsyncMock(
            return_value=_make_public_viewer(name="Office Viewer", liveview_id="lv-001")
        )
        cm.client.get_liveview_public = AsyncMock(return_value=_make_public_liveview(id="lv-002"))
        mgr = SystemManager(cm)

        result = await mgr.update_viewer(
            "viewer-001",
            {"name": "Lobby Viewer", "liveview_id": "lv-002"},
        )

        assert result["viewer_id"] == "viewer-001"
        assert result["viewer_name"] == "Office Viewer"
        assert result["current_state"] == {"name": "Office Viewer", "liveview_id": "lv-001"}
        assert result["proposed_changes"] == {"name": "Lobby Viewer", "liveview_id": "lv-002"}
        cm.require_public_api_key.assert_called_once_with("update viewer")
        cm.client.get_viewer_public.assert_awaited_once_with("viewer-001")
        cm.client.get_liveview_public.assert_awaited_once_with("lv-002")

    @pytest.mark.asyncio
    async def test_preview_name_only_leaves_liveview_unchanged(self):
        from unifi_core.protect.managers.system_manager import SystemManager

        cm = MagicMock()
        cm.require_public_api_key = MagicMock()
        cm.client.get_viewer_public = AsyncMock(
            return_value=_make_public_viewer(name="Office Viewer", liveview_id="lv-001")
        )
        cm.client.get_liveview_public = AsyncMock()
        mgr = SystemManager(cm)

        result = await mgr.update_viewer("viewer-001", {"name": "Lobby Viewer"})

        assert result["current_state"] == {"name": "Office Viewer"}
        assert result["proposed_changes"] == {"name": "Lobby Viewer"}
        cm.client.get_liveview_public.assert_not_called()

    @pytest.mark.asyncio
    async def test_confirm_validates_liveview_and_passes_public_liveview_kwarg(self):
        from unifi_core.protect.managers.system_manager import SystemManager

        cm = MagicMock()
        cm.require_public_api_key = MagicMock()
        cm.client.get_viewer_public = AsyncMock(
            return_value=_make_public_viewer(name="Office Viewer", liveview_id="lv-001")
        )
        cm.client.get_liveview_public = AsyncMock(return_value=_make_public_liveview(id="lv-002"))
        cm.client.update_viewer_public = AsyncMock(
            return_value=_make_public_viewer(name="Office Viewer", liveview_id="lv-002")
        )
        mgr = SystemManager(cm)

        result = await mgr.apply_viewer_update("viewer-001", {"liveview_id": "lv-002"})

        assert result["viewer_id"] == "viewer-001"
        assert result["viewer_name"] == "Office Viewer"
        assert result["applied"] == {"liveview_id": "lv-002"}
        assert result["updated_state"] == {"liveview_id": "lv-002"}
        cm.client.get_viewer_public.assert_awaited_once_with("viewer-001")
        cm.client.get_liveview_public.assert_awaited_once_with("lv-002")
        cm.client.update_viewer_public.assert_awaited_once_with("viewer-001", liveview="lv-002")

    @pytest.mark.asyncio
    async def test_confirm_clear_liveview_passes_null_public_liveview_kwarg(self):
        from unifi_core.protect.managers.system_manager import SystemManager

        cm = MagicMock()
        cm.require_public_api_key = MagicMock()
        cm.client.get_viewer_public = AsyncMock(
            return_value=_make_public_viewer(name="Office Viewer", liveview_id="lv-001")
        )
        cm.client.get_liveview_public = AsyncMock()
        cm.client.update_viewer_public = AsyncMock(
            return_value=_make_public_viewer(name="Office Viewer", liveview_id=None)
        )
        mgr = SystemManager(cm)

        result = await mgr.apply_viewer_update("viewer-001", {"clear_liveview": True})

        assert result["applied"] == {"liveview_id": None}
        assert result["updated_state"] == {"liveview_id": None}
        cm.client.get_liveview_public.assert_not_called()
        cm.client.update_viewer_public.assert_awaited_once_with("viewer-001", liveview=None)

    @pytest.mark.asyncio
    async def test_empty_settings_fail_cleanly(self):
        from unifi_core.protect.managers.system_manager import SystemManager

        cm = MagicMock()
        cm.require_public_api_key = MagicMock()
        mgr = SystemManager(cm)

        with pytest.raises(ValueError, match="No viewer settings provided"):
            await mgr.update_viewer("viewer-001", {})

        cm.require_public_api_key.assert_not_called()

    @pytest.mark.asyncio
    async def test_conflicting_liveview_args_fail_cleanly(self):
        from unifi_core.protect.managers.system_manager import SystemManager

        cm = MagicMock()
        cm.require_public_api_key = MagicMock()
        mgr = SystemManager(cm)

        with pytest.raises(ValueError, match="liveview_id and clear_liveview=True cannot be used together"):
            await mgr.update_viewer("viewer-001", {"liveview_id": "lv-002", "clear_liveview": True})

        cm.require_public_api_key.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_liveview_maps_to_not_found(self):
        from unifi_core.protect.managers.system_manager import SystemManager

        cm = MagicMock()
        cm.require_public_api_key = MagicMock()
        cm.client.get_viewer_public = AsyncMock(return_value=_make_public_viewer())
        cm.client.get_liveview_public = AsyncMock(
            side_effect=BadRequest("Request failed: /v1/liveviews/missing - Status: 404 - Reason: Not Found")
        )
        mgr = SystemManager(cm)

        with pytest.raises(UniFiNotFoundError) as exc_info:
            await mgr.update_viewer("viewer-001", {"liveview_id": "missing"})

        assert "missing" in str(exc_info.value)


class TestSystemManagerGetFirmwareStatus:
    @pytest.mark.asyncio
    async def test_no_devices(self, mock_cm):
        from unifi_core.protect.managers.system_manager import SystemManager

        mgr = SystemManager(mock_cm)
        status = await mgr.get_firmware_status()

        assert status["nvr"]["id"] == "nvr-001"
        assert status["total_devices"] == 0
        assert status["devices_with_updates"] == 0

    @pytest.mark.asyncio
    async def test_device_with_update(self):
        from unifi_core.protect.managers.system_manager import SystemManager

        cam = _make_camera(
            firmware_version="4.69.50",
            latest_firmware_version="4.69.55",
        )
        bs = _make_bootstrap(cameras={"c1": cam})
        cm = MagicMock()
        cm.client.bootstrap = bs

        mgr = SystemManager(cm)
        status = await mgr.get_firmware_status()

        assert status["total_devices"] == 1
        assert status["devices_with_updates"] == 1
        assert status["devices"][0]["update_available"] is True
        assert status["devices"][0]["current_firmware"] == "4.69.50"
        assert status["devices"][0]["latest_firmware"] == "4.69.55"

    @pytest.mark.asyncio
    async def test_device_up_to_date(self):
        from unifi_core.protect.managers.system_manager import SystemManager

        cam = _make_camera()  # same version for current and latest
        bs = _make_bootstrap(cameras={"c1": cam})
        cm = MagicMock()
        cm.client.bootstrap = bs

        mgr = SystemManager(cm)
        status = await mgr.get_firmware_status()
        assert status["devices_with_updates"] == 0
        assert status["devices"][0]["update_available"] is False

    @pytest.mark.asyncio
    async def test_missing_optional_device_collection(self):
        from unifi_core.protect.managers.system_manager import SystemManager

        cam = _make_camera()
        bs = _make_bootstrap(cameras={"c1": cam})
        del bs.doorlocks
        cm = MagicMock()
        cm.client.bootstrap = bs

        mgr = SystemManager(cm)
        status = await mgr.get_firmware_status()

        assert status["total_devices"] == 1
        assert status["devices"][0]["type"] == "camera"


# ===========================================================================
# System tools tests
# ===========================================================================


@pytest.fixture
def mock_system_manager():
    """Patch system_manager in the tools module."""
    mgr = MagicMock()
    with patch("unifi_protect_mcp.tools.system.system_manager", mgr):
        yield mgr


class TestProtectGetSystemInfoTool:
    @pytest.mark.asyncio
    async def test_success(self, mock_system_manager):
        from unifi_protect_mcp.tools.system import protect_get_system_info

        mock_system_manager.get_system_info = AsyncMock(return_value={"id": "nvr-001", "name": "Test"})
        result = await protect_get_system_info()
        assert result["success"] is True
        assert result["data"]["id"] == "nvr-001"

    @pytest.mark.asyncio
    async def test_error(self, mock_system_manager):
        from unifi_protect_mcp.tools.system import protect_get_system_info

        mock_system_manager.get_system_info = AsyncMock(side_effect=RuntimeError("boom"))
        result = await protect_get_system_info()
        assert result["success"] is False
        assert "boom" in result["error"]


class TestProtectGetHealthTool:
    @pytest.mark.asyncio
    async def test_success(self, mock_system_manager):
        from unifi_protect_mcp.tools.system import protect_get_health

        mock_system_manager.get_health = AsyncMock(return_value={"cpu": {"average_load": 0.1}})
        result = await protect_get_health()
        assert result["success"] is True
        assert "cpu" in result["data"]

    @pytest.mark.asyncio
    async def test_error(self, mock_system_manager):
        from unifi_protect_mcp.tools.system import protect_get_health

        mock_system_manager.get_health = AsyncMock(side_effect=RuntimeError("fail"))
        result = await protect_get_health()
        assert result["success"] is False


class TestProtectListViewersTool:
    @pytest.mark.asyncio
    async def test_success(self, mock_system_manager):
        from unifi_protect_mcp.tools.system import protect_list_viewers

        mock_system_manager.list_viewers = AsyncMock(return_value=[{"id": "v1"}])
        result = await protect_list_viewers()
        assert result["success"] is True
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_error(self, mock_system_manager):
        from unifi_protect_mcp.tools.system import protect_list_viewers

        mock_system_manager.list_viewers = AsyncMock(side_effect=RuntimeError("x"))
        result = await protect_list_viewers()
        assert result["success"] is False


class TestProtectUpdateViewerTool:
    @pytest.mark.asyncio
    async def test_preview(self, mock_system_manager):
        from unifi_protect_mcp.tools.system import protect_update_viewer

        mock_system_manager.update_viewer = AsyncMock(
            return_value={
                "viewer_id": "viewer-001",
                "viewer_name": "Office Viewer",
                "current_state": {"name": "Office Viewer", "liveview_id": "lv-001"},
                "proposed_changes": {"name": "Lobby Viewer", "liveview_id": "lv-002"},
            }
        )

        result = await protect_update_viewer(
            "viewer-001",
            {"name": "Lobby Viewer", "liveview_id": "lv-002"},
            confirm=False,
        )

        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["resource_type"] == "viewer_settings"
        assert result["preview"]["current"]["liveview_id"] == "lv-001"
        assert result["preview"]["proposed"]["liveview_id"] == "lv-002"
        mock_system_manager.update_viewer.assert_awaited_once_with(
            "viewer-001",
            {"name": "Lobby Viewer", "liveview_id": "lv-002"},
        )

    @pytest.mark.asyncio
    async def test_confirm(self, mock_system_manager):
        from unifi_protect_mcp.tools.system import protect_update_viewer

        mock_system_manager.apply_viewer_update = AsyncMock(
            return_value={
                "viewer_id": "viewer-001",
                "viewer_name": "Office Viewer",
                "applied": {"liveview_id": None},
                "updated_state": {"liveview_id": None},
            }
        )

        result = await protect_update_viewer("viewer-001", {"clear_liveview": True}, confirm=True)

        assert result["success"] is True
        assert result["data"]["applied"] == {"liveview_id": None}
        mock_system_manager.apply_viewer_update.assert_awaited_once_with(
            "viewer-001",
            {"clear_liveview": True},
        )

    @pytest.mark.asyncio
    async def test_validation_error(self, mock_system_manager):
        from unifi_protect_mcp.tools.system import protect_update_viewer

        mock_system_manager.update_viewer = AsyncMock(
            side_effect=ValueError("liveview_id and clear_liveview=True cannot be used together")
        )

        result = await protect_update_viewer(
            "viewer-001",
            {"liveview_id": "lv-002", "clear_liveview": True},
            confirm=False,
        )

        assert result["success"] is False
        assert "liveview_id and clear_liveview=True cannot be used together" in result["error"]

    @pytest.mark.asyncio
    async def test_manager_exception_maps_to_operation_error(self, mock_system_manager):
        from unifi_protect_mcp.tools.system import protect_update_viewer

        mock_system_manager.update_viewer = AsyncMock(side_effect=RuntimeError("network down"))

        result = await protect_update_viewer("viewer-001", {"name": "Lobby Viewer"}, confirm=False)

        assert result["success"] is False
        assert result["error"] == "Failed to update viewer: network down"


class TestProtectGetFirmwareStatusTool:
    @pytest.mark.asyncio
    async def test_success(self, mock_system_manager):
        from unifi_protect_mcp.tools.system import protect_get_firmware_status

        mock_system_manager.get_firmware_status = AsyncMock(return_value={"total_devices": 3})
        result = await protect_get_firmware_status()
        assert result["success"] is True
        assert result["data"]["total_devices"] == 3

    @pytest.mark.asyncio
    async def test_error(self, mock_system_manager):
        from unifi_protect_mcp.tools.system import protect_get_firmware_status

        mock_system_manager.get_firmware_status = AsyncMock(side_effect=RuntimeError("err"))
        result = await protect_get_firmware_status()
        assert result["success"] is False
