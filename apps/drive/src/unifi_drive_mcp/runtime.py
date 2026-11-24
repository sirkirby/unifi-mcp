# ruff: noqa: E402
from __future__ import annotations

"""Shared runtime objects for the UniFi Drive MCP server.

The single source of truth for the FastMCP server instance, the loaded
configuration and the managers. Tool modules import these aliases; tests
substitute fakes by monkey-patching them.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from mcp.server.transport_security import TransportSecuritySettings

from unifi_core.drive.managers.connection_manager import (
    DriveConnectionManager,
    DriveWriteNotSent,
    DriveWriteOutcomeUnknown,
)
from unifi_core.drive.managers.file_service_manager import FileServiceManager
from unifi_core.drive.managers.shared_drive_manager import SharedDriveManager
from unifi_core.drive.managers.storage_manager import StorageManager
from unifi_core.drive.managers.system_manager import DriveSystemManager
from unifi_core.exceptions import UniFiError
from unifi_core.operation_gate import GateKey, GateSettings, OperationGate, gate_registry
from unifi_core.redaction import redact_sensitive_fields
from unifi_core.tls import server_ssl_setting
from unifi_drive_mcp.bootstrap import load_config, logger
from unifi_drive_mcp.tool_index import TOOL_REGISTRY
from unifi_mcp_shared.bootstrap import resolve_env
from unifi_mcp_shared.metadata import PROJECT_WEBSITE_URL, configure_mcp_server_metadata
from unifi_mcp_shared.response_policy import resolve_mcp_content_mode, should_redact_response_sensitive_fields
from unifi_mcp_shared.server import UniFiMCPServer, resolve_allowed_hosts
from unifi_mcp_shared.tool_gate import gate_settings_from_env

_TOOLS_MANIFEST_PATH = Path(__file__).resolve().parent / "tools_manifest.json"
_DEFAULT_TIMEOUT_SECONDS = 30.0


@lru_cache
def get_config():
    """Load and cache configuration."""
    return load_config()


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
        name="unifi-drive-mcp",
        debug=False,
        website_url=PROJECT_WEBSITE_URL,
        transport_security=transport_security,
        tools_manifest_path=_TOOLS_MANIFEST_PATH,
        mcp_content_mode=resolve_mcp_content_mode("drive", config=get_config()),
    )
    configure_mcp_server_metadata(server, package_name="unifi-drive-mcp", icon_family="drive")

    # Until main.py installs the full permissioned_tool, a fail-closed stand-in
    # accepts the permission kwargs so tool modules can be imported directly.
    from unifi_mcp_shared.permissioned_tool import create_import_time_tool_decorator
    from unifi_mcp_shared.protocol import create_mcp_tool_adapter

    server._original_tool = create_mcp_tool_adapter(server.tool)
    server.tool = create_import_time_tool_decorator(server._original_tool, logger=logger)

    return server


def _timeout_seconds() -> float:
    try:
        value = float(get_config().drive.timeout_seconds)
    except (AttributeError, TypeError, ValueError):
        return _DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else _DEFAULT_TIMEOUT_SECONDS


def _ssl_fingerprint(cfg: Any) -> str | None:
    """A pin from ``UNIFI_DRIVE_SSL_FINGERPRINT``, or from an operator's ``CONFIG_PATH`` file.

    Read here rather than through ``load_config``'s keys, which log their values
    at debug level. ``UNIFI_SSL_FINGERPRINT`` pins the gateway's certificate, so
    it is not used for the NAS.
    """
    value = resolve_env("ssl_fingerprint", env_prefix="DRIVE", logger=logger, shared_fallback=False) or cfg.get(
        "ssl_fingerprint"
    )
    return str(value) if value else None


@lru_cache
def get_connection_manager() -> DriveConnectionManager:
    cfg = get_config().unifi
    verify_ssl = str(cfg.get("verify_ssl", False)).lower() in ("true", "1", "yes")
    fingerprint = _ssl_fingerprint(cfg)
    host = str(cfg.get("host", "") or "")
    if host:
        # Warns once when nothing checks the NAS certificate; exits on a malformed pin.
        server_ssl_setting(logger, verify_ssl, fingerprint, product="Drive", env_prefix="DRIVE")
    try:
        port = int(cfg.get("port", 443))
    except (TypeError, ValueError):
        port = 443
    return DriveConnectionManager(
        host=host,
        username=str(cfg.get("username", "") or ""),
        password=str(cfg.get("password", "") or ""),
        port=port,
        verify_ssl=verify_ssl,
        ssl_fingerprint=fingerprint if host else None,
        tls_env_prefix="DRIVE",
        timeout_seconds=_timeout_seconds(),
    )


@lru_cache
def get_system_manager() -> DriveSystemManager:
    return DriveSystemManager(get_connection_manager())


@lru_cache
def get_storage_manager() -> StorageManager:
    return StorageManager(get_connection_manager())


@lru_cache
def get_shared_drive_manager() -> SharedDriveManager:
    return SharedDriveManager(get_connection_manager())


@lru_cache
def get_file_service_manager() -> FileServiceManager:
    return FileServiceManager(get_connection_manager(), get_shared_drive_manager())


@lru_cache
def get_gate_settings() -> GateSettings:
    """Operation-gate limits from UNIFI_DRIVE_* or the shared UNIFI_*; a bad value refuses startup."""
    return gate_settings_from_env("DRIVE", logger=logger)


def get_operation_gate() -> OperationGate | None:
    """This server's NAS operation gate; ``None`` while no host is configured (setup mode).

    Keyed by the configured host and port plus the product, so it outlives any
    connection manager and is shared by every tool call in this process.
    """
    cm = get_connection_manager()
    if not cm.host:
        return None
    return gate_registry().get(GateKey.for_host(cm.host, cm.port, "drive"), get_gate_settings())


@lru_cache
def get_tool_registry() -> dict[str, Any]:
    """Return the global tool registry for runtime access."""
    return TOOL_REGISTRY


config = get_config()
server = get_server()
connection_manager = get_connection_manager()
system_manager = get_system_manager()
storage_manager = get_storage_manager()
shared_drive_manager = get_shared_drive_manager()
file_service_manager = get_file_service_manager()
tool_registry = get_tool_registry()
# Read now, so a bad gate setting refuses startup instead of the first tool call.
gate_settings = get_gate_settings()


def should_redact_sensitive_fields() -> bool:
    """Whether Drive MCP responses should redact sensitive fields."""
    return should_redact_response_sensitive_fields("drive", config)


def tool_success(data: Any) -> dict[str, Any]:
    """A successful tool response, redacted according to the response policy."""
    return redact_sensitive_fields({"success": True, "data": data}, redact_sensitive=should_redact_sensitive_fields())


def tool_failure(operation: str, exc: Exception) -> dict[str, Any]:
    """Log a failed tool call and build its error response.

    Drive errors are built from fixed text, the request path, the HTTP status
    and a length-capped upstream message with the NAS address removed; their
    message is returned. Anything else may carry request details: only its
    class is returned. A change stopped before it was sent reports
    ``mutation_applied: false`` (the gate's own outcome counts the write's
    earlier reads as sent); a change sent and never answered reports
    ``mutation_applied: null``.
    """
    if isinstance(exc, (DriveWriteNotSent, DriveWriteOutcomeUnknown)):
        logger.error("Failed to %s: %s", operation, exc)
        applied = False if isinstance(exc, DriveWriteNotSent) else None
        return {"success": False, "error": f"Failed to {operation}: {exc}", "mutation_applied": applied}
    if isinstance(exc, UniFiError):
        logger.error("Failed to %s: %s", operation, exc)
        return {"success": False, "error": f"Failed to {operation}: {exc}"}
    logger.error("Failed to %s: unexpected %s", operation, type(exc).__name__, exc_info=True)
    return {"success": False, "error": f"Failed to {operation}: unexpected {type(exc).__name__}"}


logger.debug("runtime.py: shared singletons initialised")
