"""MCP response policy helpers."""

from typing import Any

from unifi_core.policy import should_redact_sensitive_fields


def should_redact_response_sensitive_fields(server_prefix: str, config: Any | None = None) -> bool:
    """Return whether MCP responses should redact sensitive fields."""
    return should_redact_sensitive_fields(server_prefix, config=config)
