"""MCP response policy helpers."""

import logging
import os
from collections.abc import Mapping
from typing import Any, Literal, cast

from unifi_core.policy import _get_nested_config_value, should_redact_sensitive_fields

logger = logging.getLogger(__name__)

MCPContentMode = Literal["adaptive", "compat", "compact"]
_MCP_CONTENT_MODES = frozenset({"adaptive", "compat", "compact"})
_MCP_CONTENT_MODE_PATH = ("policy", "response", "mcp_content_mode")


def resolve_mcp_content_mode(
    server_prefix: str,
    config: Any | None = None,
    env: Mapping[str, str] | None = None,
) -> MCPContentMode:
    """Resolve the MCP response content mode from environment or config."""
    env_values = os.environ if env is None else env
    prefix_upper = server_prefix.strip().upper()
    for name in (f"UNIFI_{prefix_upper}_MCP_CONTENT_MODE", "UNIFI_MCP_CONTENT_MODE"):
        value = env_values.get(name)
        if value is not None and value.strip():
            return _parse_mcp_content_mode(value, source=name)

    value = _get_nested_config_value(config, _MCP_CONTENT_MODE_PATH)
    if value is not None:
        return _parse_mcp_content_mode(value, source="policy.response.mcp_content_mode")
    return "adaptive"


def _parse_mcp_content_mode(value: Any, *, source: str) -> MCPContentMode:
    normalized = str(value).strip().lower()
    if normalized in _MCP_CONTENT_MODES:
        return cast(MCPContentMode, normalized)
    logger.warning("[response-policy] Invalid value for %s=%r, using adaptive", source, value)
    return "adaptive"


def should_redact_response_sensitive_fields(server_prefix: str, config: Any | None = None) -> bool:
    """Return whether MCP responses should redact sensitive fields."""
    return should_redact_sensitive_fields(server_prefix, config=config)
