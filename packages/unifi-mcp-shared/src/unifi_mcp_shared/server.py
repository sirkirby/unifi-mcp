"""Shared UniFi MCP server boundary."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context
from mcp.server.transport_security import TransportSecuritySettings

from unifi_mcp_shared.protocol import get_request_protocol_revision
from unifi_mcp_shared.response_policy import MCPContentMode
from unifi_mcp_shared.response_serialization import serialize_call_tool_result
from unifi_mcp_shared.strict_dispatch import StrictKwargFastMCP

_DEFAULT_ALLOWED_HOSTS = "localhost,127.0.0.1"


class UniFiMCPServer(StrictKwargFastMCP):
    """Apply UniFi response policy after strict FastMCP dispatch."""

    def __init__(
        self,
        *args: Any,
        mcp_content_mode: MCPContentMode = "adaptive",
        **kwargs: Any,
    ) -> None:
        transport_security = kwargs.pop("transport_security", None)
        super().__init__(*args, **kwargs)
        self._mcp_content_mode = mcp_content_mode
        self.transport_security = _normalize_transport_security(transport_security)

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context | None = None,
    ) -> Any:
        result = await super().call_tool(name, arguments, context=context)
        return serialize_call_tool_result(
            result,
            mode=self._mcp_content_mode,
            protocol_revision=get_request_protocol_revision(context),
            tool_name=name,
        )


def resolve_allowed_hosts(
    configured_hosts: str | None,
    *,
    override_hosts: str | None = None,
    internal_hosts: str | None = None,
) -> list[str]:
    """Resolve operator hosts, optional deployment override, and required internal hosts."""
    operator_hosts = configured_hosts if override_hosts is None else override_hosts
    configured = _DEFAULT_ALLOWED_HOSTS if operator_hosts is None else operator_hosts
    values = configured.split(",")
    if internal_hosts:
        values.extend(internal_hosts.split(","))
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _normalize_transport_security(
    settings: TransportSecuritySettings | None,
) -> TransportSecuritySettings | None:
    """Normalize v1-style bare hosts for the SDK v2 host-and-port matcher."""
    if settings is None:
        return None

    allowed_hosts = [_normalize_allowed_host(host) for host in settings.allowed_hosts]
    return settings.model_copy(update={"allowed_hosts": allowed_hosts})


def _normalize_allowed_host(host: str) -> str:
    value = host.strip()
    if not value or value == "*":
        return value
    if value.startswith("["):
        return value if "]:" in value else f"{value}:*"
    if value.count(":") > 1:
        return f"[{value}]:*"
    if ":" in value:
        return value
    return f"{value}:*"
