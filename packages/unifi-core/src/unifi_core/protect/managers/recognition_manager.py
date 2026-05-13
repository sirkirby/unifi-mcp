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
        order_by: str = "name",
        order_direction: Literal["asc", "desc"] = "asc",
    ) -> Dict[str, Any]:
        """Return assigned/named face recognition groups.

        Uses the same private endpoint shape as the Protect UI's Known Faces
        view. The response intentionally includes image reference paths only;
        it never fetches or embeds image bytes.
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

        labels = "groupType:known,groupType:interest" if include_interest else "groupType:known"
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
