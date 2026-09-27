"""Typed site-wide mDNS service settings.

Network membership is controller-owned and intentionally read-only here.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError, field_validator

ADDRESS_PATTERN = re.compile(r"^_[a-zA-Z0-9._-]+\._(tcp|udp)(\.local)?$")
MUTABLE_FIELDS = frozenset({"mode", "predefined_services", "custom_services"})


class PredefinedService(BaseModel):
    """Tolerant projection of a controller service entry."""

    code: str | None = None


class CustomService(BaseModel):
    """Older controllers may omit either field or add new nested keys."""

    name: str | None = None
    address: str | None = None


class _WritePredefinedService(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    code: StrictStr

    @field_validator("code")
    @classmethod
    def nonempty_code(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("code must not be empty")
        return value


class _WriteCustomService(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: StrictStr
    address: StrictStr

    @field_validator("address")
    @classmethod
    def valid_address(cls, value: str) -> str:
        if not ADDRESS_PATTERN.fullmatch(value):
            raise ValueError("invalid address")
        return value


class MdnsSettings(BaseModel):
    """Public read view. Unknown controller mode values remain visible."""

    mode: str | None = None
    predefined_services: list[PredefinedService] = Field(default_factory=list)
    custom_services: list[CustomService] = Field(default_factory=list)
    id: str | None = Field(default=None, json_schema_extra={"mutable": False})
    site_id: str | None = Field(default=None, json_schema_extra={"mutable": False})
    enabled_for: str | None = Field(default=None, json_schema_extra={"mutable": False})
    enabled_for_network_ids: list[str] = Field(default_factory=list, json_schema_extra={"mutable": False})


class _MdnsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: StrictStr | None = None
    predefined_services: list[_WritePredefinedService] | None = None
    custom_services: list[_WriteCustomService] | None = None

    @field_validator("mode")
    @classmethod
    def valid_mode(cls, value: str | None) -> str | None:
        if value not in (None, "all", "auto", "custom"):
            raise ValueError("invalid mode")
        return value


def mdns_from_controller(raw: dict[str, Any]) -> MdnsSettings:
    """Project known fields, without leaking unrelated controller settings."""
    return MdnsSettings.model_validate(
        {
            "id": raw.get("_id", raw.get("id")),
            "site_id": raw.get("site_id", raw.get("site")),
            "mode": raw.get("mode"),
            "predefined_services": raw.get("predefined_services") or [],
            "custom_services": raw.get("custom_services") or [],
            "enabled_for": raw.get("enabled_for"),
            "enabled_for_network_ids": raw.get("enabled_for_network_ids") or [],
        }
    )


def validate_mdns_service_selection(settings: dict[str, Any]) -> None:
    """Validate the known mode/list constraints, including partial requests.

    Network 10.6.106 rejects ALL with services and CUSTOM without services.
    A partial CUSTOM request needs the stored lists before emptiness is known.
    """
    service_keys = ("predefined_services", "custom_services")
    has_services = any(settings.get(key) for key in service_keys)
    if settings.get("mode") == "all" and has_services:
        raise ValueError("mDNS mode 'all' requires empty predefined_services and custom_services lists.")
    if settings.get("mode") == "custom" and all(key in settings for key in service_keys) and not has_services:
        raise ValueError("mDNS mode 'custom' requires at least one predefined or custom service.")


def mdns_to_controller_update(fields: dict[str, Any]) -> dict[str, Any]:
    """Validate an exact partial update; return only supplied mutable keys.

    Errors include field names only, never rejected values or controller text.
    """
    unknown = set(fields) - MUTABLE_FIELDS
    if unknown:
        raise ValueError(f"Invalid mDNS field: {', '.join(sorted(unknown))}")
    if not fields:
        raise ValueError("No mDNS fields provided")
    try:
        parsed = _MdnsUpdate.model_validate(fields)
    except ValidationError as exc:
        names = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]})
        raise ValueError(f"Invalid mDNS field: {', '.join(names)}") from None
    if any(value is None for value in fields.values()):
        raise ValueError("mDNS fields cannot be null")
    updates = parsed.model_dump(exclude_unset=True)
    validate_mdns_service_selection(updates)
    return updates
