"""Tool and API diagnostics for MCP servers.

This module provides diagnostic logging for tool calls and API requests,
with configurable redaction, truncation, and payload limits.

Servers initialize diagnostics at startup via ``init_diagnostics()``
to inject their config provider (avoiding circular imports).

Example::

    from unifi_core.diagnostics import init_diagnostics, diagnostics_enabled, wrap_tool

    # During server bootstrap:
    init_diagnostics(
        config_provider=lambda: runtime.config,
        logger_name="unifi-network-mcp.diagnostics",
    )
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import time
from functools import wraps
from typing import Any, Callable, Dict

from unifi_core.redaction import REDACTED, is_sensitive_key, redact_sensitive_fields

# Module-level state set by init_diagnostics()
_config_provider: Callable[[], Any] | None = None
_logger: logging.Logger = logging.getLogger(__name__)


def init_diagnostics(
    config_provider: Callable[[], Any] | None = None,
    logger_name: str = "diagnostics",
) -> None:
    """Initialize the diagnostics module with a server-specific config provider.

    This must be called before diagnostics will use YAML config. Without
    initialization, the module falls back to environment variables only.

    Args:
        config_provider: A callable returning the server's OmegaConf config object.
                         Called lazily on each diagnostics check.
        logger_name: Logger name for diagnostic output (e.g. "unifi-network-mcp.diagnostics").
    """
    global _config_provider, _logger
    _config_provider = config_provider
    _logger = logging.getLogger(logger_name)


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------


def _get_bool_env(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _get_int_env(name: str, default: int) -> int:
    val = os.getenv(name)
    if not val:
        return default
    try:
        return int(val)
    except Exception:
        return default


def _server_diag_cfg_from_env() -> Dict[str, Any]:
    return {
        "enabled": _get_bool_env("UNIFI_MCP_DIAGNOSTICS", False),
        "log_tool_args": _get_bool_env("UNIFI_MCP_DIAG_LOG_TOOL_ARGS", True),
        "log_tool_result": _get_bool_env("UNIFI_MCP_DIAG_LOG_TOOL_RESULT", True),
        "max_payload_chars": _get_int_env("UNIFI_MCP_DIAG_MAX_PAYLOAD", 2000),
    }


def _server_diag_cfg_from_config() -> Dict[str, Any]:
    if _config_provider is None:
        return _server_diag_cfg_from_env()
    try:
        config = _config_provider()
        server_cfg = getattr(config, "server", {}) or {}
        diag_cfg = server_cfg.get("diagnostics", {}) or {}
        return {
            "enabled": bool(diag_cfg.get("enabled", False)),
            "log_tool_args": bool(diag_cfg.get("log_tool_args", True)),
            "log_tool_result": bool(diag_cfg.get("log_tool_result", True)),
            "max_payload_chars": int(diag_cfg.get("max_payload_chars", 2000)),
        }
    except Exception:
        return _server_diag_cfg_from_env()


def _diag_cfg() -> Dict[str, Any]:
    return _server_diag_cfg_from_config()


def diagnostics_enabled() -> bool:
    """Return True if diagnostics logging is enabled."""
    return bool(_diag_cfg().get("enabled", False))


# ---------------------------------------------------------------------------
# Redaction / truncation helpers
# ---------------------------------------------------------------------------

def _redact_value(key: str, value: Any) -> Any:
    if is_sensitive_key(key):
        return REDACTED
    return value


def _redact(obj: Any) -> Any:
    try:
        return redact_sensitive_fields(obj)
    except Exception:
        return obj


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [truncated {len(text) - limit} chars]"


def _safe_json(data: Any, limit: int) -> str:
    try:
        redacted = _redact(data)
        as_text = json.dumps(redacted, ensure_ascii=False, default=str)
    except Exception:
        try:
            as_text = str(data)
        except Exception:
            as_text = "<unserializable>"
    return _truncate(as_text, limit)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def log_tool_call(
    tool_name: str,
    args: Any,
    kwargs: Dict[str, Any],
    result: Any | None,
    duration_ms: float,
    error: Exception | None = None,
) -> None:
    """Log a tool invocation with redaction and truncation."""
    if not diagnostics_enabled():
        return
    cfg = _diag_cfg()
    parts = {"tool": tool_name, "duration_ms": int(duration_ms)}
    if cfg.get("log_tool_args", True):
        try:
            parts["args"] = args
            parts["kwargs"] = kwargs
        except Exception:
            parts["args"] = "<unserializable>"
            parts["kwargs"] = "<unserializable>"
    if error is not None:
        parts["error"] = str(error)
    elif cfg.get("log_tool_result", True):
        parts["result"] = result

    max_chars = int(cfg.get("max_payload_chars", 2000))
    text = _safe_json(parts, max_chars)
    _logger.info("TOOL %s", text)


def wrap_tool(func, tool_name: str):
    """Wrap a tool function with diagnostics logging.

    IMPORTANT: Preserves the original function's signature so that FastMCP
    can correctly generate the JSON schema for tool parameters.
    """

    @wraps(func)
    async def _wrapper(*args, **kwargs):
        if not diagnostics_enabled():
            return await func(*args, **kwargs)
        start = time.perf_counter()
        err: Exception | None = None
        res: Any | None = None
        try:
            res = await func(*args, **kwargs)
            return res
        except Exception as e:  # noqa: BLE001 - we re-raise after logging
            err = e
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000.0
            try:
                log_tool_call(tool_name, args, kwargs, res, duration_ms, err)
            except Exception:
                # Never let diagnostics break the tool
                pass

    # Preserve the original function's signature for FastMCP schema generation
    _wrapper.__signature__ = inspect.signature(func)
    return _wrapper


def log_api_request(method: str, path: str, payload: Any, response: Any, duration_ms: float, ok: bool) -> None:
    """Log an API request with redaction and truncation."""
    if not diagnostics_enabled():
        return
    cfg = _diag_cfg()
    max_chars = int(cfg.get("max_payload_chars", 2000))
    entry = {
        "method": method.upper(),
        "path": path,
        "ok": ok,
        "duration_ms": int(duration_ms),
        "request": json.loads(_safe_json(payload, max_chars)) if payload is not None else None,
        "response": json.loads(_safe_json(response, max_chars)) if response is not None else None,
    }
    _logger.info("API %s", _safe_json(entry, max_chars))
