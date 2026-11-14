"""Site Manager server category mappings and tool module map."""

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
SITEMANAGER_CATEGORY_MAP = {
    "host": "hosts",
    "site": "sites",
    "device": "devices",
    "isp_metrics": "isp_metrics",
    "sdwan": "sdwan",
}

_MANIFEST_PATH = Path(__file__).parent / "tools_manifest.json"
_MANIFEST_FALLBACK = Path("apps/sitemanager/src/unifi_sitemanager_mcp/tools_manifest.json")


def _manifest_path() -> Path:
    return _MANIFEST_PATH if _MANIFEST_PATH.exists() else _MANIFEST_FALLBACK


def _build_tool_module_map() -> Dict[str, str]:
    """Build tool-to-module mapping for the Site Manager app."""
    return build_tool_module_map(
        "unifi_sitemanager_mcp.tools", manifest_path=str(_manifest_path()), tool_prefix="sitemanager_"
    )


TOOL_MODULE_MAP: Dict[str, str] = _build_tool_module_map()

# Every tool is read-only. Lazy mode lists them all directly: its one indirect
# route, sitemanager_execute, is not read-only, so a client that permits only
# read-only tools would otherwise reach none of them.
LAZY_DIRECT_TOOLS: tuple[str, ...] = tuple(sorted(TOOL_MODULE_MAP))


def setup_lazy_loading(server, tool_decorator: Callable) -> LazyToolLoader:
    """Setup lazy tool loading, passing this app's TOOL_MODULE_MAP."""
    return _shared_setup_lazy_loading(server, tool_decorator, TOOL_MODULE_MAP)
