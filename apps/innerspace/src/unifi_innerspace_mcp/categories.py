"""InnerSpace server category mappings and tool module map.

Maps each tool's ``permission_category`` to the config key (and module name)
that ``enabled_categories`` uses. ``TOOL_MODULE_MAP`` drives lazy loading.
"""

from pathlib import Path
from typing import Callable, Dict

from unifi_mcp_shared.lazy_tools import (
    LazyToolLoader,
    build_tool_module_map,
)
from unifi_mcp_shared.lazy_tools import (
    setup_lazy_loading as _shared_setup_lazy_loading,
)

# Mapping from tool category shorthand to config key
INNERSPACE_CATEGORY_MAP = {
    "status": "status",
    "project": "project",
    "floor_plans": "floor_plans",
    "devices": "devices",
}

_MANIFEST_PATH = Path(__file__).parent / "tools_manifest.json"
_MANIFEST_FALLBACK = Path("apps/innerspace/src/unifi_innerspace_mcp/tools_manifest.json")


def _manifest_path() -> Path:
    return _MANIFEST_PATH if _MANIFEST_PATH.exists() else _MANIFEST_FALLBACK


def _build_tool_module_map() -> Dict[str, str]:
    """Build tool-to-module mapping for the InnerSpace app."""
    return build_tool_module_map(
        "unifi_innerspace_mcp.tools", manifest_path=str(_manifest_path()), tool_prefix="innerspace_"
    )


TOOL_MODULE_MAP: Dict[str, str] = _build_tool_module_map()

# Every tool is read-only. Lazy mode lists them all directly: its one indirect
# route, innerspace_execute, is not read-only, so a client that permits only
# read-only tools would otherwise reach none of them.
LAZY_DIRECT_TOOLS: tuple[str, ...] = tuple(sorted(TOOL_MODULE_MAP))


def setup_lazy_loading(server, tool_decorator: Callable) -> LazyToolLoader:
    """Setup lazy tool loading, passing this app's TOOL_MODULE_MAP."""
    return _shared_setup_lazy_loading(server, tool_decorator, TOOL_MODULE_MAP)
