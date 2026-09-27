"""Tool index and registry — re-exported from shared package."""

from pathlib import Path

from unifi_mcp_shared.tool_index import (
    TOOL_REGISTRY,
    ToolMetadata,
    register_tool,
)
from unifi_mcp_shared.tool_index import (
    get_tool_index as _get_tool_index,
)


def get_tool_index(**kwargs):
    """Get the tool index, using network server's registration mode and manifest."""
    try:
        from unifi_network_mcp.bootstrap import UNIFI_TOOL_REGISTRATION_MODE

        registration_mode = UNIFI_TOOL_REGISTRATION_MODE
    except ImportError:
        registration_mode = "lazy"

    manifest_path = Path(__file__).parent / "tools_manifest.json"
    return _get_tool_index(registration_mode=registration_mode, manifest_path=manifest_path, **kwargs)


async def tool_index_handler(args=None):
    """Handler for the unifi_tool_index tool."""
    args = args or {}
    return get_tool_index(
        name=args.get("name"),
        category=args.get("category"),
        search=args.get("search"),
        include_schemas=bool(args.get("include_schemas", False)),
    )


__all__ = ["TOOL_REGISTRY", "ToolMetadata", "get_tool_index", "register_tool", "tool_index_handler"]
