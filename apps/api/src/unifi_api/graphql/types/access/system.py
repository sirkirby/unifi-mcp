"""Strawberry types for access/system (Phase 6 PR4 Task B).

Two read serializers from ``unifi_api.serializers.access.system`` map to
two Strawberry classes:

- ``AccessSystemInfo`` — access_get_system_info (DETAIL). Mirrors
  ``AccessSystemInfoSerializer.serialize`` byte-for-byte. SystemManager
  populates two slightly different shapes (api-client probe path vs raw
  ``access/info`` proxy payload); ``from_manager_output`` normalizes
  across both with name/host fallbacks.
- ``AccessHealth`` — access_get_health (DETAIL). Mirrors
  ``AccessHealthSerializer.serialize`` byte-for-byte. Derives a single
  ``status`` field from per-probe healthy flags
  (``api_client_healthy`` / ``proxy_healthy``) plus optional door/device
  counts when surfaced via ``num_*`` keys.

The access manifest has no system mutation tools today, so the
serializer module ``serializers/access/system.py`` is removed entirely
once this migration lands.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry
from unifi_core.access.models.system import _int_from_value, _string_from_value


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


def _derive_health_status(obj: Any) -> str:
    explicit = _get(obj, "status")
    if isinstance(explicit, str):
        return explicit
    api_h = _get(obj, "api_client_healthy")
    proxy_h = _get(obj, "proxy_healthy")
    flags = [v for v in (api_h, proxy_h) if v is not None]
    if not flags:
        is_connected = _get(obj, "is_connected")
        return "healthy" if is_connected else "unknown"
    if all(flags):
        return "healthy"
    if any(flags):
        return "degraded"
    return "unhealthy"


@strawberry.type(description="UniFi Access application info (name + version + host).")
class AccessSystemInfo:
    """Mirrors ``AccessSystemInfoSerializer.serialize`` projection
    byte-for-byte."""

    name: str | None
    version: str | None
    hostname: str | None
    uptime: int | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "AccessSystemInfo":
        return cls(
            name=_string_from_value(_get(obj, "name") or _get(obj, "source")),
            version=_string_from_value(_get(obj, "version")),
            hostname=_string_from_value(_get(obj, "hostname") or _get(obj, "host")),
            uptime=_int_from_value(_get(obj, "uptime")),
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: v for k, v in out.items() if not k.startswith("_") and not callable(v)}


@strawberry.type(description="UniFi Access health probe summary.")
class AccessHealth:
    """Mirrors ``AccessHealthSerializer.serialize`` projection byte-for-byte."""

    status: str
    num_doors: int | None
    num_devices: int | None
    num_offline_devices: int | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "AccessHealth":
        return cls(
            status=_derive_health_status(obj),
            num_doors=_get(obj, "num_doors"),
            num_devices=_get(obj, "num_devices"),
            num_offline_devices=_get(obj, "num_offline_devices"),
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: v for k, v in out.items() if not k.startswith("_") and not callable(v)}
