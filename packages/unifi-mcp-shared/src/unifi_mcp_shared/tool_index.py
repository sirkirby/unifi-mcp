"""Tool index and registry system for MCP servers.

This module provides a registry to capture metadata about all registered tools,
enabling code-execution mode and programmatic tool discovery.

The registry is populated during tool registration via the permissioned_tool
decorator, and can be queried via the server's tool_index tool.

In lazy mode, tool metadata is read from a static manifest (tools_manifest.json)
generated at build time, allowing full tool discovery without runtime imports.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool metadata structure
# ---------------------------------------------------------------------------


@dataclass
class ToolMetadata:
    """Metadata about a registered MCP tool.

    Attributes:
        name: Tool name (e.g., "unifi_list_clients")
        description: Human-readable description of what the tool does
        input_schema: JSON Schema describing the tool's input parameters
        output_schema: Optional JSON Schema describing the tool's output structure
        auth_method: Auth strategy hint -- "local_only" (default), "api_key_only", or "either"
        annotations: MCP ToolAnnotations (readOnlyHint, destructiveHint, idempotentHint, openWorldHint)
    """

    name: str
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] | None = None
    auth_method: str = "local_only"
    annotations: Dict[str, Any] | None = None  # MCP ToolAnnotations (readOnlyHint, destructiveHint, etc.)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        data = asdict(self)
        return {k: v for k, v in data.items() if v is not None}


# ---------------------------------------------------------------------------
# Global tool registry
# ---------------------------------------------------------------------------

# Global dictionary mapping tool names to their metadata
TOOL_REGISTRY: Dict[str, ToolMetadata] = {}


def register_tool(
    name: str,
    description: str,
    input_schema: Dict[str, Any] | None = None,
    output_schema: Dict[str, Any] | None = None,
    auth_method: str = "local_only",
    annotations: Dict[str, Any] | None = None,
) -> None:
    """Register a tool in the global registry.

    Args:
        name: Tool name
        description: Tool description
        input_schema: JSON Schema for input parameters (defaults to empty object)
        output_schema: Optional JSON Schema for output structure
        auth_method: Auth strategy hint -- "local_only", "api_key_only", or "either"
        annotations: MCP ToolAnnotations (readOnlyHint, destructiveHint, idempotentHint, openWorldHint)
    """
    if input_schema is None:
        input_schema = {"type": "object", "properties": {}}

    metadata = ToolMetadata(
        name=name,
        description=description,
        input_schema=input_schema,
        output_schema=output_schema,
        auth_method=auth_method,
        annotations=annotations,
    )

    TOOL_REGISTRY[name] = metadata
    logger.debug("Registered tool in index: %s", name)


def get_tool_index(
    registration_mode: str = "lazy",
    manifest_path: Path | None = None,
) -> Dict[str, Any]:
    """Get the complete tool index in machine-readable format.

    In lazy loading mode, reads tool metadata from a static manifest file
    (tools_manifest.json) generated at build time.

    Args:
        registration_mode: Current tool registration mode ("lazy", "eager", "meta_only").
        manifest_path: Path to the tools_manifest.json file for lazy mode.

    Returns:
        Dictionary with "tools" key containing list of tool metadata objects.
    """
    if registration_mode == "lazy" and manifest_path is not None:
        if manifest_path.exists():
            try:
                with open(manifest_path) as f:
                    manifest = json.load(f)
                logger.debug("Loaded tool index from manifest: %d tools", manifest.get("count", 0))
                return manifest
            except Exception as e:
                logger.warning("Failed to load tool manifest: %s, falling back to runtime", e)
        else:
            logger.warning(
                "Tool manifest not found at %s. "
                "Run the manifest generation script to generate it.",
                manifest_path,
            )

    # Fallback: return registered tools (for eager/meta_only or if manifest missing)
    tools = [
        {
            "name": meta.name,
            "description": meta.description,
            "schema": {
                "input": meta.input_schema,
                **({"output": meta.output_schema} if meta.output_schema else {}),
            },
            "annotations": meta.annotations,
        }
        for meta in TOOL_REGISTRY.values()
    ]

    return {
        "tools": tools,
        "count": len(tools),
    }


# ---------------------------------------------------------------------------
# MCP tool handler
# ---------------------------------------------------------------------------


async def tool_index_handler(args: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Default handler for the tool_index tool.

    Servers should wrap this or call get_tool_index() directly to pass
    their registration_mode and manifest_path.

    Returns:
        Dictionary containing tool index with all registered tools and their schemas.
    """
    return get_tool_index()
