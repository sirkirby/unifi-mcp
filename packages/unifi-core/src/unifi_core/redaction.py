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
        "private_preshared_keys",
        "privatepresharedkeys",
        "wireguard_private_key",
        "wireguardprivatekey",
        "preshared_key",
        "presharedkey",
        "auth_key",
        "authkey",
        "x_iapp_key",
        "xiappkey",
        "community",
        "snmp_community",
        "snmpcommunity",
        "tls_auth",
        "tlsauth",
        "tls_crypt",
        "tlscrypt",
        "pin_code",
        "pincode",
        "rtsp_alias",
        "rtsp_url",
        "rtsps_url",
        "rtsps_streams",
        # VPN config blobs: the secret rides inside the value (e.g. a WireGuard
        # .conf with `PrivateKey =`, or an OpenVPN .ovpn with an embedded
        # tls-crypt static key). Key-name matching can't see into the value, so
        # the whole blob field is treated as a secret (suppression).
        "openvpn_configuration",
        "wireguard_client_configuration_file",
        "wireguard_server_configuration_file",
    }
)

# Words that name secret key material only when immediately followed by "key".
# Requiring the pair keeps role-infixed controller fields such as
# ``wireguard_client_private_key`` sensitive while leaving non-secret keys like
# ``public_key`` and ``network_key`` visible.
_SENSITIVE_KEY_QUALIFIERS = frozenset({"private", "preshared"})

_SENSITIVE_COMPOUNDS = frozenset(
    {
        "xpassphrase",
        "apikey",
        "apitoken",
        "privatekey",
        "privatepresharedkeys",
        "wireguardprivatekey",
        "presharedkey",
        "authkey",
        "xiappkey",
        "snmpcommunity",
        "tlsauth",
        "tlscrypt",
        "pincode",
        "rtspalias",
        "rtspurl",
        "rtspsurl",
        "rtspsstreams",
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
    for left, right in zip(parts, parts[1:]):
        if right == "key" and left in _SENSITIVE_KEY_QUALIFIERS:
            return True
    # "preshared" sometimes arrives underscore-split as "pre_shared" (e.g. the
    # controller's x_ipsec_pre_shared_key field) — match that 3-gram too.
    for first, second, third in zip(parts, parts[1:], parts[2:]):
        if (first, second, third) == ("pre", "shared", "key"):
            return True
    return False


def redact_value(
    key: Any,
    value: Any,
    *,
    redact_sensitive: bool = True,
    marker: str = REDACTED,
) -> Any:
    """Redact a single ``key``/``value`` pair by the shared vocabulary.

    Returns ``marker`` when ``key`` names secret material and ``value`` is
    present; otherwise returns ``value`` unchanged. Use at boundaries that
    project individual fields (e.g. typed serializers) so the sensitivity
    decision stays routed through :func:`is_sensitive_key` rather than a
    local hard-coded field list.
    """
    if not redact_sensitive or value is None:
        return value
    return marker if is_sensitive_key(key) else value


def redact_sensitive_fields(
    obj: Any,
    *,
    redact_sensitive: bool = True,
    marker: str = REDACTED,
) -> Any:
    """Return a redacted copy of ``obj``."""
    if not redact_sensitive:
        return obj
    if isinstance(obj, Mapping):
        return {
            key: marker
            if value is not None and is_sensitive_key(key)
            else redact_sensitive_fields(value, redact_sensitive=redact_sensitive, marker=marker)
            for key, value in obj.items()
        }
    if isinstance(obj, tuple):
        return tuple(redact_sensitive_fields(value, redact_sensitive=redact_sensitive, marker=marker) for value in obj)
    if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        return [redact_sensitive_fields(value, redact_sensitive=redact_sensitive, marker=marker) for value in obj]
    return obj


def redaction_marker_paths(obj: Any, *, marker: str = REDACTED, prefix: str = "") -> list[str]:
    """Return sensitive-key paths whose value is the redaction marker."""
    paths: list[str] = []
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if value == marker and is_sensitive_key(key_text):
                paths.append(path)
            paths.extend(redaction_marker_paths(value, marker=marker, prefix=path))
    elif isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        for index, value in enumerate(obj):
            path = f"{prefix}[{index}]" if prefix else f"[{index}]"
            paths.extend(redaction_marker_paths(value, marker=marker, prefix=path))
    return paths
