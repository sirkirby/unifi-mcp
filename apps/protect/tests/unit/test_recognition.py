"""Tests for Protect recognition manager and tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_cm():
    cm = MagicMock()
    cm.client.api_request = AsyncMock()
    return cm


class TestRecognitionManager:
    @pytest.mark.asyncio
    async def test_list_known_faces_success(self, mock_cm):
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        mock_cm.client.api_request.return_value = {
            "groups": [
                {
                    "id": "face-1",
                    "name": "Assigned Person",
                    "matchedName": "Assigned Person",
                    "type": "face",
                    "imagePath": "/proxy/protect/api/recognition/face/groups/face-1/image",
                    "enhancedPath": None,
                    "detectionsCount": 9,
                    "firstDetectedAt": 1778700000000,
                    "lastDetectedAt": 1778701000000,
                    "isNotificationEnabled": True,
                    "isDegraded": False,
                    "tags": [],
                    "description": None,
                    "createdAt": 1778690000000,
                    "metadata": {},
                }
            ],
            "links": {"prev": None, "next": None},
        }

        result = await RecognitionManager(mock_cm).list_known_faces(page=2, page_size=50)

        assert result["count"] == 1
        assert result["links"] == {}
        face = result["faces"][0]
        assert face["id"] == "face-1"
        assert face["matched_name"] == "Assigned Person"
        assert face["detections_count"] == 9
        mock_cm.client.api_request.assert_awaited_once_with(
            "recognition/face/groups",
            method="get",
            params={
                "labels": "groupType:known,groupType:interest",
                "minConfidence": 30,
                "orderBy": "name",
                "orderDirection": "asc",
                "pageSize": 50,
                "page": 2,
            },
        )

    @pytest.mark.asyncio
    async def test_list_known_faces_known_only(self, mock_cm):
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        mock_cm.client.api_request.return_value = {"groups": [], "links": {"prev": None, "next": None}}

        result = await RecognitionManager(mock_cm).list_known_faces(include_interest=False)

        assert result["count"] == 0
        params = mock_cm.client.api_request.await_args.kwargs["params"]
        assert params["labels"] == "groupType:known"

    @pytest.mark.asyncio
    async def test_list_known_faces_validates_bounds(self, mock_cm):
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        mgr = RecognitionManager(mock_cm)

        with pytest.raises(ValueError, match="page_size"):
            await mgr.list_known_faces(page_size=0)
        with pytest.raises(ValueError, match="min_confidence"):
            await mgr.list_known_faces(min_confidence=101)
        with pytest.raises(ValueError, match="order_direction"):
            await mgr.list_known_faces(order_direction="sideways")  # type: ignore[arg-type]


@pytest.fixture
def mock_recognition_manager():
    mgr = MagicMock()
    with patch("unifi_protect_mcp.tools.recognition.recognition_manager", mgr):
        yield mgr


class TestProtectListKnownFacesTool:
    @pytest.mark.asyncio
    async def test_success(self, mock_recognition_manager):
        from unifi_protect_mcp.tools.recognition import protect_list_known_faces

        mock_recognition_manager.list_known_faces = AsyncMock(
            return_value={
                "faces": [{"id": "face-1", "name": "Assigned Person", "matched_name": "Assigned Person"}],
                "count": 1,
                "links": {},
            }
        )

        result = await protect_list_known_faces(page_size=25, min_confidence=40)

        assert result["success"] is True
        assert result["data"]["count"] == 1
        assert result["data"]["faces"][0]["id"] == "face-1"
        mock_recognition_manager.list_known_faces.assert_awaited_once_with(
            page=None,
            page_size=25,
            min_confidence=40,
            include_interest=True,
            order_by="name",
            order_direction="asc",
        )

    @pytest.mark.asyncio
    async def test_empty(self, mock_recognition_manager):
        from unifi_protect_mcp.tools.recognition import protect_list_known_faces

        mock_recognition_manager.list_known_faces = AsyncMock(return_value={"faces": [], "count": 0, "links": {}})

        result = await protect_list_known_faces()

        assert result["success"] is True
        assert result["data"]["count"] == 0

    @pytest.mark.asyncio
    async def test_error(self, mock_recognition_manager):
        from unifi_protect_mcp.tools.recognition import protect_list_known_faces

        mock_recognition_manager.list_known_faces = AsyncMock(side_effect=RuntimeError("connection lost"))

        result = await protect_list_known_faces()

        assert result["success"] is False
        assert "Failed to list known faces" in result["error"]
        assert "connection lost" in result["error"]
