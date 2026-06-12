"""Deterministic response redaction for UniFi controller payloads."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

REDACTED = "***REDACTED***"

_SENSITIVE_SEGMENTS = frozenset(
    {
        "password",
        "passphrase",
        "psk",
        "secret",
        "token",
        "authorization",
        "cookie",
    }
)

_SENSITIVE_EXACT = frozenset(
    {
        "auth",
        "x_password",
        "x_passphrase",
        "api_key",
        "api_token",
        "private_key",
        "privatekey",
        "wireguard_private_key",
        "wireguardprivatekey",
        "preshared_key",
        "presharedkey",
        "auth_key",
        "authkey",
        "tls_auth",
        "tlsauth",
        "tls_crypt",
        "tlscrypt",
        "pin_code",
        "pincode",
    }
)

_SENSITIVE_COMPOUNDS = frozenset(
    {
        "xpassphrase",
        "apikey",
        "apitoken",
        "privatekey",
        "wireguardprivatekey",
        "presharedkey",
        "authkey",
        "tlsauth",
        "tlscrypt",
        "pincode",
    }
)


def _segments(key: str) -> list[str]:
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    return [part for part in re.split(r"[^A-Za-z0-9]+", camel_split.lower()) if part]


def is_sensitive_key(key: Any) -> bool:
    """Return true when a mapping key conventionally carries secret material."""
    if not isinstance(key, str) or not key:
        return False
    parts = _segments(key)
    if not parts:
        return False
    normalized = "_".join(parts)
    compound = "".join(parts)
    if normalized in _SENSITIVE_EXACT or compound in _SENSITIVE_EXACT:
        return True
    if compound in _SENSITIVE_COMPOUNDS:
        return True
    for index, part in enumerate(parts):
        if part not in _SENSITIVE_SEGMENTS:
            continue
        if part == "token" and index + 1 < len(parts) and parts[index + 1] in {"count", "counts"}:
            continue
        return True
    return False


def redact_sensitive_fields(
    obj: Any,
    *,
    include_sensitive: bool = False,
    marker: str = REDACTED,
) -> Any:
    """Return a redacted copy of ``obj``."""
    if include_sensitive:
        return obj
    if isinstance(obj, Mapping):
        return {
            key: marker
            if value is not None and is_sensitive_key(key)
            else redact_sensitive_fields(value, marker=marker)
            for key, value in obj.items()
        }
    if isinstance(obj, tuple):
        return tuple(redact_sensitive_fields(value, marker=marker) for value in obj)
    if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        return [redact_sensitive_fields(value, marker=marker) for value in obj]
    return obj
