"""Access server category mappings and tool module map.

Maps tool category shorthands to their config key names used in
the policy gate system. This mapping is injected into the
PolicyGateChecker at startup.

Also provides:
- ``TOOL_MODULE_MAP`` for lazy/on-demand tool loading
"""

from functools import cache
from pathlib import Path
from typing import Callable, Dict

from unifi_mcp_shared.lazy_tools import (
    LazyToolLoader,
    build_tool_module_map,
)
from unifi_mcp_shared.lazy_tools import (
    setup_lazy_loading as _shared_setup_lazy_loading,
)
from unifi_mcp_shared.tool_index import policy_gates_from_manifest

# ---------------------------------------------------------------------------
# Permission category mapping
# ---------------------------------------------------------------------------

# Mapping from tool category shorthand to config key
ACCESS_CATEGORY_MAP = {
    "door": "doors",
    "policy": "policies",
    "schedule": "policies",
    "credential": "credentials",
    "visitor": "visitors",
    "event": "events",
    "device": "devices",
    "system": "system",
    "user": "system",
}


# ---------------------------------------------------------------------------
# Tool module map (lazy loading)
# ---------------------------------------------------------------------------

# Access-specific manifest path
_MANIFEST_PATH = Path(__file__).parent / "tools_manifest.json"
_MANIFEST_FALLBACK = Path("apps/access/src/unifi_access_mcp/tools_manifest.json")


def _manifest_path() -> Path:
    return _MANIFEST_PATH if _MANIFEST_PATH.exists() else _MANIFEST_FALLBACK


def _build_tool_module_map() -> Dict[str, str]:
    """Build tool-to-module mapping for the access app."""
    manifest = _manifest_path()
    return build_tool_module_map("unifi_access_mcp.tools", manifest_path=str(manifest), tool_prefix="access_")


# Build the tool map at module load time
TOOL_MODULE_MAP: Dict[str, str] = _build_tool_module_map()


@cache
def policy_gates() -> frozenset[tuple[str, str]]:
    """(permission_category, permission_action) pairs the manifest's tools gate on."""
    return policy_gates_from_manifest(_manifest_path())


def setup_lazy_loading(server, tool_decorator: Callable) -> LazyToolLoader:
    """Setup lazy tool loading for the access app.

    Wraps the shared setup_lazy_loading, automatically passing TOOL_MODULE_MAP.

    Args:
        server: FastMCP server instance
        tool_decorator: The decorator function to register tools

    Returns:
        LazyToolLoader instance
    """
    return _shared_setup_lazy_loading(server, tool_decorator, TOOL_MODULE_MAP)
