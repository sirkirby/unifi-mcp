"""MCP-specific helpers for tool manifest generation."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_tool_annotations(server: Any) -> dict[str, dict[str, Any]]:
    """Extract explicitly declared ToolAnnotations using their MCP wire names."""
    annotations_map: dict[str, dict[str, Any]] = {}

    try:
        tool_manager = getattr(server, "_tool_manager", None)
        if tool_manager is None:
            logger.warning("   server._tool_manager not found; skipping annotations")
            return annotations_map

        internal_tools = getattr(tool_manager, "_tools", None)
        if internal_tools is None:
            logger.warning("   server._tool_manager._tools not found; skipping annotations")
            return annotations_map

        for tool_name, tool_obj in internal_tools.items():
            tool_annotations = getattr(tool_obj, "annotations", None)
            if tool_annotations is None:
                continue

            if hasattr(tool_annotations, "model_dump"):
                annotation_data = tool_annotations.model_dump(
                    by_alias=True,
                    exclude_none=True,
                    exclude_unset=True,
                )
            else:
                annotation_data = {
                    field_name: value
                    for field_name in (
                        "title",
                        "readOnlyHint",
                        "destructiveHint",
                        "idempotentHint",
                        "openWorldHint",
                    )
                    if (value := getattr(tool_annotations, field_name, None)) is not None
                }

            if annotation_data:
                annotations_map[tool_name] = annotation_data
    except Exception as exc:
        logger.warning("   Failed to extract tool annotations: %s", exc)

    return annotations_map
