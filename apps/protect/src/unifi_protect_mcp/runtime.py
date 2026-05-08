# ruff: noqa: E402
from __future__ import annotations

"""Shared runtime objects for the UniFi-Protect MCP server.

This module is the *single* source of truth for global singletons such as the
FastMCP server instance, loaded configuration, and all manager helpers.

Downstream code (tool modules, tests, etc.) should import these via::

    from unifi_protect_mcp.runtime import server, config, camera_manager

Lazy factories (`get_*`) are provided so unit tests can substitute fakes by
monkey-patching before the first call.

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
from unifi_protect_mcp.bootstrap import load_config, logger

_TOOLS_MANIFEST_PATH = Path(__file__).resolve().parent / "tools_manifest.json"
from unifi_core.protect.managers.alarm_manager import AlarmManager
from unifi_core.protect.managers.camera_manager import CameraManager
from unifi_core.protect.managers.chime_manager import ChimeManager
from unifi_core.protect.managers.connection_manager import ProtectConnectionManager
from unifi_core.protect.managers.event_manager import EventManager
from unifi_core.protect.managers.light_manager import LightManager
from unifi_core.protect.managers.liveview_manager import LiveviewManager
from unifi_core.protect.managers.recording_manager import RecordingManager
from unifi_core.protect.managers.sensor_manager import SensorManager
from unifi_core.protect.managers.system_manager import SystemManager
from unifi_protect_mcp.tool_index import TOOL_REGISTRY

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
        name="unifi-protect-mcp",
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
def get_connection_manager() -> ProtectConnectionManager:
    cfg = _unifi_settings()
    api_key = getattr(cfg, "api_key", None) or os.environ.get("UNIFI_API_KEY")
    return ProtectConnectionManager(
        host=cfg.host,
        username=cfg.username,
        password=cfg.password,
        port=cfg.port,
        site=cfg.site,
        verify_ssl=str(cfg.verify_ssl).lower() in ("true", "1", "yes"),
        api_key=api_key if api_key else None,
    )


@lru_cache
def get_camera_manager() -> CameraManager:
    return CameraManager(get_connection_manager())


@lru_cache
def get_event_manager() -> EventManager:
    cfg = get_config()
    events_cfg: dict = {}
    try:
        events_cfg = dict(cfg.protect.events) if hasattr(cfg, "protect") and hasattr(cfg.protect, "events") else {}
    except Exception:
        pass
    return EventManager(get_connection_manager(), config=events_cfg)


@lru_cache
def get_recording_manager() -> RecordingManager:
    return RecordingManager(get_connection_manager())


@lru_cache
def get_light_manager() -> LightManager:
    return LightManager(get_connection_manager())


@lru_cache
def get_sensor_manager() -> SensorManager:
    return SensorManager(get_connection_manager())


@lru_cache
def get_chime_manager() -> ChimeManager:
    return ChimeManager(get_connection_manager())


@lru_cache
def get_liveview_manager() -> LiveviewManager:
    return LiveviewManager(get_connection_manager())


@lru_cache
def get_system_manager() -> SystemManager:
    return SystemManager(get_connection_manager())


@lru_cache
def get_alarm_manager() -> AlarmManager:
    return AlarmManager(get_connection_manager())


@lru_cache
def get_tool_registry() -> dict[str, Any]:
    """Return the global tool registry for runtime access."""
    return TOOL_REGISTRY


# ---------------------------------------------------------------------------
# Shorthand aliases (import-time singletons) --------------------------------
# ---------------------------------------------------------------------------

# These provide the convenient attribute style while still being created lazily
# the first time the corresponding factory is called.

config = get_config()
auth = get_auth()
server = get_server()
connection_manager = get_connection_manager()
camera_manager = get_camera_manager()
event_manager = get_event_manager()
recording_manager = get_recording_manager()
light_manager = get_light_manager()
sensor_manager = get_sensor_manager()
chime_manager = get_chime_manager()
liveview_manager = get_liveview_manager()
system_manager = get_system_manager()
alarm_manager = get_alarm_manager()
tool_registry = get_tool_registry()

logger.debug("runtime.py: shared singletons initialised")
