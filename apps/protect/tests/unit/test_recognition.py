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
    async def test_list_known_faces_unknown_group_type(self, mock_cm):
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        mock_cm.client.api_request.return_value = {
            "groups": [
                {
                    "id": "face-427",
                    "name": None,
                    "matchedName": None,
                    "type": "face",
                    "detectionsCount": 14,
                    "metadata": {},
                }
            ],
            "links": {"prev": None, "next": None},
        }

        result = await RecognitionManager(mock_cm).list_known_faces(group_types=["unknown"])

        face = result["faces"][0]
        assert face["id"] == "face-427"
        assert "name" not in face
        assert "matched_name" not in face
        params = mock_cm.client.api_request.await_args.kwargs["params"]
        assert params["labels"] == "groupType:unknown"

    @pytest.mark.asyncio
    async def test_list_known_faces_mixed_group_types(self, mock_cm):
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        mock_cm.client.api_request.return_value = {"groups": [], "links": {}}

        await RecognitionManager(mock_cm).list_known_faces(group_types=["known", "unknown", "known"])

        params = mock_cm.client.api_request.await_args.kwargs["params"]
        assert params["labels"] == "groupType:known,groupType:unknown"

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
        with pytest.raises(ValueError, match="group_types"):
            await mgr.list_known_faces(group_types=["person"])  # type: ignore[list-item]
        with pytest.raises(ValueError, match="at least one"):
            await mgr.list_known_faces(group_types=[])

    @pytest.mark.asyncio
    async def test_update_known_face_preview_preserves_unmentioned_fields(self, mock_cm):
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        mock_cm.client.api_request.return_value = {
            "groups": [
                {
                    "id": "face-1",
                    "name": "Current",
                    "description": "Keep",
                    "isNotificationEnabled": True,
                    "detectionsCount": 12,
                }
            ]
        }

        result = await RecognitionManager(mock_cm).update_known_face("face-1", {"name": "Updated"})

        assert result["current_state"] == {"name": "Current"}
        assert result["proposed_changes"] == {"name": "Updated"}
        assert "description" not in result["proposed_changes"]

    @pytest.mark.asyncio
    async def test_update_known_face_rejects_unknown_and_read_only_fields(self, mock_cm):
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        mgr = RecognitionManager(mock_cm)

        with pytest.raises(ValueError, match="Read-only"):
            await mgr.update_known_face("face-1", {"id": "other"})
        with pytest.raises(ValueError, match="Unsupported"):
            await mgr.update_known_face("face-1", {"nickname": "nope"})
        with pytest.raises(ValueError, match="at least one"):
            await mgr.update_known_face("face-1", {})

    @pytest.mark.asyncio
    async def test_apply_update_known_face_patches_translated_mutable_fields(self, mock_cm):
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        mock_cm.client.api_request.side_effect = [
            {
                "groups": [
                    {
                        "id": "face-1",
                        "name": "Current",
                        "description": "Keep",
                        "isNotificationEnabled": False,
                    }
                ]
            },
            {
                "id": "face-1",
                "name": "Current",
                "description": "Keep",
                "isNotificationEnabled": True,
            },
        ]

        result = await RecognitionManager(mock_cm).apply_update_known_face(
            "face-1",
            {"is_notification_enabled": True},
        )

        assert result["updated_fields"] == ["is_notification_enabled"]
        mock_cm.client.api_request.assert_any_await(
            "recognition/face/groups/face-1",
            method="patch",
            json={"isNotificationEnabled": True},
        )

    @pytest.mark.asyncio
    async def test_merge_known_faces_preview_fetches_source_and_target(self, mock_cm):
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        mock_cm.client.api_request.side_effect = [
            {"groups": [{"id": "source", "name": "Source", "detectionsCount": 2}]},
            {"groups": [{"id": "target", "name": "Target", "detectionsCount": 9}]},
        ]

        result = await RecognitionManager(mock_cm).merge_known_faces("source", "target")

        assert result["source"]["id"] == "source"
        assert result["target"]["id"] == "target"
        assert result["warnings"]

    @pytest.mark.asyncio
    async def test_merge_known_faces_rejects_same_id(self, mock_cm):
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        with pytest.raises(ValueError, match="must be different"):
            await RecognitionManager(mock_cm).merge_known_faces("face-1", "face-1")

    @pytest.mark.asyncio
    async def test_apply_merge_known_faces_posts_validated_payload(self, mock_cm):
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        mock_cm.client.api_request.side_effect = [
            {"groups": [{"id": "source", "name": "Source"}]},
            {"groups": [{"id": "target", "name": "Target"}]},
            None,
        ]

        result = await RecognitionManager(mock_cm).apply_merge_known_faces("source", "target")

        assert result["merged"] is True
        mock_cm.client.api_request.assert_any_await(
            "recognition/v2/merge-group",
            method="post",
            json={"fromGroupIds": ["source"], "toGroupId": "target"},
        )

    @pytest.mark.asyncio
    async def test_delete_known_face_preview_fetches_group(self, mock_cm):
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        mock_cm.client.api_request.return_value = {"groups": [{"id": "face-1", "name": "Assigned"}]}

        result = await RecognitionManager(mock_cm).delete_known_face("face-1")

        assert result["face"]["id"] == "face-1"
        assert result["warnings"]

    @pytest.mark.asyncio
    async def test_apply_delete_known_face_calls_delete_endpoint(self, mock_cm):
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        mock_cm.client.api_request.side_effect = [
            {"groups": [{"id": "face-1", "name": "Assigned"}]},
            None,
        ]

        result = await RecognitionManager(mock_cm).apply_delete_known_face("face-1")

        assert result["deleted"] is True
        mock_cm.client.api_request.assert_any_await(
            "recognition/face/groups/face-1",
            method="delete",
        )


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
            group_types=None,
            order_by="name",
            order_direction="asc",
        )

    @pytest.mark.asyncio
    async def test_unknown_group_types(self, mock_recognition_manager):
        from unifi_protect_mcp.tools.recognition import protect_list_known_faces

        mock_recognition_manager.list_known_faces = AsyncMock(
            return_value={
                "faces": [{"id": "face-427", "type": "face", "detections_count": 14}],
                "count": 1,
                "links": {},
            }
        )

        result = await protect_list_known_faces(group_types=["unknown"])

        assert result["success"] is True
        assert result["data"]["faces"][0]["id"] == "face-427"
        mock_recognition_manager.list_known_faces.assert_awaited_once_with(
            page=None,
            page_size=100,
            min_confidence=30,
            include_interest=True,
            group_types=["unknown"],
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


class TestProtectKnownFaceMutationTools:
    @pytest.mark.asyncio
    async def test_update_preview(self, mock_recognition_manager):
        from unifi_protect_mcp.tools.recognition import protect_update_known_face

        mock_recognition_manager.update_known_face = AsyncMock(
            return_value={
                "face_id": "face-1",
                "face_name": "Current",
                "current_state": {"name": "Current"},
                "proposed_changes": {"name": "Updated"},
            }
        )

        result = await protect_update_known_face("face-1", {"name": "Updated"})

        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["preview"]["current"] == {"name": "Current"}
        mock_recognition_manager.apply_update_known_face.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_confirm(self, mock_recognition_manager):
        from unifi_protect_mcp.tools.recognition import protect_update_known_face

        mock_recognition_manager.update_known_face = AsyncMock(
            return_value={
                "face_id": "face-1",
                "face_name": "Current",
                "current_state": {"description": None},
                "proposed_changes": {"description": "Doorbell"},
            }
        )
        mock_recognition_manager.apply_update_known_face = AsyncMock(return_value={"face_id": "face-1"})

        result = await protect_update_known_face("face-1", {"description": "Doorbell"}, confirm=True)

        assert result == {"success": True, "data": {"face_id": "face-1"}}
        mock_recognition_manager.apply_update_known_face.assert_awaited_once_with(
            "face-1",
            {"description": "Doorbell"},
        )

    @pytest.mark.asyncio
    async def test_merge_preview(self, mock_recognition_manager):
        from unifi_protect_mcp.tools.recognition import protect_merge_known_faces

        mock_recognition_manager.merge_known_faces = AsyncMock(
            return_value={
                "source": {"id": "source", "name": "Source"},
                "target": {"id": "target", "name": "Target"},
                "warnings": ["hard to reverse"],
            }
        )

        result = await protect_merge_known_faces("source", "target")

        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["warnings"] == ["hard to reverse"]

    @pytest.mark.asyncio
    async def test_merge_confirm(self, mock_recognition_manager):
        from unifi_protect_mcp.tools.recognition import protect_merge_known_faces

        mock_recognition_manager.merge_known_faces = AsyncMock(
            return_value={
                "source": {"id": "source"},
                "target": {"id": "target"},
                "warnings": [],
            }
        )
        mock_recognition_manager.apply_merge_known_faces = AsyncMock(return_value={"merged": True})

        result = await protect_merge_known_faces("source", "target", confirm=True)

        assert result == {"success": True, "data": {"merged": True}}
        mock_recognition_manager.apply_merge_known_faces.assert_awaited_once_with("source", "target")

    @pytest.mark.asyncio
    async def test_delete_preview(self, mock_recognition_manager):
        from unifi_protect_mcp.tools.recognition import protect_delete_known_face

        mock_recognition_manager.delete_known_face = AsyncMock(
            return_value={
                "face": {"id": "face-1", "name": "Assigned"},
                "warnings": ["destructive"],
            }
        )

        result = await protect_delete_known_face("face-1")

        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["warnings"] == ["destructive"]

    @pytest.mark.asyncio
    async def test_delete_confirm(self, mock_recognition_manager):
        from unifi_protect_mcp.tools.recognition import protect_delete_known_face

        mock_recognition_manager.delete_known_face = AsyncMock(return_value={"face": {"id": "face-1"}, "warnings": []})
        mock_recognition_manager.apply_delete_known_face = AsyncMock(return_value={"deleted": True})

        result = await protect_delete_known_face("face-1", confirm=True)

        assert result == {"success": True, "data": {"deleted": True}}
        mock_recognition_manager.apply_delete_known_face.assert_awaited_once_with("face-1")

    @pytest.mark.asyncio
    async def test_merge_error_has_operation_context(self, mock_recognition_manager):
        from unifi_protect_mcp.tools.recognition import protect_merge_known_faces

        mock_recognition_manager.merge_known_faces = AsyncMock(side_effect=RuntimeError("controller rejected"))

        result = await protect_merge_known_faces("source", "target")

        assert result["success"] is False
        assert "Failed to merge known faces" in result["error"]


class TestRecognitionManagerLicensePlates:
    """Tests for the license-plate recognition group manager method.

    Mirrors the Known Faces shape (``recognition/face/groups``); license plates
    live behind ``recognition/vehicle/groups`` with the same ``labels`` /
    ``minConfidence`` / pagination params.
    """

    @pytest.mark.asyncio
    async def test_list_known_license_plates_success(self, mock_cm):
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        mock_cm.client.api_request.return_value = {
            "groups": [
                {
                    "id": "plate-uuid-1",
                    "name": "Example Vehicle",
                    "matchedName": "ABC1234",
                    "type": "vehicle",
                    "imagePath": "/proxy/protect/api/recognition/vehicle/groups/plate-uuid-1/image",
                    "enhancedPath": None,
                    "detectionsCount": 42,
                    "firstDetectedAt": 1778700000000,
                    "lastDetectedAt": 1778701000000,
                    "isNotificationEnabled": False,
                    "isDegraded": False,
                    "tags": [],
                    "description": None,
                    "createdAt": 1778690000000,
                    "metadata": {
                        "color": {"val": "black", "confidence": 80},
                        "vehicleType": {"val": "suv", "confidence": 95},
                    },
                }
            ],
            "links": {"prev": None, "next": None},
        }

        result = await RecognitionManager(mock_cm).list_known_license_plates(page=2, page_size=50)

        assert result["count"] == 1
        assert result["links"] == {}
        plate = result["license_plates"][0]
        assert plate["id"] == "plate-uuid-1"
        assert plate["name"] == "Example Vehicle"
        assert plate["matched_name"] == "ABC1234"
        assert plate["detections_count"] == 42
        mock_cm.client.api_request.assert_awaited_once_with(
            "recognition/vehicle/groups",
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
    async def test_list_known_license_plates_known_only(self, mock_cm):
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        mock_cm.client.api_request.return_value = {"groups": [], "links": {"prev": None, "next": None}}

        result = await RecognitionManager(mock_cm).list_known_license_plates(include_interest=False)

        assert result["count"] == 0
        params = mock_cm.client.api_request.await_args.kwargs["params"]
        assert params["labels"] == "groupType:known"

    @pytest.mark.asyncio
    async def test_list_known_license_plates_unknown_group_type(self, mock_cm):
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        mock_cm.client.api_request.return_value = {"groups": [], "links": {"prev": None, "next": None}}

        result = await RecognitionManager(mock_cm).list_known_license_plates(group_types=["unknown"])

        assert result["count"] == 0
        params = mock_cm.client.api_request.await_args.kwargs["params"]
        assert params["labels"] == "groupType:unknown"

    @pytest.mark.asyncio
    async def test_update_known_license_plate_preview_preserves_unmentioned_fields(self, mock_cm):
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        mock_cm.client.api_request.return_value = {
            "groups": [
                {
                    "id": "plate-1",
                    "name": "Current",
                    "description": "Keep",
                    "isNotificationEnabled": True,
                    "detectionsCount": 4,
                }
            ]
        }

        result = await RecognitionManager(mock_cm).update_known_license_plate("plate-1", {"name": "Updated"})

        assert result["current_state"] == {"name": "Current"}
        assert result["proposed_changes"] == {"name": "Updated"}

    @pytest.mark.asyncio
    async def test_update_known_license_plate_rejects_unknown_and_read_only_fields(self, mock_cm):
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        mgr = RecognitionManager(mock_cm)
        with pytest.raises(ValueError, match="Read-only"):
            await mgr.update_known_license_plate("plate-1", {"matched_name": "PLATE"})
        with pytest.raises(ValueError, match="Unsupported"):
            await mgr.update_known_license_plate("plate-1", {"nickname": "nope"})
        with pytest.raises(ValueError, match="at least one"):
            await mgr.update_known_license_plate("plate-1", {})

    @pytest.mark.asyncio
    async def test_apply_update_known_license_plate_patches_translated_fields(self, mock_cm):
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        mock_cm.client.api_request.side_effect = [
            {"groups": [{"id": "plate-1", "name": "Current", "isNotificationEnabled": False}]},
            {"id": "plate-1", "name": "Current", "isNotificationEnabled": True},
        ]

        result = await RecognitionManager(mock_cm).apply_update_known_license_plate(
            "plate-1", {"is_notification_enabled": True}
        )

        assert result["updated_fields"] == ["is_notification_enabled"]
        mock_cm.client.api_request.assert_any_await(
            "recognition/vehicle/groups/plate-1",
            method="patch",
            json={"isNotificationEnabled": True},
        )

    @pytest.mark.asyncio
    async def test_delete_known_license_plate_preview_fetches_group(self, mock_cm):
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        mock_cm.client.api_request.return_value = {"groups": [{"id": "plate-1", "name": "Assigned"}]}

        result = await RecognitionManager(mock_cm).delete_known_license_plate("plate-1")

        assert result["license_plate"]["id"] == "plate-1"
        assert result["warnings"]

    @pytest.mark.asyncio
    async def test_apply_delete_known_license_plate_uses_raw_delete(self, mock_cm):
        """Vehicle DELETE returns an empty body; must use api_request_raw to avoid a
        spurious 'Could not decode JSON' error after a successful delete."""
        from unifi_core.protect.managers.recognition_manager import RecognitionManager

        mock_cm.client.api_request.return_value = {"groups": [{"id": "plate-1", "name": "Assigned"}]}
        mock_cm.client.api_request_raw = AsyncMock(return_value=None)

        result = await RecognitionManager(mock_cm).apply_delete_known_license_plate("plate-1")

        assert result["deleted"] is True
        mock_cm.client.api_request_raw.assert_awaited_once_with(
            "recognition/vehicle/groups/plate-1",
            method="delete",
        )


class TestProtectListKnownLicensePlatesTool:
    """Tool-layer tests for the pass-through wrapping that diverges from the faces tool.

    The plates tool intentionally does NOT re-serialize the manager output (the faces
    tool double-dumps), so the tool's own wrapping (license_plates/count/links + the
    error handler) is exercised here, separately from the manager tests above.
    """

    @pytest.mark.asyncio
    async def test_success(self, mock_recognition_manager):
        from unifi_protect_mcp.tools.recognition import protect_list_known_license_plates

        mock_recognition_manager.list_known_license_plates = AsyncMock(
            return_value={
                "license_plates": [{"id": "plate-uuid-1", "name": "Example Vehicle", "matched_name": "ABC1234"}],
                "count": 1,
                "links": {},
            }
        )

        result = await protect_list_known_license_plates(page_size=25, min_confidence=40)

        assert result["success"] is True
        assert result["data"]["count"] == 1
        assert result["data"]["license_plates"][0]["id"] == "plate-uuid-1"
        mock_recognition_manager.list_known_license_plates.assert_awaited_once_with(
            page=None,
            page_size=25,
            min_confidence=40,
            include_interest=True,
            group_types=None,
            order_by="name",
            order_direction="asc",
        )

    @pytest.mark.asyncio
    async def test_empty(self, mock_recognition_manager):
        from unifi_protect_mcp.tools.recognition import protect_list_known_license_plates

        mock_recognition_manager.list_known_license_plates = AsyncMock(
            return_value={"license_plates": [], "count": 0, "links": {}}
        )

        result = await protect_list_known_license_plates()

        assert result["success"] is True
        assert result["data"]["count"] == 0
        assert result["data"]["license_plates"] == []

    @pytest.mark.asyncio
    async def test_error(self, mock_recognition_manager):
        from unifi_protect_mcp.tools.recognition import protect_list_known_license_plates

        mock_recognition_manager.list_known_license_plates = AsyncMock(side_effect=RuntimeError("connection lost"))

        result = await protect_list_known_license_plates()

        assert result["success"] is False
        assert "Failed to list known license plates" in result["error"]
        assert "connection lost" in result["error"]


class TestProtectKnownLicensePlateMutationTools:
    @pytest.mark.asyncio
    async def test_update_preview(self, mock_recognition_manager):
        from unifi_protect_mcp.tools.recognition import protect_update_known_license_plate

        mock_recognition_manager.update_known_license_plate = AsyncMock(
            return_value={
                "plate_id": "plate-1",
                "plate_name": "Current",
                "current_state": {"name": "Current"},
                "proposed_changes": {"name": "Updated"},
            }
        )

        result = await protect_update_known_license_plate("plate-1", {"name": "Updated"})

        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["preview"]["current"] == {"name": "Current"}
        mock_recognition_manager.apply_update_known_license_plate.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_confirm(self, mock_recognition_manager):
        from unifi_protect_mcp.tools.recognition import protect_update_known_license_plate

        mock_recognition_manager.update_known_license_plate = AsyncMock(
            return_value={
                "plate_id": "plate-1",
                "plate_name": "Current",
                "current_state": {"description": None},
                "proposed_changes": {"description": "Delivery van"},
            }
        )
        mock_recognition_manager.apply_update_known_license_plate = AsyncMock(return_value={"plate_id": "plate-1"})

        result = await protect_update_known_license_plate("plate-1", {"description": "Delivery van"}, confirm=True)

        assert result == {"success": True, "data": {"plate_id": "plate-1"}}
        mock_recognition_manager.apply_update_known_license_plate.assert_awaited_once_with(
            "plate-1", {"description": "Delivery van"}
        )

    @pytest.mark.asyncio
    async def test_delete_preview(self, mock_recognition_manager):
        from unifi_protect_mcp.tools.recognition import protect_delete_known_license_plate

        mock_recognition_manager.delete_known_license_plate = AsyncMock(
            return_value={"license_plate": {"id": "plate-1", "name": "Assigned"}, "warnings": ["destructive"]}
        )

        result = await protect_delete_known_license_plate("plate-1")

        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["warnings"] == ["destructive"]
        mock_recognition_manager.apply_delete_known_license_plate.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_confirm(self, mock_recognition_manager):
        from unifi_protect_mcp.tools.recognition import protect_delete_known_license_plate

        mock_recognition_manager.delete_known_license_plate = AsyncMock(
            return_value={"license_plate": {"id": "plate-1"}, "warnings": []}
        )
        mock_recognition_manager.apply_delete_known_license_plate = AsyncMock(return_value={"deleted": True})

        result = await protect_delete_known_license_plate("plate-1", confirm=True)

        assert result == {"success": True, "data": {"deleted": True}}
        mock_recognition_manager.apply_delete_known_license_plate.assert_awaited_once_with("plate-1")

    @pytest.mark.asyncio
    async def test_update_not_found_returns_error(self, mock_recognition_manager):
        from unifi_core.exceptions import UniFiNotFoundError
        from unifi_protect_mcp.tools.recognition import protect_update_known_license_plate

        mock_recognition_manager.update_known_license_plate = AsyncMock(
            side_effect=UniFiNotFoundError("known license plate", "missing")
        )

        result = await protect_update_known_license_plate("missing", {"name": "X"})

        assert result["success"] is False
        assert "missing" in result["error"]
        mock_recognition_manager.apply_update_known_license_plate.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_not_found_returns_error(self, mock_recognition_manager):
        from unifi_core.exceptions import UniFiNotFoundError
        from unifi_protect_mcp.tools.recognition import protect_delete_known_license_plate

        mock_recognition_manager.delete_known_license_plate = AsyncMock(
            side_effect=UniFiNotFoundError("known license plate", "missing")
        )

        result = await protect_delete_known_license_plate("missing", confirm=True)

        assert result["success"] is False
        assert "missing" in result["error"]
        mock_recognition_manager.apply_delete_known_license_plate.assert_not_called()
