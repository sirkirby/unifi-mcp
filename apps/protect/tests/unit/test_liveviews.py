"""Tests for LiveviewManager and liveview tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unifi_core.exceptions import UniFiNotFoundError

# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------


def _make_slot(**overrides):
    """Build a mock LiveviewSlot."""
    slot = MagicMock()
    slot.camera_ids = overrides.get("camera_ids", ["cam-001", "cam-002"])
    slot.cycle_mode = overrides.get("cycle_mode", "none")
    slot.cycle_interval = overrides.get("cycle_interval", 10)
    return slot


def _make_liveview(**overrides):
    """Build a mock Liveview object."""
    lv = MagicMock()
    lv.id = overrides.get("id", "lv-001")
    lv.name = overrides.get("name", "All Cameras")
    lv.is_default = overrides.get("is_default", True)
    lv.is_global = overrides.get("is_global", True)
    lv.layout = overrides.get("layout", 4)
    lv.owner_id = overrides.get("owner_id", "user-001")
    lv.slots = overrides.get("slots", [_make_slot()])
    return lv


def _make_camera(**overrides):
    """Build a minimal mock Camera for validation."""
    cam = MagicMock()
    cam.id = overrides.get("id", "cam-001")
    cam.name = overrides.get("name", "Front Door")
    return cam


def _make_bootstrap(liveviews=None, cameras=None):
    bs = MagicMock()
    bs.liveviews = liveviews or {}
    bs.cameras = cameras or {}
    return bs


@pytest.fixture
def mock_cm():
    """Create a mock ProtectConnectionManager with liveview data."""
    cm = MagicMock()
    lv = _make_liveview()
    cam1 = _make_camera(id="cam-001", name="Front Door")
    cam2 = _make_camera(id="cam-002", name="Back Yard")
    cm.client.bootstrap = _make_bootstrap(
        liveviews={"lv-001": lv},
        cameras={"cam-001": cam1, "cam-002": cam2},
    )
    return cm


@pytest.fixture
def mock_cm_multiple():
    """CM with multiple liveviews."""
    cm = MagicMock()
    lv1 = _make_liveview(id="lv-001", name="All Cameras")
    lv2 = _make_liveview(
        id="lv-002",
        name="Front Only",
        is_default=False,
        is_global=False,
        slots=[_make_slot(camera_ids=["cam-001"])],
    )
    cam1 = _make_camera(id="cam-001")
    cm.client.bootstrap = _make_bootstrap(
        liveviews={"lv-001": lv1, "lv-002": lv2},
        cameras={"cam-001": cam1},
    )
    return cm


# ===========================================================================
# LiveviewManager tests
# ===========================================================================


class TestLiveviewManagerListLiveviews:
    @pytest.mark.asyncio
    async def test_empty(self):
        from unifi_core.protect.managers.liveview_manager import LiveviewManager

        cm = MagicMock()
        cm.client.bootstrap = _make_bootstrap(liveviews={})
        mgr = LiveviewManager(cm)
        result = await mgr.list_liveviews()
        assert result == []

    @pytest.mark.asyncio
    async def test_single_liveview(self, mock_cm):
        from unifi_core.protect.managers.liveview_manager import LiveviewManager

        mgr = LiveviewManager(mock_cm)
        liveviews = await mgr.list_liveviews()
        assert len(liveviews) == 1
        lv = liveviews[0]
        assert lv["id"] == "lv-001"
        assert lv["name"] == "All Cameras"
        assert lv["is_default"] is True
        assert lv["is_global"] is True
        assert lv["layout"] == 4
        assert lv["slot_count"] == 1
        assert lv["camera_count"] == 2

    @pytest.mark.asyncio
    async def test_multiple_liveviews(self, mock_cm_multiple):
        from unifi_core.protect.managers.liveview_manager import LiveviewManager

        mgr = LiveviewManager(mock_cm_multiple)
        liveviews = await mgr.list_liveviews()
        assert len(liveviews) == 2
        names = [lv["name"] for lv in liveviews]
        assert "All Cameras" in names
        assert "Front Only" in names

    @pytest.mark.asyncio
    async def test_slot_details(self, mock_cm):
        from unifi_core.protect.managers.liveview_manager import LiveviewManager

        mgr = LiveviewManager(mock_cm)
        liveviews = await mgr.list_liveviews()
        slot = liveviews[0]["slots"][0]
        assert "cam-001" in slot["camera_ids"]
        assert "cam-002" in slot["camera_ids"]
        assert slot["cycle_mode"] == "none"
        assert slot["cycle_interval"] == 10


class TestLiveviewManagerCreateLiveview:
    @pytest.mark.asyncio
    async def test_validate_cameras(self, mock_cm):
        from unifi_core.protect.managers.liveview_manager import LiveviewManager

        mgr = LiveviewManager(mock_cm)
        result = await mgr.create_liveview("Test View", ["cam-001", "cam-002"])
        assert result["name"] == "Test View"
        assert result["camera_count"] == 2
        assert result["invalid_camera_ids"] == []
        assert result["supported"] is False

    @pytest.mark.asyncio
    async def test_invalid_camera_ids(self, mock_cm):
        from unifi_core.protect.managers.liveview_manager import LiveviewManager

        mgr = LiveviewManager(mock_cm)
        result = await mgr.create_liveview("Test View", ["cam-001", "cam-999"])
        assert result["camera_count"] == 1
        assert "cam-999" in result["invalid_camera_ids"]

    @pytest.mark.asyncio
    async def test_all_invalid(self, mock_cm):
        from unifi_core.protect.managers.liveview_manager import LiveviewManager

        mgr = LiveviewManager(mock_cm)
        result = await mgr.create_liveview("Test View", ["cam-999"])
        assert result["camera_count"] == 0
        assert result["invalid_camera_ids"] == ["cam-999"]


class TestLiveviewManagerDeleteLiveview:
    @pytest.mark.asyncio
    async def test_preview(self, mock_cm):
        from unifi_core.protect.managers.liveview_manager import LiveviewManager

        mgr = LiveviewManager(mock_cm)
        result = await mgr.delete_liveview("lv-001")
        assert result["liveview_id"] == "lv-001"
        assert result["liveview_name"] == "All Cameras"
        assert result["supported"] is False

    @pytest.mark.asyncio
    async def test_not_found(self, mock_cm):
        from unifi_core.protect.managers.liveview_manager import LiveviewManager

        mgr = LiveviewManager(mock_cm)
        with pytest.raises(UniFiNotFoundError):
            await mgr.delete_liveview("bad-id")


# ===========================================================================
# Liveview tools tests
# ===========================================================================


@pytest.fixture
def mock_liveview_manager():
    """Patch liveview_manager in the tools module."""
    mgr = MagicMock()
    with patch("unifi_protect_mcp.tools.liveviews.liveview_manager", mgr):
        yield mgr


class TestProtectListLiveviewsTool:
    @pytest.mark.asyncio
    async def test_success(self, mock_liveview_manager):
        from unifi_protect_mcp.tools.liveviews import protect_list_liveviews

        mock_liveview_manager.list_liveviews = AsyncMock(return_value=[{"id": "lv-001", "name": "All Cameras"}])
        result = await protect_list_liveviews()
        assert result["success"] is True
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_empty(self, mock_liveview_manager):
        from unifi_protect_mcp.tools.liveviews import protect_list_liveviews

        mock_liveview_manager.list_liveviews = AsyncMock(return_value=[])
        result = await protect_list_liveviews()
        assert result["success"] is True
        assert result["data"]["count"] == 0

    @pytest.mark.asyncio
    async def test_error(self, mock_liveview_manager):
        from unifi_protect_mcp.tools.liveviews import protect_list_liveviews

        mock_liveview_manager.list_liveviews = AsyncMock(side_effect=RuntimeError("fail"))
        result = await protect_list_liveviews()
        assert result["success"] is False
        assert "fail" in result["error"]


class TestProtectCreateLiveviewTool:
    @pytest.mark.asyncio
    async def test_not_supported(self, mock_liveview_manager):
        from unifi_protect_mcp.tools.liveviews import protect_create_liveview

        mock_liveview_manager.create_liveview = AsyncMock(
            return_value={
                "name": "Test",
                "camera_ids": ["cam-001"],
                "invalid_camera_ids": [],
                "camera_count": 1,
                "supported": False,
                "message": "Liveview creation is not directly supported by the uiprotect Python API.",
            }
        )
        result = await protect_create_liveview("Test", ["cam-001"])
        assert result["success"] is False
        assert "not directly supported" in result["error"]
        assert "data" in result

    @pytest.mark.asyncio
    async def test_empty_name(self, mock_liveview_manager):
        from unifi_protect_mcp.tools.liveviews import protect_create_liveview

        result = await protect_create_liveview("", ["cam-001"])
        assert result["success"] is False
        assert "name is required" in result["error"]

    @pytest.mark.asyncio
    async def test_no_cameras(self, mock_liveview_manager):
        from unifi_protect_mcp.tools.liveviews import protect_create_liveview

        result = await protect_create_liveview("Test", [])
        assert result["success"] is False
        assert "camera ID is required" in result["error"]

    @pytest.mark.asyncio
    async def test_error(self, mock_liveview_manager):
        from unifi_protect_mcp.tools.liveviews import protect_create_liveview

        mock_liveview_manager.create_liveview = AsyncMock(side_effect=RuntimeError("boom"))
        result = await protect_create_liveview("Test", ["cam-001"])
        assert result["success"] is False


class TestProtectDeleteLiveviewTool:
    @pytest.mark.asyncio
    async def test_not_supported(self, mock_liveview_manager):
        from unifi_protect_mcp.tools.liveviews import protect_delete_liveview

        mock_liveview_manager.delete_liveview = AsyncMock(
            return_value={
                "liveview_id": "lv-001",
                "liveview_name": "All Cameras",
                "supported": False,
                "message": "Liveview deletion is not directly supported by the uiprotect Python API.",
            }
        )
        result = await protect_delete_liveview("lv-001")
        assert result["success"] is False
        assert "not directly supported" in result["error"]

    @pytest.mark.asyncio
    async def test_not_found(self, mock_liveview_manager):
        from unifi_protect_mcp.tools.liveviews import protect_delete_liveview

        mock_liveview_manager.delete_liveview = AsyncMock(side_effect=ValueError("Liveview not found: bad-id"))
        result = await protect_delete_liveview("bad-id")
        assert result["success"] is False
        assert "Liveview not found" in result["error"]

    @pytest.mark.asyncio
    async def test_error(self, mock_liveview_manager):
        from unifi_protect_mcp.tools.liveviews import protect_delete_liveview

        mock_liveview_manager.delete_liveview = AsyncMock(side_effect=RuntimeError("boom"))
        result = await protect_delete_liveview("lv-001")
        assert result["success"] is False
