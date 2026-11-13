# ruff: noqa: E402
from __future__ import annotations

"""Shared runtime objects for the UniFi Site Manager MCP server.

The single source of truth for the FastMCP server instance, the loaded
configuration and the managers. Tool modules import these aliases; tests
substitute fakes by monkey-patching them.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from mcp.server.transport_security import TransportSecuritySettings

from unifi_core.exceptions import UniFiError
from unifi_core.redaction import redact_sensitive_fields
from unifi_core.sitemanager.managers.connection_manager import SiteManagerConnectionManager
from unifi_core.sitemanager.managers.inventory_manager import InventoryManager
from unifi_core.sitemanager.managers.isp_metrics_manager import IspMetricsManager
from unifi_core.sitemanager.managers.sdwan_manager import SdwanManager
from unifi_mcp_shared.bootstrap import resolve_env
from unifi_mcp_shared.metadata import PROJECT_WEBSITE_URL, configure_mcp_server_metadata
from unifi_mcp_shared.response_policy import resolve_mcp_content_mode, should_redact_response_sensitive_fields
from unifi_mcp_shared.server import UniFiMCPServer, resolve_allowed_hosts
from unifi_sitemanager_mcp.bootstrap import load_config, logger
from unifi_sitemanager_mcp.tool_index import TOOL_REGISTRY

_TOOLS_MANIFEST_PATH = Path(__file__).resolve().parent / "tools_manifest.json"
_DEFAULT_TIMEOUT_SECONDS = 30.0


@lru_cache
def get_config():
    """Load and cache configuration."""
    return load_config()


@lru_cache
def get_api_key() -> str | None:
    """The Site Manager API key, from its own variable and nowhere else.

    The key covers every console on the account and is sent to Ubiquiti's
    cloud. It is never taken from the config file, ``CONFIG_PATH`` or the
    shared ``UNIFI_API_KEY``, which holds a console's local key.
    """
    return resolve_env("api_key", env_prefix="SITEMANAGER", logger=logger, shared_fallback=False)


@lru_cache
def get_server() -> UniFiMCPServer:
    """Create the FastMCP server instance exactly once."""
    allowed_hosts = resolve_allowed_hosts(
        os.getenv("UNIFI_MCP_ALLOWED_HOSTS"),
        override_hosts=(
            os.getenv("UNIFI_MCP_COMPOSE_ALLOWED_HOSTS_OVERRIDE")
            if os.getenv("UNIFI_MCP_COMPOSE_ALLOWED_HOSTS_OVERRIDE_SET") == "true"
            else None
        ),
        internal_hosts=os.getenv("UNIFI_MCP_INTERNAL_ALLOWED_HOSTS"),
    )
    enable_dns_rebinding = os.getenv("UNIFI_MCP_ENABLE_DNS_REBINDING_PROTECTION", "true").lower() == "true"
    transport_security = TransportSecuritySettings(
        allowed_hosts=allowed_hosts,
        enable_dns_rebinding_protection=enable_dns_rebinding,
    )

    server = UniFiMCPServer(
        name="unifi-sitemanager-mcp",
        debug=False,
        website_url=PROJECT_WEBSITE_URL,
        transport_security=transport_security,
        tools_manifest_path=_TOOLS_MANIFEST_PATH,
        mcp_content_mode=resolve_mcp_content_mode("sitemanager", config=get_config()),
    )
    configure_mcp_server_metadata(server, package_name="unifi-sitemanager-mcp", icon_family="sitemanager")

    # Until main.py installs the full permissioned_tool, a fail-closed stand-in
    # accepts the permission kwargs so tool modules can be imported directly.
    from unifi_mcp_shared.permissioned_tool import create_import_time_tool_decorator
    from unifi_mcp_shared.protocol import create_mcp_tool_adapter

    server._original_tool = create_mcp_tool_adapter(server.tool)
    server.tool = create_import_time_tool_decorator(server._original_tool, logger=logger)

    return server


def _timeout_seconds() -> float:
    try:
        value = float(get_config().sitemanager.timeout_seconds)
    except (AttributeError, TypeError, ValueError):
        return _DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else _DEFAULT_TIMEOUT_SECONDS


@lru_cache
def get_connection_manager() -> SiteManagerConnectionManager:
    return SiteManagerConnectionManager(get_api_key(), timeout_seconds=_timeout_seconds())


@lru_cache
def get_inventory_manager() -> InventoryManager:
    return InventoryManager(get_connection_manager())


@lru_cache
def get_isp_metrics_manager() -> IspMetricsManager:
    return IspMetricsManager(get_connection_manager())


@lru_cache
def get_sdwan_manager() -> SdwanManager:
    return SdwanManager(get_connection_manager())


@lru_cache
def get_tool_registry() -> dict[str, Any]:
    """Return the global tool registry for runtime access."""
    return TOOL_REGISTRY


config = get_config()
server = get_server()
connection_manager = get_connection_manager()
inventory_manager = get_inventory_manager()
isp_metrics_manager = get_isp_metrics_manager()
sdwan_manager = get_sdwan_manager()
tool_registry = get_tool_registry()


def should_redact_sensitive_fields() -> bool:
    """Whether Site Manager MCP responses should redact sensitive fields."""
    return should_redact_response_sensitive_fields("sitemanager", config)


def tool_success(data: dict[str, Any]) -> dict[str, Any]:
    """A successful tool response, redacted according to the response policy."""
    return redact_sensitive_fields({"success": True, "data": data}, redact_sensitive=should_redact_sensitive_fields())


def tool_failure(operation: str, exc: Exception) -> dict[str, Any]:
    """Log a failed tool call and build its error response.

    Site Manager errors are built from fixed text, the HTTP status and the
    upstream trace id; a 400 also carries the upstream reason, with the API
    key removed and its length capped. Their message is returned. Anything
    else may carry request details: only its class is logged and returned.
    """
    logger.error("Failed to %s: %s", operation, type(exc).__name__)
    if isinstance(exc, UniFiError):
        return {"success": False, "error": f"Failed to {operation}: {exc}"}
    return {"success": False, "error": f"Failed to {operation}: unexpected {type(exc).__name__}"}


logger.debug("runtime.py: shared singletons initialised")
