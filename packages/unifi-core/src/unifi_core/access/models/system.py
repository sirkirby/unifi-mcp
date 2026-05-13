"""Shared field models for Access system info and health (read-only).

Two classes:
- ``AccessSystemInfo`` — controller application info (name, version, host).
- ``AccessHealth`` — health probe summary (status + device counts).

All fields are read-only; there are no system mutation tools. The
``status`` field on ``AccessHealth`` is derived from health-flag keys
(``api_client_healthy``, ``proxy_healthy``) when an explicit ``status``
string is absent — mirroring the Strawberry type's
``_derive_health_status`` logic.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class AccessSystemInfo(BaseModel):
    """Canonical Access system info model (read-only)."""

    name: Optional[str] = Field(default=None, description="Controller application name", json_schema_extra={"mutable": False})
    version: Optional[str] = Field(default=None, description="Firmware / application version string", json_schema_extra={"mutable": False})
    hostname: Optional[str] = Field(default=None, description="Controller hostname or IP", json_schema_extra={"mutable": False})
    uptime: Optional[int] = Field(default=None, description="Uptime in seconds", json_schema_extra={"mutable": False})


class AccessHealth(BaseModel):
    """Canonical Access system health model (read-only)."""

    status: Optional[str] = Field(default="unknown", description="Derived health status (healthy, degraded, unhealthy, unknown)", json_schema_extra={"mutable": False})
    num_doors: Optional[int] = Field(default=None, description="Number of configured doors", json_schema_extra={"mutable": False})
    num_devices: Optional[int] = Field(default=None, description="Number of connected devices", json_schema_extra={"mutable": False})
    num_offline_devices: Optional[int] = Field(default=None, description="Number of offline devices", json_schema_extra={"mutable": False})


MUTABLE_FIELDS: frozenset[str] = frozenset()
READ_ONLY_FIELDS: frozenset[str] = frozenset(AccessSystemInfo.model_fields.keys()) | frozenset(AccessHealth.model_fields.keys())


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _derive_health_status(obj: Any) -> str:
    """Derive a health status string from the raw controller output.

    Mirrors the Strawberry ``_derive_health_status`` helper exactly:
    1. Use explicit ``status`` string when present.
    2. Fall back to ``api_client_healthy`` / ``proxy_healthy`` flags.
    3. Fall back to ``is_connected``.
    4. Default to ``"unknown"``.
    """
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


def system_info_from_controller(raw: Any) -> AccessSystemInfo:
    """Build an AccessSystemInfo from a manager dict or object."""
    return AccessSystemInfo(
        name=_get(raw, "name") or _get(raw, "source"),
        version=_get(raw, "version"),
        hostname=_get(raw, "hostname") or _get(raw, "host"),
        uptime=_get(raw, "uptime"),
    )


def health_from_controller(raw: Any) -> AccessHealth:
    """Build an AccessHealth from a manager dict or object."""
    return AccessHealth(
        status=_derive_health_status(raw),
        num_doors=_get(raw, "num_doors"),
        num_devices=_get(raw, "num_devices"),
        num_offline_devices=_get(raw, "num_offline_devices"),
    )
