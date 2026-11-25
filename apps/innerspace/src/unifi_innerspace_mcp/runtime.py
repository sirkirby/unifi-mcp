# ruff: noqa: E402
from __future__ import annotations

"""Shared runtime objects for the UniFi InnerSpace MCP server.

The single source of truth for the FastMCP server instance, the loaded
configuration and the managers. Tool modules import these aliases; tests
substitute fakes by monkey-patching them.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, ValidationError

from unifi_core.exceptions import UniFiError
from unifi_core.innerspace.managers.attenuation_manager import InnerSpaceAttenuationManager
from unifi_core.innerspace.managers.connection_manager import InnerSpaceConnectionManager
from unifi_core.innerspace.managers.floor_plan_manager import InnerSpaceFloorPlanManager
from unifi_core.innerspace.managers.inventory_manager import InnerSpaceInventoryManager
from unifi_core.innerspace.managers.project_manager import InnerSpaceProjectManager
from unifi_core.innerspace.managers.project_settings_manager import InnerSpaceProjectSettingsManager
from unifi_core.innerspace.managers.system_manager import InnerSpaceSystemManager
from unifi_core.innerspace.managers.wall_manager import InnerSpaceWallManager
from unifi_core.innerspace.managers.wall_type_manager import InnerSpaceWallTypeManager
from unifi_core.innerspace.models import writes as write_models
from unifi_core.operation_gate import GateKey, GateSettings, OperationGate, gate_registry
from unifi_core.redaction import redact_sensitive_fields
from unifi_core.tls import ssl_setting
from unifi_core.write_verification import WriteVerificationResult, format_tool_payload
from unifi_innerspace_mcp.bootstrap import load_config, logger
from unifi_innerspace_mcp.tool_index import TOOL_REGISTRY
from unifi_mcp_shared.bootstrap import credential_cut_hint, resolve_env
from unifi_mcp_shared.metadata import PROJECT_WEBSITE_URL, configure_mcp_server_metadata
from unifi_mcp_shared.response_policy import resolve_mcp_content_mode, should_redact_response_sensitive_fields
from unifi_mcp_shared.server import UniFiMCPServer, resolve_allowed_hosts
from unifi_mcp_shared.tool_gate import gate_settings_from_env

_TOOLS_MANIFEST_PATH = Path(__file__).resolve().parent / "tools_manifest.json"


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
        name="unifi-innerspace-mcp",
        debug=False,
        website_url=PROJECT_WEBSITE_URL,
        transport_security=transport_security,
        tools_manifest_path=_TOOLS_MANIFEST_PATH,
        mcp_content_mode=resolve_mcp_content_mode("innerspace", config=get_config()),
    )
    configure_mcp_server_metadata(server, package_name="unifi-innerspace-mcp", icon_family="innerspace")

    # Until main.py installs the full permissioned_tool, a fail-closed stand-in
    # accepts the permission kwargs so tool modules can be imported directly.
    from unifi_mcp_shared.permissioned_tool import create_import_time_tool_decorator
    from unifi_mcp_shared.protocol import create_mcp_tool_adapter

    server._original_tool = create_mcp_tool_adapter(server.tool)
    server.tool = create_import_time_tool_decorator(server._original_tool, logger=logger)

    return server


def _ssl_fingerprint(cfg: Any) -> str | None:
    """A pin from the environment, or from an operator's ``CONFIG_PATH`` file.

    Read here rather than through ``load_config``'s keys, which log their values at
    debug level: a malformed pin is rejected without being echoed, and the value
    may be something pasted by mistake.
    """
    value = resolve_env("ssl_fingerprint", env_prefix="INNERSPACE", logger=logger) or cfg.get("ssl_fingerprint")
    return str(value) if value else None


def _tls_settings(cfg: Any) -> tuple[bool, str | None]:
    """``verify_ssl`` and the pin, checked at startup.

    A malformed pin stops the server rather than starting without the check the
    operator asked for; the log line never echoes it. The warning that nothing
    checks the console is the connection manager's, logged once at its first
    request, so it is not repeated here.
    """
    verify_ssl = str(cfg.verify_ssl).lower() in ("true", "1", "yes")
    fingerprint = _ssl_fingerprint(cfg)
    try:
        ssl_setting(verify_ssl, fingerprint)
    except ValueError as error:
        logger.critical("Invalid UNIFI_SSL_FINGERPRINT or UNIFI_INNERSPACE_SSL_FINGERPRINT: %s", error)
        raise SystemExit(2) from None
    return verify_ssl, fingerprint


def _port(cfg: Any) -> int:
    """The console port; an empty value, as a compose file passes for an unset one, is the default 443."""
    value = str(cfg.port).strip()
    return int(value) if value else 443


@lru_cache
def get_connection_manager() -> InnerSpaceConnectionManager:
    cfg = get_config().unifi
    verify_ssl, fingerprint = _tls_settings(cfg)
    try:
        return InnerSpaceConnectionManager(
            host=cfg.host,
            username=cfg.username,
            password=cfg.password,
            port=_port(cfg),
            verify_ssl=verify_ssl,
            ssl_fingerprint=fingerprint,
            tls_env_prefix="INNERSPACE",
            auth_failure_hint=credential_cut_hint("INNERSPACE"),
        )
    except ValueError:
        # The manager's text is fixed and carries nothing from the settings.
        logger.critical("UNIFI_INNERSPACE_HOST and UNIFI_INNERSPACE_PORT must name a valid console address.")
        raise SystemExit(2) from None


@lru_cache
def get_project_manager() -> InnerSpaceProjectManager:
    return InnerSpaceProjectManager(get_connection_manager())


@lru_cache
def get_floor_plan_manager() -> InnerSpaceFloorPlanManager:
    return InnerSpaceFloorPlanManager(get_connection_manager())


@lru_cache
def get_inventory_manager() -> InnerSpaceInventoryManager:
    return InnerSpaceInventoryManager(get_connection_manager())


@lru_cache
def get_system_manager() -> InnerSpaceSystemManager:
    return InnerSpaceSystemManager(get_connection_manager())


@lru_cache
def get_gate_settings() -> GateSettings:
    """Operation-gate limits from UNIFI_INNERSPACE_* or the shared UNIFI_*; a bad value refuses startup."""
    return gate_settings_from_env("INNERSPACE", logger=logger)


def get_operation_gate() -> OperationGate | None:
    """This server's console operation gate; ``None`` while no host is configured (setup mode).

    Keyed by the configured host and port plus the product, so it outlives any
    connection manager and is shared by every tool call in this process.
    """
    cm = get_connection_manager()
    if not cm.host:
        return None
    return gate_registry().get(GateKey.for_host(cm.host, cm.port, "innerspace"), get_gate_settings())


@lru_cache
def get_wall_manager() -> InnerSpaceWallManager:
    return InnerSpaceWallManager(get_connection_manager())


@lru_cache
def get_wall_type_manager() -> InnerSpaceWallTypeManager:
    return InnerSpaceWallTypeManager(get_connection_manager())


@lru_cache
def get_attenuation_manager() -> InnerSpaceAttenuationManager:
    return InnerSpaceAttenuationManager(get_connection_manager())


@lru_cache
def get_project_settings_manager() -> InnerSpaceProjectSettingsManager:
    return InnerSpaceProjectSettingsManager(get_connection_manager())


@lru_cache
def get_tool_registry() -> dict[str, Any]:
    """Return the global tool registry for runtime access."""
    return TOOL_REGISTRY


config = get_config()
server = get_server()
connection_manager = get_connection_manager()
project_manager = get_project_manager()
floor_plan_manager = get_floor_plan_manager()
inventory_manager = get_inventory_manager()
system_manager = get_system_manager()
wall_manager = get_wall_manager()
wall_type_manager = get_wall_type_manager()
attenuation_manager = get_attenuation_manager()
project_settings_manager = get_project_settings_manager()
tool_registry = get_tool_registry()
# Read now, so a bad gate setting refuses startup instead of the first tool call.
gate_settings = get_gate_settings()


def should_redact_sensitive_fields() -> bool:
    """Whether InnerSpace MCP responses should redact sensitive fields."""
    return should_redact_response_sensitive_fields("innerspace", config)


def tool_success(data: dict[str, Any]) -> dict[str, Any]:
    """A successful tool response, redacted according to the response policy."""
    return redact_sensitive_fields({"success": True, "data": data}, redact_sensitive=should_redact_sensitive_fields())


def tool_failure(operation: str, error: BaseException) -> dict[str, Any]:
    """Log a failed tool call and build its error response.

    InnerSpace errors are built from fixed text, the HTTP status and an error
    code, so their message is returned; when it already starts with the
    operation, the operation is not repeated. Invalid arguments get fixed text:
    the rejected value is never echoed. Anything else may carry request
    details: only its class is logged and returned.
    """
    logger.error("Failed to %s: %s", operation, type(error).__name__)
    if isinstance(error, UniFiError):
        text = str(error)
        if text.startswith(f"{operation}:"):
            return {"success": False, "error": f"Failed to {text}"}
        return {"success": False, "error": f"Failed to {operation}: {text}"}
    if isinstance(error, ValidationError):
        return {"success": False, "error": f"Failed to {operation}: invalid arguments"}
    return {"success": False, "error": f"Failed to {operation}: unexpected {type(error).__name__}"}


# Field names of the write arguments: the only parts of a validation error's location a reply may name.
_WRITE_FIELDS = frozenset(
    name
    for model in vars(write_models).values()
    if isinstance(model, type) and issubclass(model, BaseModel)
    for name in model.model_fields
)
_MAX_REPORTED_ERRORS = 3
NO_CHANGE = "No change: the console already holds the requested values, so nothing was sent."
ALREADY_APPLIED = "Already applied: an earlier call with the same arguments created these objects, so nothing was sent."
NONE_FOUND = (
    "Nothing to remove: none of these ids is in the project (already removed, or never existed), so nothing was sent."
)
# The one message for each reason a confirmed write sent nothing (the core's ``noop``).
_NOOP_MESSAGES = {"already_applied": ALREADY_APPLIED, "none_found": NONE_FOUND}


def _invalid_arguments(error: ValidationError) -> str:
    """Pydantic's fixed messages, located by known field names and indexes only; never a value or a caller's key."""
    parts = []
    for item in error.errors(include_url=False, include_input=False, include_context=False)[:_MAX_REPORTED_ERRORS]:
        where = ".".join(str(p) for p in item["loc"] if isinstance(p, int) or p in _WRITE_FIELDS)
        parts.append(f"{where}: {item['msg']}" if where else item["msg"])
    return "; ".join(parts)


def write_failure(operation: str, error: BaseException) -> dict[str, Any]:
    """A write tool's error response; invalid arguments name the field and the rule, never the value."""
    if isinstance(error, ValidationError):
        logger.error("Failed to %s: %s", operation, type(error).__name__)
        return {"success": False, "error": f"Failed to {operation}: invalid arguments: {_invalid_arguments(error)}"}
    return tool_failure(operation, error)


