"""Canonical policy helpers for UniFi shared packages."""

import logging
import os
from collections.abc import Mapping
from typing import Any

from unifi_core.policy_gate import (
    _FALSY,
    _TRUTHY,
    PolicyGateChecker,
    check_deprecated_env_vars,
    resolve_permission_mode,
)

logger = logging.getLogger(__name__)

_CONFIG_PATH = ("policy", "response", "redact_sensitive_fields")
_CONFIG_LABEL = ".".join(_CONFIG_PATH)


def should_redact_sensitive_fields(
    server_prefix: str,
    config: Any | None = None,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Resolve whether sensitive response fields should be redacted.

    Precedence:
      1. UNIFI_<SERVER>_REDACT_SENSITIVE_FIELDS
      2. UNIFI_REDACT_SENSITIVE_FIELDS
      3. policy.response.redact_sensitive_fields from config
      4. default True
    """
    env_values = os.environ if env is None else env
    prefix_upper = server_prefix.strip().upper()

    for name in (
        f"UNIFI_{prefix_upper}_REDACT_SENSITIVE_FIELDS",
        "UNIFI_REDACT_SENSITIVE_FIELDS",
    ):
        value = env_values.get(name)
        # An empty / whitespace-only value is treated as unset so it falls
        # through to the next precedence tier rather than masking a
        # config-level disable (and avoids a spurious invalid-value warning).
        if value is not None and value.strip():
            return _parse_policy_bool(value, source=name)

    config_value = _get_nested_config_value(config, _CONFIG_PATH)
    if config_value is not None:
        return _parse_policy_bool(config_value, source=_CONFIG_LABEL)

    return True


def _parse_policy_bool(value: Any, *, source: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUTHY:
            return True
        if normalized in _FALSY:
            return False

    logger.warning("[policy] Invalid value for %s=%r, treating as redacted", source, value)
    return True


def _get_nested_config_value(config: Any | None, path: tuple[str, ...]) -> Any | None:
    current = config
    for key in path:
        if current is None:
            return None
        if isinstance(current, Mapping):
            current = current.get(key)
            continue
        current = getattr(current, key, None)
    return current


__all__ = [
    "PolicyGateChecker",
    "check_deprecated_env_vars",
    "resolve_permission_mode",
    "should_redact_sensitive_fields",
]
