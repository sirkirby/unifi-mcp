"""Shared helpers for tool manifest generation scripts.

Provides utilities used by all per-app ``generate_tool_manifest.py`` scripts
so the logic lives in one place rather than being duplicated.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_tool_annotations(server: Any) -> dict[str, dict[str, Any]]:
    """Extract ToolAnnotations from FastMCP's internal tool registry.

    FastMCP stores Tool objects (with annotations) in server._tool_manager._tools.
    Each Tool has an optional ``annotations`` field of type ``ToolAnnotations``.

    Args:
        server: The FastMCP server instance.

    Returns:
        Dictionary mapping tool_name -> annotations dict (only non-None values).
    """
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

            # Preserve MCP wire aliases while excluding SDK defaults the tool did not declare.
            if hasattr(tool_annotations, "model_dump"):
                ann_dict = tool_annotations.model_dump(by_alias=True, exclude_none=True, exclude_unset=True)
            else:
                ann_dict = {
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

            if ann_dict:
                annotations_map[tool_name] = ann_dict

    except Exception as e:
        logger.warning("   Failed to extract tool annotations: %s", e)

    return annotations_map