def write_preview(preview: dict[str, Any]) -> dict[str, Any]:
    """A preview response: nothing was sent, and confirming with the same arguments applies it."""
    message = (
        "Nothing to change: confirming sends nothing."
        if preview.get("no_op")
        else "Review the preview, then call again with the same arguments and confirm=true to apply."
    )
    return redact_sensitive_fields(
        {"success": True, "requires_confirmation": True, "preview": preview, "message": message},
        redact_sensitive=should_redact_sensitive_fields(),
    )


def write_result(result: WriteVerificationResult, *, applied: str) -> dict[str, Any]:
    """A confirmed write's response: ``success`` follows the read-back, so a write not applied is a failure.

    ``mutation_applied`` False after a send is a failure; ``None`` is a failure whose outcome is unknown.
    A success that sent nothing says whether the values were already there or an earlier identical
    create made them.
    """
    payload = format_tool_payload(result, site="", success_message=applied)
    # InnerSpace writes take a plan id, not a site, so the payload names none.
    payload.pop("site", None)
    if result.success and result.mutation_applied is False:
        payload["message"] = _NOOP_MESSAGES.get(result.metadata.get("noop"), NO_CHANGE)
    elif not result.success or result.mutation_applied is None:
        # An unknown outcome is never a success, whatever the result says.
        payload["success"] = False
        payload.pop("message", None)
        error = result.error or f"{result.operation}: the change was not applied."
        if result.mutation_applied is None and "read before retrying" not in error.lower():
            error += " Whether it was applied is unknown; read before retrying."
        payload["error"] = f"Failed to {error}"
        logger.warning("Failed to %s: mutation_applied=%s", result.operation, result.mutation_applied)
    return redact_sensitive_fields(payload, redact_sensitive=should_redact_sensitive_fields())


logger.debug("runtime.py: shared singletons initialised")
