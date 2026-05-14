"""Recognition tools for UniFi Protect MCP server."""

import logging
from typing import Annotated, Any, Dict, List, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.protect.models.recognition import from_controller
from unifi_protect_mcp.runtime import recognition_manager, server

logger = logging.getLogger(__name__)


@server.tool(
    name="protect_list_known_faces",
    description=(
        "List UniFi Protect face recognition groups, including assigned Known Faces "
        "by default and unlabeled groups when group_types includes unknown. "
        "Returns metadata and controller image references only; image bytes are not fetched."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="recognition",
)
async def protect_list_known_faces(
    page: Annotated[
        Optional[int],
        Field(description="Optional 1-based Protect recognition page number."),
    ] = None,
    page_size: Annotated[
        int,
        Field(description="Maximum number of face groups to return (default 100).", ge=1, le=1000),
    ] = 100,
    min_confidence: Annotated[
        int,
        Field(description="Minimum recognition confidence filter used by Protect (0-100, default 30).", ge=0, le=100),
    ] = 30,
    include_interest: Annotated[
        bool,
        Field(
            description=(
                "Backward-compatible filter used when group_types is omitted. "
                "When true, include known and interest groups. When false, only known groups."
            )
        ),
    ] = True,
    group_types: Annotated[
        Optional[List[str]],
        Field(
            description=(
                "Optional explicit recognition group types to list. Supported values: known, interest, unknown. "
                "When set, this overrides include_interest."
            )
        ),
    ] = None,
    order_by: Annotated[
        str,
        Field(description="Sort field: name, createdAt, firstDetectedAt, lastDetectedAt, or detectionsCount."),
    ] = "name",
    order_direction: Annotated[
        str,
        Field(description="Sort direction: asc or desc."),
    ] = "asc",
) -> Dict[str, Any]:
    """List assigned Known Faces from the Protect recognition API."""
    logger.info(
        "protect_list_known_faces called (page=%s, page_size=%s, min_confidence=%s)",
        page,
        page_size,
        min_confidence,
    )
    try:
        raw = await recognition_manager.list_known_faces(
            page=page,
            page_size=page_size,
            min_confidence=min_confidence,
            include_interest=include_interest,
            group_types=group_types,
            order_by=order_by,
            order_direction=order_direction,  # type: ignore[arg-type]
        )
        faces = [from_controller(face).model_dump(exclude_none=True) for face in raw.get("faces", [])]
        return {
            "success": True,
            "data": {
                "faces": faces,
                "count": len(faces),
                "links": raw.get("links", {}),
            },
        }
    except Exception as e:
        logger.error("Error listing known faces: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list known faces: {e}"}
