"""InnerSpace server category mappings and tool module map.

Maps each tool's ``permission_category`` to the config key (and module name)
that ``enabled_categories`` and the ``UNIFI_POLICY_INNERSPACE_<CATEGORY>_<ACTION>``
gates use. ``TOOL_MODULE_MAP`` drives lazy loading.
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
INNERSPACE_CATEGORY_MAP = {
    "status": "status",
    "project": "project",
    "floor_plans": "floor_plans",
    "devices": "devices",
    "walls": "walls",
    "wall_types": "wall_types",
    "attenuation": "attenuation",
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

# The read-only tools lazy mode lists directly: its one indirect route,
# innerspace_execute, is not read-only, so a client that permits only
# read-only tools would otherwise reach none of them. Named one by one so a
# tool added later is listed directly only by choice, and only when read-only.
LAZY_DIRECT_TOOLS: tuple[str, ...] = (
    "innerspace_get_plan_asset",
    "innerspace_get_project",
    "innerspace_get_status",
    "innerspace_list_access_points",
    "innerspace_list_floor_plans",
    "innerspace_list_inventory",
    "innerspace_list_placed_devices",
    "innerspace_list_switches",
    "innerspace_list_walls",
)


@cache
def policy_gates() -> frozenset[tuple[str, str]]:
    """(permission_category, permission_action) pairs the manifest's tools gate on."""
    return policy_gates_from_manifest(_manifest_path())


def setup_lazy_loading(server, tool_decorator: Callable) -> LazyToolLoader:
    """Setup lazy tool loading, passing this app's TOOL_MODULE_MAP."""
    return _shared_setup_lazy_loading(server, tool_decorator, TOOL_MODULE_MAP)
