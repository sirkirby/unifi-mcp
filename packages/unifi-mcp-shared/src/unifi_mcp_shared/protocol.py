"""MCP protocol abstraction layer.

Provides a version-aware adapter for the FastMCP tool decorator, enabling
dual-track migration when MCP SDK v2 arrives. Today this is a passthrough
to FastMCP v1. When v2 ships, a v2 adapter can be added here without
touching any tool modules.

The adapter sits at Layer 1 of the decorator chain:

    Tool module calls @server.tool()
      -> permissioned_tool (Layer 3: permission checks + diagnostics)
        -> create_mcp_tool_adapter result (Layer 1: this module)
          -> FastMCP server.tool (actual registration)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Known protocol versions. "v2" is recognized but not yet implemented.
_KNOWN_VERSIONS = {"v1", "v2"}


def get_protocol_version() -> str:
    """Read the MCP protocol version from environment.

    Returns "v1" by default. Set UNIFI_MCP_PROTOCOL_VERSION=v2 to
    switch when v2 support is added.
    """
    return os.environ.get("UNIFI_MCP_PROTOCOL_VERSION", "v1").strip()


def create_mcp_tool_adapter(
    fastmcp_tool_decorator: Callable[..., Any],
    *,
    protocol_version: str | None = None,
) -> Callable[..., Any]:
    """Wrap the FastMCP tool decorator with protocol-version awareness.

    Args:
        fastmcp_tool_decorator: The raw FastMCP ``server.tool`` decorator.
        protocol_version: Override version (default: from env var).

    Returns:
        A decorator with the same signature as ``server.tool``.
        In v1 mode, this is a direct passthrough (zero overhead).

    Raises:
        ValueError: If the protocol version is unknown or not yet implemented.
    """
    version = protocol_version or get_protocol_version()

    if version not in _KNOWN_VERSIONS:
        raise ValueError(f"Unsupported protocol version: '{version}'. Known versions: {sorted(_KNOWN_VERSIONS)}")

    if version == "v1":
        logger.debug("[protocol] Using MCP v1 adapter (passthrough)")
        return fastmcp_tool_decorator

    if version == "v2":
        raise ValueError(
            "MCP protocol v2 is not yet implemented. Set UNIFI_MCP_PROTOCOL_VERSION=v1 or remove the variable."
        )

    # Unreachable, but satisfies type checkers
    raise ValueError(f"Unhandled protocol version: {version}")
