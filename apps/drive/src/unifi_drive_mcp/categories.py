"""Drive server category mappings and tool module map.

Maps tool category shorthands to their config key names used in the policy
gate system, and provides ``TOOL_MODULE_MAP`` for lazy tool loading.
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

# Mapping from tool category shorthand to config key
DRIVE_CATEGORY_MAP = {
    "system": "system",
    "storage": "storage",
    "shared_drive": "shared_drives",
    "file_service": "file_services",
    "nfs_connection": "nfs_connections",
    "log": "logs",
    "performance": "performance",
}

_MANIFEST_PATH = Path(__file__).parent / "tools_manifest.json"
_MANIFEST_FALLBACK = Path("apps/drive/src/unifi_drive_mcp/tools_manifest.json")


def _manifest_path() -> Path:
    return _MANIFEST_PATH if _MANIFEST_PATH.exists() else _MANIFEST_FALLBACK


def _build_tool_module_map() -> Dict[str, str]:
    """Build tool-to-module mapping for the Drive app."""
    return build_tool_module_map("unifi_drive_mcp.tools", manifest_path=str(_manifest_path()), tool_prefix="drive_")


TOOL_MODULE_MAP: Dict[str, str] = _build_tool_module_map()


@cache
def policy_gates() -> frozenset[tuple[str, str]]:
    """(permission_category, permission_action) pairs the manifest's tools gate on."""
    return policy_gates_from_manifest(_manifest_path())


def setup_lazy_loading(server, tool_decorator: Callable) -> LazyToolLoader:
    """Setup lazy tool loading, passing this app's TOOL_MODULE_MAP."""
    return _shared_setup_lazy_loading(server, tool_decorator, TOOL_MODULE_MAP)
