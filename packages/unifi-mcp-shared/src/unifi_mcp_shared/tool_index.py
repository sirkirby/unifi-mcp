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
    permission_category: str | None = None  # Permission category (e.g., "networks", "devices")
    permission_action: str | None = None  # Permission action (e.g., "create", "update", "delete")

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
    permission_category: str | None = None,
    permission_action: str | None = None,
) -> None:
    """Register a tool in the global registry.

    Args:
        name: Tool name
        description: Tool description
        input_schema: JSON Schema for input parameters (defaults to empty object)
        output_schema: Optional JSON Schema for output structure
        auth_method: Auth strategy hint -- "local_only", "api_key_only", or "either"
        annotations: MCP ToolAnnotations (readOnlyHint, destructiveHint, idempotentHint, openWorldHint)
        permission_category: Permission category (e.g., "networks", "devices")
        permission_action: Permission action (e.g., "create", "update", "delete")
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
        permission_category=permission_category,
        permission_action=permission_action,
    )

    TOOL_REGISTRY[name] = metadata
    logger.debug("Registered tool in index: %s", name)


def get_tool_index(
    registration_mode: str = "lazy",
    manifest_path: Path | None = None,
    category: str | None = None,
    search: str | None = None,
    include_schemas: bool = False,
) -> Dict[str, Any]:
    """Get the tool index, optionally filtered to reduce response size.

    By default returns tool names and descriptions without full schemas
    (~38K chars for 166 tools vs ~127K with schemas).

    In lazy loading mode, reads tool metadata from a static manifest file
    (tools_manifest.json) generated at build time.

    Args:
        registration_mode: Current tool registration mode ("lazy", "eager", "meta_only").
        manifest_path: Path to the tools_manifest.json file for lazy mode.
        category: Filter to tools in this category (e.g. "clients", "firewall").
                  Derived from the last segment of the tool's module path.
        search: Case-insensitive substring filter applied to tool name and description.
        include_schemas: If True, include full input/output schemas per tool.

    Returns:
        Dictionary with "tools", "count", and "categories" keys.
    """
    module_map: Dict[str, str] = {}

    if registration_mode == "lazy" and manifest_path is not None:
        if manifest_path.exists():
            try:
                with open(manifest_path) as f:
                    manifest = json.load(f)
                module_map = manifest.get("module_map", {})
                logger.debug("Loaded tool index from manifest: %d tools", manifest.get("count", 0))
                all_tools = manifest.get("tools", [])
            except Exception as e:
                logger.warning("Failed to load tool manifest: %s, falling back to runtime", e)
                all_tools = _tools_from_registry()
        else:
            logger.warning(
                "Tool manifest not found at %s. Run the manifest generation script to generate it.",
                manifest_path,
            )
            all_tools = _tools_from_registry()
    else:
        all_tools = _tools_from_registry()

    # Derive per-tool category from module_map (last segment of module path)
    def _category(tool_name: str) -> str:
        module = module_map.get(tool_name, "")
        return module.split(".")[-1] if module else ""

    # Build full category list before filtering
    all_categories = sorted({_category(t.get("name", "")) for t in all_tools} - {""})

    # Apply category filter
    if category:
        cat_lower = category.lower()
        all_tools = [t for t in all_tools if _category(t.get("name", "")).lower() == cat_lower]

    # Apply search filter (name + description)
    if search:
        search_lower = search.lower()
        all_tools = [
            t
            for t in all_tools
            if search_lower in t.get("name", "").lower() or search_lower in t.get("description", "").lower()
        ]

    # Strip schemas unless explicitly requested
    if not include_schemas:
        tools_out = [{"name": t["name"], "description": t.get("description", "")} for t in all_tools]
    else:
        tools_out = all_tools

    result: Dict[str, Any] = {
        "tools": tools_out,
        "count": len(tools_out),
        "categories": all_categories,
    }
    if category or search:
        result["filtered"] = True
    return result


def _tools_from_registry() -> list:
    """Build tool list from the runtime TOOL_REGISTRY (fallback for non-lazy mode)."""
    return [
        {
            "name": meta.name,
            "description": meta.description,
            "schema": {
                "input": meta.input_schema,
                **({"output": meta.output_schema} if meta.output_schema else {}),
            },
            **({"annotations": meta.annotations} if meta.annotations is not None else {}),
        }
        for meta in TOOL_REGISTRY.values()
    ]


# ---------------------------------------------------------------------------
# MCP tool handler
# ---------------------------------------------------------------------------


async def tool_index_handler(args: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Default handler for the tool_index tool.

    Servers should wrap this or call get_tool_index() directly to pass
    their registration_mode and manifest_path.

    Accepts optional filter args:
        category (str): Filter by tool category (module suffix, e.g. "clients").
        search (str): Case-insensitive substring match on name/description.
        include_schemas (bool): Include full schemas per tool. Defaults to False.

    Returns:
        Dictionary containing matching tools with name, description,
        and (if include_schemas) full schemas.
    """
    args = args or {}
    return get_tool_index(
        category=args.get("category"),
        search=args.get("search"),
        include_schemas=bool(args.get("include_schemas", False)),
    )
