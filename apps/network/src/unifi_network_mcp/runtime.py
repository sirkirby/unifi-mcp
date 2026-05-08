# ruff: noqa: E402
from __future__ import annotations

"""Shared runtime objects for the UniFi‑Network MCP server.

This module is the *single* source of truth for global singletons such as the
FastMCP server instance, loaded configuration, and all manager helpers.

Downstream code (tool modules, tests, etc.) should import these via::

    from unifi_network_mcp.runtime import server, config, device_manager

Lazy factories (`get_*`) are provided so unit tests can substitute fakes by
monkey‑patching before the first call.

IMPORTANT: The server's `tool` decorator is wrapped here (not in main.py) to
ensure that tool modules can be imported directly (for testing, etc.) without
errors from unrecognized decorator kwargs like `permission_category`.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from unifi_core.auth import UniFiAuth
from unifi_mcp_shared.strict_dispatch import StrictKwargFastMCP
from unifi_network_mcp.bootstrap import load_config, logger

_TOOLS_MANIFEST_PATH = Path(__file__).resolve().parent / "tools_manifest.json"
from unifi_core.network.managers.acl_manager import AclManager
from unifi_core.network.managers.client_group_manager import ClientGroupManager
from unifi_core.network.managers.client_manager import ClientManager
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.content_filter_manager import ContentFilterManager
from unifi_core.network.managers.device_manager import DeviceManager
from unifi_core.network.managers.dns_manager import DnsManager
from unifi_core.network.managers.dpi_manager import DpiManager
from unifi_core.network.managers.event_manager import EventManager
from unifi_core.network.managers.firewall_manager import FirewallManager
from unifi_core.network.managers.hotspot_manager import HotspotManager
from unifi_core.network.managers.network_manager import NetworkManager
from unifi_core.network.managers.oon_manager import OonManager
from unifi_core.network.managers.qos_manager import QosManager
from unifi_core.network.managers.routing_manager import RoutingManager
from unifi_core.network.managers.stats_manager import StatsManager
from unifi_core.network.managers.switch_manager import SwitchManager
from unifi_core.network.managers.system_manager import SystemManager
from unifi_core.network.managers.traffic_route_manager import TrafficRouteManager
from unifi_core.network.managers.usergroup_manager import UsergroupManager
from unifi_core.network.managers.vpn_manager import VpnManager
from unifi_network_mcp.tool_index import TOOL_REGISTRY

# ---------------------------------------------------------------------------
# Core singletons
# ---------------------------------------------------------------------------


@lru_cache
def get_config():
    """Load and cache configuration."""
    return load_config()


@lru_cache
def get_auth() -> UniFiAuth:
    """Create and cache the dual-auth instance."""
    settings = get_config().unifi
    api_key = getattr(settings, "api_key", None) or os.environ.get("UNIFI_API_KEY")
    return UniFiAuth(api_key=api_key if api_key else None)


def _create_permissioned_tool_wrapper(original_tool_decorator):
    """Wrap the FastMCP tool decorator to handle permission kwargs.

    This wrapper strips `permission_category` and `permission_action` kwargs
    before passing to the original FastMCP decorator. This allows tool modules
    to be imported directly (for testing, etc.) without errors.

    The actual permission checking is done in main.py's permissioned_tool,
    which replaces this wrapper at startup. This wrapper just ensures imports
    don't fail when tools have permission kwargs.
    """

    def wrapper(*args, **kwargs):
        # Strip permission-related kwargs that FastMCP doesn't understand
        kwargs.pop("permission_category", None)
        kwargs.pop("permission_action", None)
        kwargs.pop("auth", None)
        return original_tool_decorator(*args, **kwargs)

    return wrapper


@lru_cache
def get_server() -> FastMCP:
    """Create the FastMCP server instance exactly once."""
    # Parse allowed hosts from environment variable for reverse proxy support
    # Default to localhost only for backwards compatibility
    allowed_hosts_str = os.getenv("UNIFI_MCP_ALLOWED_HOSTS", "localhost,127.0.0.1")
    allowed_hosts = [h.strip() for h in allowed_hosts_str.split(",") if h.strip()]

    # Allow disabling DNS rebinding protection entirely (default: enabled)
    # Set to "false" for Kubernetes/proxy deployments where allowed_hosts is insufficient
    enable_dns_rebinding = os.getenv("UNIFI_MCP_ENABLE_DNS_REBINDING_PROTECTION", "true").lower() == "true"

    # Configure transport security settings
    transport_security = TransportSecuritySettings(
        allowed_hosts=allowed_hosts,
        enable_dns_rebinding_protection=enable_dns_rebinding,
    )

    logger.debug(
        "Configuring FastMCP with allowed_hosts: %s, dns_rebinding_protection: %s", allowed_hosts, enable_dns_rebinding
    )

    server = StrictKwargFastMCP(
        name="unifi-network-mcp",
        debug=True,
        transport_security=transport_security,
        tools_manifest_path=_TOOLS_MANIFEST_PATH,
    )

    # Wrap the tool decorator to handle permission kwargs gracefully.
    # This ensures tool modules can be imported directly without errors.
    # main.py will replace this with the full permissioned_tool implementation.
    from unifi_mcp_shared.protocol import create_mcp_tool_adapter

    # Wrap Layer 1 (raw FastMCP decorator) with protocol adapter.
    # server._original_tool must be set to the adapter (not raw server.tool),
    # because setup_permissioned_tool reads server._original_tool (line 47 of
    # permissioned_tool.py) and uses it as the bottom of the decorator chain.
    # This ensures Layer 3 delegates to the protocol adapter.
    server._original_tool = create_mcp_tool_adapter(server.tool)
    server.tool = _create_permissioned_tool_wrapper(server._original_tool)

    return server


# ---------------------------------------------------------------------------
# Manager factories ---------------------------------------------------------
# ---------------------------------------------------------------------------


def _unifi_settings() -> Any:
    cfg = get_config().unifi
    return cfg


@lru_cache
def get_connection_manager() -> ConnectionManager:
    cfg = _unifi_settings()
    return ConnectionManager(
        host=cfg.host,
        username=cfg.username,
        password=cfg.password,
        port=cfg.port,
        site=cfg.site,
        verify_ssl=str(cfg.verify_ssl).lower() in ("true", "1", "yes"),
    )


@lru_cache
def get_acl_manager() -> AclManager:
    return AclManager(get_connection_manager())


@lru_cache
def get_client_group_manager() -> ClientGroupManager:
    return ClientGroupManager(get_connection_manager())


@lru_cache
def get_client_manager() -> ClientManager:
    return ClientManager(get_connection_manager())


@lru_cache
def get_content_filter_manager() -> ContentFilterManager:
    return ContentFilterManager(get_connection_manager())


@lru_cache
def get_dns_manager() -> DnsManager:
    return DnsManager(get_connection_manager())


@lru_cache
def get_dpi_manager() -> DpiManager:
    return DpiManager(get_connection_manager(), get_auth())


@lru_cache
def get_device_manager() -> DeviceManager:
    return DeviceManager(get_connection_manager())


@lru_cache
def get_stats_manager() -> StatsManager:
    return StatsManager(get_connection_manager(), get_client_manager())


@lru_cache
def get_qos_manager() -> QosManager:
    return QosManager(get_connection_manager())


@lru_cache
def get_vpn_manager() -> VpnManager:
    return VpnManager(get_connection_manager())


@lru_cache
def get_network_manager() -> NetworkManager:
    return NetworkManager(get_connection_manager())


@lru_cache
def get_oon_manager() -> OonManager:
    return OonManager(get_connection_manager())


@lru_cache
def get_switch_manager() -> SwitchManager:
    return SwitchManager(get_connection_manager())


@lru_cache
def get_system_manager() -> SystemManager:
    return SystemManager(get_connection_manager())


@lru_cache
def get_firewall_manager() -> FirewallManager:
    return FirewallManager(get_connection_manager())


@lru_cache
def get_event_manager() -> EventManager:
    return EventManager(get_connection_manager())


@lru_cache
def get_hotspot_manager() -> HotspotManager:
    return HotspotManager(get_connection_manager())


@lru_cache
def get_usergroup_manager() -> UsergroupManager:
    return UsergroupManager(get_connection_manager())


@lru_cache
def get_routing_manager() -> RoutingManager:
    return RoutingManager(get_connection_manager())


@lru_cache
def get_traffic_route_manager() -> TrafficRouteManager:
    return TrafficRouteManager(get_connection_manager())


@lru_cache
def get_tool_registry() -> dict[str, Any]:
    """Return the global tool registry for runtime access."""
    return TOOL_REGISTRY


# ---------------------------------------------------------------------------
# Shorthand aliases (import‑time singletons) --------------------------------
# ---------------------------------------------------------------------------

# These provide the convenient attribute style while still being created lazily
# the first time the corresponding factory is called.

config = get_config()
auth = get_auth()
server = get_server()
connection_manager = get_connection_manager()
acl_manager = get_acl_manager()
client_group_manager = get_client_group_manager()
client_manager = get_client_manager()
content_filter_manager = get_content_filter_manager()
dns_manager = get_dns_manager()
dpi_manager = get_dpi_manager()
device_manager = get_device_manager()
stats_manager = get_stats_manager()
switch_manager = get_switch_manager()
qos_manager = get_qos_manager()
vpn_manager = get_vpn_manager()
network_manager = get_network_manager()
oon_manager = get_oon_manager()
system_manager = get_system_manager()
firewall_manager = get_firewall_manager()
event_manager = get_event_manager()
hotspot_manager = get_hotspot_manager()
usergroup_manager = get_usergroup_manager()
routing_manager = get_routing_manager()
traffic_route_manager = get_traffic_route_manager()
tool_registry = get_tool_registry()

logger.debug("runtime.py: shared singletons initialised")
