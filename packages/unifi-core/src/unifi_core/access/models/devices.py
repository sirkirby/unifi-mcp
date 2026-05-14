"""Shared field model for Access devices (read-only).

Class name ``AccessDevice`` disambiguates from the Network layer's ``Device``
model. All fields are read-only: there is no update_device tool. The
``access_reboot_device`` action is handled separately in Task 11.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


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
    location: Optional[str] = Field(
        default=None, description="Physical location or associated door name", json_schema_extra={"mutable": False}
    )


MUTABLE_FIELDS = frozenset()
READ_ONLY_FIELDS = frozenset(AccessDevice.model_fields.keys())


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def from_controller(raw: Any) -> AccessDevice:
    """Build an AccessDevice from a manager dict or object."""
    return AccessDevice(
        id=_get(raw, "id"),
        name=_get(raw, "name"),
        type=_get(raw, "type"),
        is_online=_get(raw, "is_online"),
        firmware_version=_get(raw, "firmware_version"),
        location=_get(raw, "location"),
    )
