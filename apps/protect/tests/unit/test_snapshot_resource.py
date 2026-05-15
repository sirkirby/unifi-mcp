"""Tests for camera snapshot MCP resources."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_camera_manager():
    """Patch camera_manager in the snapshots resource module."""
    mgr = MagicMock()
    with patch("unifi_protect_mcp.resources.snapshots.camera_manager", mgr):
        yield mgr


# ---------------------------------------------------------------------------
# protect://cameras/{camera_id}/snapshot  (resource template)
# ---------------------------------------------------------------------------


class TestCameraSnapshotResource:
    """Tests for the camera_snapshot resource template function."""

    @pytest.mark.asyncio
    async def test_returns_jpeg_bytes(self, mock_camera_manager):
        from unifi_protect_mcp.resources.snapshots import camera_snapshot

        fake_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # JPEG-like bytes
        mock_camera_manager.get_snapshot = AsyncMock(return_value=fake_jpeg)

        result = await camera_snapshot("cam-001")
        assert isinstance(result, bytes)
        assert result == fake_jpeg
        mock_camera_manager.get_snapshot.assert_awaited_once_with("cam-001")

    @pytest.mark.asyncio
    async def test_large_snapshot(self, mock_camera_manager):
        from unifi_protect_mcp.resources.snapshots import camera_snapshot

        # Simulate a realistic ~500KB JPEG snapshot
        large_jpeg = b"\xff\xd8\xff\xe0" + b"\xab" * 500_000
        mock_camera_manager.get_snapshot = AsyncMock(return_value=large_jpeg)

        result = await camera_snapshot("cam-large")
        assert len(result) == 500_004
        mock_camera_manager.get_snapshot.assert_awaited_once_with("cam-large")

    @pytest.mark.asyncio
    async def test_camera_not_found_raises(self, mock_camera_manager):
        from unifi_protect_mcp.resources.snapshots import camera_snapshot

        mock_camera_manager.get_snapshot = AsyncMock(side_effect=ValueError("Camera not found: cam-999"))

        with pytest.raises(ValueError, match="Camera not found"):
            await camera_snapshot("cam-999")

    @pytest.mark.asyncio
    async def test_snapshot_fetch_failure_raises(self, mock_camera_manager):
        from unifi_protect_mcp.resources.snapshots import camera_snapshot

        mock_camera_manager.get_snapshot = AsyncMock(
            side_effect=RuntimeError("Failed to get snapshot from camera cam-002: camera returned None")
        )

        with pytest.raises(RuntimeError, match="Failed to get snapshot"):
            await camera_snapshot("cam-002")

    @pytest.mark.asyncio
    async def test_connection_error_raises(self, mock_camera_manager):
        from unifi_protect_mcp.resources.snapshots import camera_snapshot

        mock_camera_manager.get_snapshot = AsyncMock(side_effect=ConnectionError("NVR unreachable"))

        with pytest.raises(ConnectionError, match="NVR unreachable"):
            await camera_snapshot("cam-003")


# ---------------------------------------------------------------------------
# protect://cameras/snapshots  (discovery index resource)
# ---------------------------------------------------------------------------


class TestCameraSnapshotIndexResource:
    """Tests for the camera_snapshot_index discovery resource."""

    @pytest.mark.asyncio
    async def test_returns_json_index(self, mock_camera_manager):
        from unifi_protect_mcp.resources.snapshots import camera_snapshot_index

        mock_camera_manager.list_cameras = AsyncMock(
            return_value=[
                {
                    "id": "cam-001",
                    "name": "Front Door",
                    "model": "G4 Pro",
                    "is_connected": True,
                },
                {
                    "id": "cam-002",
                    "name": "Backyard",
                    "model": "G5 Bullet",
                    "is_connected": False,
                },
            ]
        )

        result = await camera_snapshot_index()
        data = json.loads(result)

        assert isinstance(data, list)
        assert len(data) == 2

        assert data[0]["camera_id"] == "cam-001"
        assert data[0]["name"] == "Front Door"
        assert data[0]["model"] == "G4 Pro"
        assert data[0]["is_connected"] is True
        assert data[0]["snapshot_uri"] == "protect://cameras/cam-001/snapshot"

        assert data[1]["camera_id"] == "cam-002"
        assert data[1]["name"] == "Backyard"
        assert data[1]["snapshot_uri"] == "protect://cameras/cam-002/snapshot"

    @pytest.mark.asyncio
    async def test_empty_camera_list(self, mock_camera_manager):
        from unifi_protect_mcp.resources.snapshots import camera_snapshot_index

        mock_camera_manager.list_cameras = AsyncMock(return_value=[])

        result = await camera_snapshot_index()
        data = json.loads(result)

        assert isinstance(data, list)
        assert len(data) == 0

    @pytest.mark.asyncio
    async def test_error_returns_json_error(self, mock_camera_manager):
        from unifi_protect_mcp.resources.snapshots import camera_snapshot_index

        mock_camera_manager.list_cameras = AsyncMock(side_effect=RuntimeError("bootstrap not ready"))

        result = await camera_snapshot_index()
        data = json.loads(result)

        assert "error" in data
        assert "bootstrap not ready" in data["error"]

    @pytest.mark.asyncio
    async def test_missing_optional_fields(self, mock_camera_manager):
        """Cameras with minimal fields should still produce valid index entries."""
        from unifi_protect_mcp.resources.snapshots import camera_snapshot_index

        mock_camera_manager.list_cameras = AsyncMock(
            return_value=[
                {
                    "id": "cam-min",
                    "name": "Minimal Camera",
                    # no 'model' or 'is_connected' keys
                },
            ]
        )

        result = await camera_snapshot_index()
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["camera_id"] == "cam-min"
        assert data[0]["name"] == "Minimal Camera"
        assert data[0]["model"] is None
        assert data[0]["is_connected"] is None
        assert data[0]["snapshot_uri"] == "protect://cameras/cam-min/snapshot"


# ---------------------------------------------------------------------------
# Resource registration integration
# ---------------------------------------------------------------------------


class TestSnapshotResourceRegistration:
    """Verify that resource decorators register correctly with the server."""

    def test_snapshot_template_registered(self):
        """The camera_snapshot function should be registered as a resource template."""
        # Import the module so its @server.resource decorators run; with pytest-xdist
        # workers are isolated so we can't rely on another test triggering the import.
        import unifi_protect_mcp.resources.snapshots  # noqa: F401
        from unifi_protect_mcp.runtime import server

        templates = server._resource_manager.list_templates()
        template_uris = [t.uri_template for t in templates]
        assert "protect://cameras/{camera_id}/snapshot" in template_uris

    def test_snapshot_index_registered(self):
        """The camera_snapshot_index function should be registered as a concrete resource."""
        import unifi_protect_mcp.resources.snapshots  # noqa: F401
        from unifi_protect_mcp.runtime import server

        resources = server._resource_manager.list_resources()
        resource_uris = [str(r.uri) for r in resources]
        assert "protect://cameras/snapshots" in resource_uris

    def test_snapshot_template_mime_type(self):
        """The snapshot template should have image/jpeg MIME type."""
        import unifi_protect_mcp.resources.snapshots  # noqa: F401
        from unifi_protect_mcp.runtime import server

        templates = server._resource_manager.list_templates()
        snapshot_templates = [t for t in templates if t.uri_template == "protect://cameras/{camera_id}/snapshot"]
        assert len(snapshot_templates) == 1
        assert snapshot_templates[0].mime_type == "image/jpeg"

    def test_snapshot_index_mime_type(self):
        """The snapshot index should have application/json MIME type."""
        import unifi_protect_mcp.resources.snapshots  # noqa: F401
        from unifi_protect_mcp.runtime import server

        resources = server._resource_manager.list_resources()
        index_resources = [r for r in resources if str(r.uri) == "protect://cameras/snapshots"]
        assert len(index_resources) == 1
        assert index_resources[0].mime_type == "application/json"

    def test_snapshot_template_has_mcp_metadata(self):
        """The snapshot template should expose MCP title, annotations, and namespaced metadata."""
        import unifi_protect_mcp.resources.snapshots  # noqa: F401
        from unifi_protect_mcp.runtime import server

        templates = server._resource_manager.list_templates()
        snapshot_templates = [t for t in templates if t.uri_template == "protect://cameras/{camera_id}/snapshot"]
        assert len(snapshot_templates) == 1
        template = snapshot_templates[0]

        assert template.title == "Live Camera Snapshot"
        assert template.annotations is not None
        assert template.annotations.audience == ["user", "assistant"]
        assert template.annotations.priority == 0.7
        assert template.meta == {
            "io.unifi.resourceKind": "camera-snapshot",
            "io.unifi.updateMode": "on-demand",
            "io.unifi.protocolSubscribe": False,
            "io.unifi.relatedTools": ["protect_get_snapshot", "protect_list_cameras"],
        }

    def test_snapshot_index_has_mcp_metadata(self):
        """The snapshot index should expose MCP title, annotations, and namespaced metadata."""
        import unifi_protect_mcp.resources.snapshots  # noqa: F401
        from unifi_protect_mcp.runtime import server

        resources = server._resource_manager.list_resources()
        index_resources = [r for r in resources if str(r.uri) == "protect://cameras/snapshots"]
        assert len(index_resources) == 1
        index = index_resources[0]

        assert index.title == "Camera Snapshot Index"
        assert index.annotations is not None
        assert index.annotations.audience == ["assistant"]
        assert index.annotations.priority == 0.6
        assert index.meta == {
            "io.unifi.resourceKind": "snapshot-index",
            "io.unifi.updateMode": "poll",
            "io.unifi.pollIntervalMs": 10000,
            "io.unifi.protocolSubscribe": False,
            "io.unifi.relatedTools": ["protect_get_snapshot", "protect_list_cameras"],
        }


# ---------------------------------------------------------------------------
# protect_get_snapshot tool (include_image=True mode)
# ---------------------------------------------------------------------------


class TestGetSnapshotToolIncludeImage:
    """Verify the protect_get_snapshot tool correctly base64-encodes snapshots."""

    @pytest.fixture
    def mock_cam_manager_for_tool(self):
        """Patch camera_manager in the tools module."""
        mgr = MagicMock()
        with patch("unifi_protect_mcp.tools.cameras.camera_manager", mgr):
            yield mgr

    @pytest.mark.asyncio
    async def test_include_image_returns_base64(self, mock_cam_manager_for_tool):
        import base64

        from unifi_protect_mcp.tools.cameras import protect_get_snapshot

        fake_jpeg = b"\xff\xd8\xff\xe0JFIF_FAKE_DATA"
        mock_cam_manager_for_tool.get_snapshot = AsyncMock(return_value=fake_jpeg)

        result = await protect_get_snapshot(camera_id="cam-001", include_image=True)

        assert result["success"] is True
        assert result["data"]["content_type"] == "image/jpeg"
        # Verify the base64 round-trips back to original bytes
        decoded = base64.b64decode(result["data"]["image_base64"])
        assert decoded == fake_jpeg

    @pytest.mark.asyncio
    async def test_include_image_with_dimensions(self, mock_cam_manager_for_tool):
        from unifi_protect_mcp.tools.cameras import protect_get_snapshot

        fake_jpeg = b"\xff\xd8\xff\xe0SMALL"
        mock_cam_manager_for_tool.get_snapshot = AsyncMock(return_value=fake_jpeg)

        result = await protect_get_snapshot(camera_id="cam-001", include_image=True, width=640, height=480)

        assert result["success"] is True
        mock_cam_manager_for_tool.get_snapshot.assert_awaited_once_with("cam-001", width=640, height=480)

    @pytest.mark.asyncio
    async def test_no_include_image_returns_uri(self, mock_cam_manager_for_tool):
        from unifi_protect_mcp.tools.cameras import protect_get_snapshot

        result = await protect_get_snapshot(camera_id="cam-001", include_image=False)

        assert result["success"] is True
        assert result["data"]["snapshot_url"] == "protect://cameras/cam-001/snapshot"
        # Should NOT have called get_snapshot when include_image is False
        mock_cam_manager_for_tool.get_snapshot.assert_not_called()

    @pytest.mark.asyncio
    async def test_include_image_error(self, mock_cam_manager_for_tool):
        from unifi_protect_mcp.tools.cameras import protect_get_snapshot

        mock_cam_manager_for_tool.get_snapshot = AsyncMock(side_effect=ValueError("Camera not found: cam-bad"))

        result = await protect_get_snapshot(camera_id="cam-bad", include_image=True)

        assert result["success"] is False
        assert "Camera not found" in result["error"]
