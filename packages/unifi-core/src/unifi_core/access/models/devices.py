"""Shared field model for Access devices (read-only).

Class name ``AccessDevice`` disambiguates from the Network layer's ``Device``
model. All fields are read-only: there is no update_device tool. The
``access_reboot_device`` action is handled separately in Task 11.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class AccessLocation(BaseModel):
    """The location object UniFi Access associates with a device.

    UNVR's Access API returns ``location`` as a structured object (door / floor /
    building reference), not a bare string. Fields are read-only.
    """

    unique_id: Optional[str] = Field(default=None, description="Location UUID", json_schema_extra={"mutable": False})
    name: Optional[str] = Field(default=None, description="Location display name", json_schema_extra={"mutable": False})
    up_id: Optional[str] = Field(default=None, description="Parent location UUID", json_schema_extra={"mutable": False})
    location_type: Optional[str] = Field(
        default=None,
        description="Location category (door, floor, building, site)",
        json_schema_extra={"mutable": False},
    )
    full_name: Optional[str] = Field(
        default=None,
        description="Fully-qualified location path (e.g. 'Site - Floor - Door')",
        json_schema_extra={"mutable": False},
    )
    level: Optional[int] = Field(
        default=None, description="Depth in the location hierarchy", json_schema_extra={"mutable": False}
    )


class AccessDevice(BaseModel):
    """Canonical Access device model (read-only)."""

    id: Optional[str] = Field(default=None, description="Device UUID", json_schema_extra={"mutable": False})
    name: Optional[str] = Field(default=None, description="Device display name", json_schema_extra={"mutable": False})
    type: Optional[str] = Field(
        default=None, description="Device type (hub, reader, relay, intercom)", json_schema_extra={"mutable": False}
    )
    is_online: Optional[bool] = Field(
        default=None, description="Whether the device is currently connected", json_schema_extra={"mutable": False}
    )
    firmware_version: Optional[str] = Field(
        default=None, description="Installed firmware version string", json_schema_extra={"mutable": False}
    )
    location: Optional[AccessLocation] = Field(
        default=None,
        description="Location reference (door/floor/building) this device is mounted at",
        json_schema_extra={"mutable": False},
    )


MUTABLE_FIELDS = frozenset()
READ_ONLY_FIELDS = frozenset(AccessDevice.model_fields.keys())


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _coerce_location(raw: Any) -> Optional[AccessLocation]:
    """Build an AccessLocation from a dict, an existing AccessLocation, or a
    bare string. Returns None for None or empty values.

    Bare strings (the pre-fix shape some mocks still emit) are mapped to
    ``AccessLocation(name=<string>)`` so callers continue to surface a
    human-readable label.
    """
    if raw is None:
        return None
    if isinstance(raw, AccessLocation):
        return raw
    if isinstance(raw, str):
        stripped = raw.strip()
        return AccessLocation(name=stripped) if stripped else None
    if isinstance(raw, dict):
        return AccessLocation(
            unique_id=raw.get("unique_id"),
            name=raw.get("name"),
            up_id=raw.get("up_id"),
            location_type=raw.get("location_type"),
            full_name=raw.get("full_name"),
            level=raw.get("level"),
        )
    return None


def from_controller(raw: Any) -> AccessDevice:
    """Build an AccessDevice from a manager dict or object."""
    return AccessDevice(
        id=_get(raw, "id"),
        name=_get(raw, "name"),
        type=_get(raw, "type"),
        is_online=_get(raw, "is_online"),
        firmware_version=_get(raw, "firmware_version"),
        location=_coerce_location(_get(raw, "location")),
    )
