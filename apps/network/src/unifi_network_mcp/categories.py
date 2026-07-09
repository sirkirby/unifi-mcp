"""Network server category mappings and tool module map.

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
NETWORK_CATEGORY_MAP = {
    "firewall": "firewall_policies",
    "qos": "qos_rules",
    "vpn_client": "vpn_clients",
    "vpn_server": "vpn_servers",
    "vpn": "vpn",
    "network": "networks",
    "wlan": "wlans",
    "device": "devices",
    "client": "clients",
    "guest": "guests",
    "traffic_route": "traffic_routes",
    "port_forward": "port_forwards",
    "event": "events",
    "voucher": "vouchers",
    "usergroup": "usergroups",
    "route": "routes",
    "snmp": "snmp",
    "acl": "acl_rules",
    "client_group": "client_groups",
    "content_filter": "content_filters",
    "oon_policy": "oon_policies",
    "dpi": "dpi",
    "switch": "switch",
    "system": "system",
    "dns": "dns",
    "dynamic_dns": "dynamic_dns",
    "gateway_settings": "gateway_settings",
}

# Backward-compatible alias
CATEGORY_MAP = NETWORK_CATEGORY_MAP


# ---------------------------------------------------------------------------
# Tool module map (lazy loading)
# ---------------------------------------------------------------------------

# Network-specific manifest path
_MANIFEST_PATH = Path(__file__).parent / "tools_manifest.json"
_MANIFEST_FALLBACK = Path("apps/network/src/unifi_network_mcp/tools_manifest.json")


def _build_tool_module_map() -> Dict[str, str]:
    """Build tool-to-module mapping for the network app."""
    manifest = _MANIFEST_PATH if _MANIFEST_PATH.exists() else _MANIFEST_FALLBACK
    return build_tool_module_map("unifi_network_mcp.tools", manifest_path=str(manifest))


# Build the tool map at module load time
TOOL_MODULE_MAP: Dict[str, str] = _build_tool_module_map()


def setup_lazy_loading(server, tool_decorator: Callable) -> LazyToolLoader:
    """Setup lazy tool loading for the network app.

    Wraps the shared setup_lazy_loading, automatically passing TOOL_MODULE_MAP.

    Args:
        server: FastMCP server instance
        tool_decorator: The decorator function to register tools

    Returns:
        LazyToolLoader instance
    """
    return _shared_setup_lazy_loading(server, tool_decorator, TOOL_MODULE_MAP)
