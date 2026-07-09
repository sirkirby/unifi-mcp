"""MCP protocol abstraction layer.

Provides a revision-aware adapter for the FastMCP tool decorator, enabling
date-versioned MCP spec alignment without touching individual tool modules.
Today this is a passthrough for the currently supported MCP protocol
revision. If a future MCP revision requires SDK or registration changes, a
revision-specific adapter can be added here.

The adapter sits at Layer 1 of the decorator chain:

    Tool module calls @server.tool()
      -> permissioned_tool (Layer 3: permission checks + diagnostics)
        -> create_mcp_tool_adapter result (Layer 1: this module)
          -> FastMCP server.tool (actual registration)
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_MCP_PROTOCOL_REVISION = "2025-11-25"
FUTURE_MCP_PROTOCOL_REVISION = "2026-07-28"
STRUCTURED_CONTENT_PROTOCOL_REVISION = "2025-06-18"

_KNOWN_REVISIONS = frozenset({DEFAULT_MCP_PROTOCOL_REVISION})
_KNOWN_PROTOCOL_TARGETS = frozenset(
    {
        DEFAULT_MCP_PROTOCOL_REVISION,
        FUTURE_MCP_PROTOCOL_REVISION,
    }
)
_LEGACY_PROTOCOL_VERSION_ALIASES = {
    "v1": DEFAULT_MCP_PROTOCOL_REVISION,
}


def _normalize_protocol_revision(value: str) -> str:
    raw_value = value.strip()
    if raw_value in _LEGACY_PROTOCOL_VERSION_ALIASES:
        return _LEGACY_PROTOCOL_VERSION_ALIASES[raw_value]

    if raw_value.startswith("v"):
        raise ValueError(
            f"Unsupported MCP protocol version alias: '{raw_value}'. "
            f"Use date-based MCP protocol revisions such as '{DEFAULT_MCP_PROTOCOL_REVISION}'."
        )

    return raw_value


def get_protocol_revision() -> str:
    """Read the MCP protocol revision from environment.

    ``UNIFI_MCP_PROTOCOL_REVISION`` is the canonical setting. The legacy
    ``UNIFI_MCP_PROTOCOL_VERSION=v1`` setting remains supported as a
    compatibility alias for the current default revision.
    """
    configured_revision = os.environ.get("UNIFI_MCP_PROTOCOL_REVISION")
    if configured_revision is not None:
        return _normalize_protocol_revision(configured_revision)

    legacy_version = os.environ.get("UNIFI_MCP_PROTOCOL_VERSION")
    if legacy_version is not None:
        return _normalize_protocol_revision(legacy_version)

    return DEFAULT_MCP_PROTOCOL_REVISION


def is_known_protocol_target(value: str) -> bool:
    """Return whether a revision is tracked as a current or future MCP target."""
    return _normalize_protocol_revision(value) in _KNOWN_PROTOCOL_TARGETS


def structured_content_supported(protocol_revision: str | None) -> bool:
    """Return whether a negotiated MCP revision supports structured tool results."""
    if not protocol_revision:
        return False
    try:
        parsed_revision = date.fromisoformat(protocol_revision)
        if parsed_revision.isoformat() != protocol_revision:
            return False
        return parsed_revision >= date.fromisoformat(STRUCTURED_CONTENT_PROTOCOL_REVISION)
    except ValueError:
        return False


def get_request_protocol_revision(server: Any) -> str | None:
    """Read the negotiated revision for the current SDK-v1 request, if any.

    This is the only SDK-v1-specific session metadata read. Replace this helper
    when SDK v2 exposes protocol metadata through per-request envelopes.
    """
    try:
        context = server.get_context()
        client_params = context.session.client_params
        revision = client_params.protocolVersion if client_params is not None else None
        return str(revision) if revision else None
    except (AttributeError, LookupError, RuntimeError, ValueError):
        return None


def create_mcp_tool_adapter(
    fastmcp_tool_decorator: Callable[..., Any],
    *,
    protocol_revision: str | None = None,
) -> Callable[..., Any]:
    """Wrap the FastMCP tool decorator with protocol-revision awareness.

    Args:
        fastmcp_tool_decorator: The raw FastMCP ``server.tool`` decorator.
        protocol_revision: Override MCP spec revision (default: from env var).

    Returns:
        A decorator with the same signature as ``server.tool``.
        For the current revision, this is a direct passthrough (zero overhead).

    Raises:
        ValueError: If the protocol revision is unknown or unsupported.
    """
    if protocol_revision is not None:
        revision = _normalize_protocol_revision(protocol_revision)
    else:
        revision = get_protocol_revision()

    if revision not in _KNOWN_REVISIONS:
        raise ValueError(
            f"Unsupported MCP protocol revision: '{revision}'. Known revisions: {sorted(_KNOWN_REVISIONS)}"
        )

    if revision == DEFAULT_MCP_PROTOCOL_REVISION:
        logger.debug("[protocol] Using MCP %s adapter (passthrough)", revision)
        return fastmcp_tool_decorator

    # Unreachable, but satisfies type checkers
    raise ValueError(f"Unhandled MCP protocol revision: {revision}")
