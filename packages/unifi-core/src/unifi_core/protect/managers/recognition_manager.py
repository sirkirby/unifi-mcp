"""Recognition management for UniFi Protect.

This wraps the private recognition endpoints used by the Protect UI. The
first supported slice is read-only Known Faces / assigned face groups.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal

from unifi_core.protect.managers.connection_manager import ProtectConnectionManager
from unifi_core.protect.models.recognition import from_controller, links_from_controller

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
    """Read UniFi Protect recognition group data."""

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
