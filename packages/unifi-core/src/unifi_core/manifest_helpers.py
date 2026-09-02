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

            # ToolAnnotations is a pydantic BaseModel; serialize only non-None fields
            ann_dict = {}
            for field_name in ("title", "readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
                value = getattr(tool_annotations, field_name, None)
                if value is not None:
                    ann_dict[field_name] = value

            if ann_dict:
                annotations_map[tool_name] = ann_dict

    except Exception as e:
        logger.warning("   Failed to extract tool annotations: %s", e)

    return annotations_map
