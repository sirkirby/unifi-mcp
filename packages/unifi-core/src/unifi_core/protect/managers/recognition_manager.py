"""Recognition management for UniFi Protect.

This wraps the private recognition endpoints used by the Protect UI. The
first supported slice is read-only Known Faces / assigned face groups.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.managers.connection_manager import ProtectConnectionManager
from unifi_core.protect.models.recognition import from_controller, links_from_controller, to_controller_update

logger = logging.getLogger(__name__)

_VALID_ORDER_BY = {"name", "createdAt", "firstDetectedAt", "lastDetectedAt", "detectionsCount"}
_VALID_ORDER_DIRECTION = {"asc", "desc"}
_VALID_GROUP_TYPES = {"known", "interest", "unknown"}


def _build_group_labels(group_types: list[str] | None, include_interest: bool) -> str:
    """Build Protect recognition group labels, preserving old defaults."""
    if group_types is None:
        selected = ["known", "interest"] if include_interest else ["known"]
    else:
        selected = []
        for raw in group_types:
            group_type = str(raw).strip().lower()
            if not group_type:
                continue
            if group_type not in _VALID_GROUP_TYPES:
                raise ValueError(f"group_types must contain only {sorted(_VALID_GROUP_TYPES)}")
            if group_type not in selected:
                selected.append(group_type)
        if not selected:
            raise ValueError("group_types must include at least one supported group type")

    return ",".join(f"groupType:{group_type}" for group_type in selected)


class RecognitionManager:
    """Read and manage UniFi Protect recognition group data."""

    def __init__(self, connection_manager: ProtectConnectionManager) -> None:
        self._cm = connection_manager

    async def list_known_faces(
        self,
        *,
        page: int | None = None,
        page_size: int = 100,
        min_confidence: int = 30,
        include_interest: bool = True,
        group_types: list[str] | None = None,
        order_by: str = "name",
        order_direction: Literal["asc", "desc"] = "asc",
    ) -> Dict[str, Any]:
        """Return Protect face recognition groups.

        Uses the same private endpoint shape as the Protect UI's Known Faces
        view by default. Pass ``group_types`` to explicitly discover other
        group types, such as unlabeled/unknown clusters. The response
        intentionally includes image reference paths only; it never fetches
        or embeds image bytes.
        """
        if page is not None and page < 1:
            raise ValueError("page must be greater than or equal to 1")
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")
        if min_confidence < 0 or min_confidence > 100:
            raise ValueError("min_confidence must be between 0 and 100")
        if order_by not in _VALID_ORDER_BY:
            raise ValueError(f"order_by must be one of {sorted(_VALID_ORDER_BY)}")
        if order_direction not in _VALID_ORDER_DIRECTION:
            raise ValueError("order_direction must be 'asc' or 'desc'")

        labels = _build_group_labels(group_types, include_interest)
        params: dict[str, Any] = {
            "labels": labels,
            "minConfidence": min_confidence,
            "orderBy": order_by,
            "orderDirection": order_direction,
            "pageSize": page_size,
        }
        if page is not None:
            params["page"] = page

        data = await self._cm.client.api_request("recognition/face/groups", method="get", params=params)
        if not isinstance(data, dict):
            logger.warning("Unexpected recognition/face/groups shape: %r", type(data))
            data = {}

        groups = data.get("groups")
        if not isinstance(groups, list):
            groups = []

        faces = [from_controller(group).model_dump(exclude_none=True) for group in groups if isinstance(group, dict)]
        links = links_from_controller(data.get("links")).model_dump(exclude_none=True)

        return {
            "faces": faces,
            "count": len(faces),
            "links": links,
        }

    async def get_known_face(self, face_id: str) -> Dict[str, Any]:
        """Return one Protect face recognition group by id."""
        raw = await self._get_known_face_raw(face_id)
        return from_controller(raw).model_dump(exclude_none=True)

    async def update_known_face(self, face_id: str, fields: dict[str, Any]) -> Dict[str, Any]:
        """Return current and proposed Known Face metadata for preview."""
        to_controller_update(fields)
        current = await self.get_known_face(face_id)
        return {
            "face_id": face_id,
            "face_name": _display_name(current),
            "current_state": {key: current.get(key) for key in fields},
            "proposed_changes": dict(fields),
        }

    async def apply_update_known_face(self, face_id: str, fields: dict[str, Any]) -> Dict[str, Any]:
        """Apply a partial Known Face metadata update."""
        await self._get_known_face_raw(face_id)
        payload = to_controller_update(fields)
        updated = await self._cm.client.api_request(
            f"recognition/face/groups/{face_id}",
            method="patch",
            json=payload,
        )
        if not isinstance(updated, dict):
            updated = {}

        face = from_controller(updated).model_dump(exclude_none=True)
        return {
            "face_id": face_id,
            "updated_fields": list(fields.keys()),
            "face": face,
        }

    async def merge_known_faces(self, source_face_id: str, target_face_id: str) -> Dict[str, Any]:
        """Return source and target group metadata for a merge preview."""
        if source_face_id == target_face_id:
            raise ValueError("source_face_id and target_face_id must be different")

        source = await self.get_known_face(source_face_id)
        target = await self.get_known_face(target_face_id)
        return {
            "source": _merge_summary(source),
            "target": _merge_summary(target),
            "warnings": [
                "Source face detections and identity cluster will be folded into the target group.",
                "This operation may not be trivially reversible through MCP.",
            ],
        }

    async def apply_merge_known_faces(self, source_face_id: str, target_face_id: str) -> Dict[str, Any]:
        """Merge one Protect face group into another."""
        preview = await self.merge_known_faces(source_face_id, target_face_id)
        await self._cm.client.api_request(
            "recognition/v2/merge-group",
            method="post",
            json={"fromGroupIds": [source_face_id], "toGroupId": target_face_id},
        )
        return {
            "source_face_id": source_face_id,
            "target_face_id": target_face_id,
            "merged": True,
            "source": preview["source"],
            "target": preview["target"],
        }

    async def delete_known_face(self, face_id: str) -> Dict[str, Any]:
        """Return group metadata for a destructive delete preview."""
        face = await self.get_known_face(face_id)
        return {
            "face": _merge_summary(face),
            "warnings": [
                "This removes the selected face group from Protect.",
                "Deleted recognition groups may not be recoverable through MCP.",
            ],
        }

    async def apply_delete_known_face(self, face_id: str) -> Dict[str, Any]:
        """Delete a Protect face group after confirmation."""
        preview = await self.delete_known_face(face_id)
        await self._cm.client.api_request(
            f"recognition/face/groups/{face_id}",
            method="delete",
        )
        return {
            "face_id": face_id,
            "deleted": True,
            "face": preview["face"],
        }

    async def _get_known_face_raw(self, face_id: str) -> dict[str, Any]:
        if not face_id:
            raise ValueError("face_id is required")

        data = await self._cm.client.api_request(
            "recognition/face/groups",
            method="get",
            params={
                "ids": face_id,
                "minConfidence": 30,
                "orderBy": "name",
                "orderDirection": "asc",
                "pageSize": 1,
            },
        )
        if not isinstance(data, dict):
            data = {}

        groups = data.get("groups")
        if not isinstance(groups, list):
            groups = []

        for group in groups:
            if isinstance(group, dict) and group.get("id") == face_id:
                return group
        raise UniFiNotFoundError("known face", face_id)


def _display_name(face: dict[str, Any]) -> str | None:
    value = face.get("name") or face.get("matched_name")
    return str(value) if value is not None else None


def _merge_summary(face: dict[str, Any]) -> dict[str, Any]:
    return {
        key: face.get(key)
        for key in (
            "id",
            "name",
            "matched_name",
            "type",
            "detections_count",
            "first_detected_at",
            "last_detected_at",
            "is_notification_enabled",
            "description",
        )
        if key in face
    }
