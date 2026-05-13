"""Protect server category mappings and tool module map.

Maps tool category shorthands to their config key names used in
the policy gate system. This mapping is injected into the
PolicyGateChecker at startup.

Also provides:
- ``TOOL_MODULE_MAP`` for lazy/on-demand tool loading
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

# ---------------------------------------------------------------------------
# Permission category mapping
# ---------------------------------------------------------------------------

# Mapping from tool category shorthand to config key
PROTECT_CATEGORY_MAP = {
    "camera": "cameras",
    "event": "events",
    "recording": "recordings",
    "light": "lights",
    "sensor": "sensors",
    "chime": "chimes",
    "liveview": "liveviews",
    "recognition": "recognition",
    "system": "system",
    "alarm": "alarm",
}

# Backward-compatible alias
CATEGORY_MAP = PROTECT_CATEGORY_MAP


# ---------------------------------------------------------------------------
# Tool module map (lazy loading)
# ---------------------------------------------------------------------------

# Protect-specific manifest path
_MANIFEST_PATH = Path(__file__).parent / "tools_manifest.json"
_MANIFEST_FALLBACK = Path("apps/protect/src/unifi_protect_mcp/tools_manifest.json")


def _build_tool_module_map() -> Dict[str, str]:
    """Build tool-to-module mapping for the protect app."""
    manifest = _MANIFEST_PATH if _MANIFEST_PATH.exists() else _MANIFEST_FALLBACK
    return build_tool_module_map("unifi_protect_mcp.tools", manifest_path=str(manifest), tool_prefix="protect_")


# Build the tool map at module load time
TOOL_MODULE_MAP: Dict[str, str] = _build_tool_module_map()


def setup_lazy_loading(server, tool_decorator: Callable) -> LazyToolLoader:
    """Setup lazy tool loading for the protect app.

    Wraps the shared setup_lazy_loading, automatically passing TOOL_MODULE_MAP.

    Args:
        server: FastMCP server instance
        tool_decorator: The decorator function to register tools

    Returns:
        LazyToolLoader instance
    """
    return _shared_setup_lazy_loading(server, tool_decorator, TOOL_MODULE_MAP)
