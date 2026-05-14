"""Shared field models for Access doors (read-only).

Three classes mirror the Strawberry types in
``unifi_api.graphql.types.access.doors``:

- ``Door``       — access_list_doors + access_get_door
- ``DoorGroup``  — access_list_door_groups
- ``DoorStatus`` — access_get_door_status

All fields are read-only (no update_door tool). Factory helpers
``door_from_controller``, ``door_group_from_controller``, and
``door_status_from_controller`` normalise the two slightly different
raw shapes the DoorManager may return (API-client path vs proxy path),
mirroring the Strawberry ``from_manager_output`` helpers byte-for-byte.
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Pydantic domain models
# ---------------------------------------------------------------------------


class Door(BaseModel):
    """Canonical Access door model (read-only)."""

    id: Optional[str] = Field(default=None, description="Door UUID", json_schema_extra={"mutable": False})
    name: Optional[str] = Field(default=None, description="Display name", json_schema_extra={"mutable": False})
    location: Optional[str] = Field(
        default=None, description="Location or location type", json_schema_extra={"mutable": False}
    )
    is_online: Optional[bool] = Field(
        default=None, description="Whether the door device is online", json_schema_extra={"mutable": False}
    )
    is_locked: Optional[bool] = Field(
        default=None, description="Derived lock state", json_schema_extra={"mutable": False}
    )
    lock_state: Optional[str] = Field(
        default=None, description="Raw lock state string", json_schema_extra={"mutable": False}
    )
    last_event: Optional[Any] = Field(
        default=None, description="Last event dict {name, timestamp} or None", json_schema_extra={"mutable": False}
    )


class DoorGroup(BaseModel):
    """Canonical Access door-group model (read-only)."""

    id: Optional[str] = Field(default=None, description="Door group UUID", json_schema_extra={"mutable": False})
    name: Optional[str] = Field(default=None, description="Display name", json_schema_extra={"mutable": False})
    door_ids: List[str] = Field(
        default_factory=list, description="IDs of doors in this group", json_schema_extra={"mutable": False}
    )
    location: Optional[str] = Field(
        default=None, description="Location or location type", json_schema_extra={"mutable": False}
    )


class DoorStatus(BaseModel):
    """Canonical Access per-door live status model (read-only)."""

    door_id: Optional[str] = Field(default=None, description="Door UUID", json_schema_extra={"mutable": False})
    name: Optional[str] = Field(default=None, description="Display name", json_schema_extra={"mutable": False})
    is_locked: Optional[bool] = Field(
        default=None, description="Derived lock state", json_schema_extra={"mutable": False}
    )
    lock_state: Optional[str] = Field(
        default=None, description="Raw lock state string", json_schema_extra={"mutable": False}
    )
    door_position_status: Optional[str] = Field(
        default=None, description="Door position (open/closed/etc.)", json_schema_extra={"mutable": False}
    )
    last_event_at: Optional[str] = Field(
        default=None, description="Timestamp of last event", json_schema_extra={"mutable": False}
    )
    last_event_type: Optional[str] = Field(
        default=None, description="Name/type of last event", json_schema_extra={"mutable": False}
    )


# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------

MUTABLE_FIELDS: frozenset[str] = frozenset()
READ_ONLY_FIELDS: frozenset[str] = (
    frozenset(Door.model_fields.keys())
    | frozenset(DoorGroup.model_fields.keys())
    | frozenset(DoorStatus.model_fields.keys())
)


# ---------------------------------------------------------------------------
# Internal helpers (mirror Strawberry module helpers exactly)
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _stringify_dt(value: Any) -> Optional[str]:
    """Coerce a datetime-ish value to ISO 8601 string for serialization."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:
            return None
    return str(value)


def _is_locked(obj: Any) -> Optional[bool]:
    """Derive lock state: explicit field first, else lock_relay_status == 'lock'."""
    explicit = _get(obj, "is_locked")
    if explicit is not None:
        return bool(explicit)
    relay = _get(obj, "lock_relay_status")
    if relay is None:
        return None
    return relay == "lock"


def _last_event(obj: Any) -> Any:
    """Normalise last_event sub-dict to {name, timestamp}."""
    raw = _get(obj, "last_event")
    if isinstance(raw, dict):
        return {
            "name": raw.get("name"),
            "timestamp": raw.get("timestamp") or raw.get("created_at"),
        }
    return raw


def _door_ids_from_groups(obj: Any) -> list:
    """Coalesce door IDs from door_ids OR resources list-of-dicts."""
    door_ids = _get(obj, "door_ids")
    if isinstance(door_ids, list):
        return door_ids
    resources = _get(obj, "resources")
    if isinstance(resources, list):
        return [r.get("id") if isinstance(r, dict) else r for r in resources if r is not None]
    return []


# ---------------------------------------------------------------------------
# Public factory helpers
# ---------------------------------------------------------------------------


def door_from_controller(raw: Any) -> Door:
    """Build a Door from a manager dict or object."""
    return Door(
        id=_get(raw, "id"),
        name=_get(raw, "name"),
        location=_get(raw, "location") or _get(raw, "location_type"),
        is_online=_get(raw, "is_online"),
        is_locked=_is_locked(raw),
        lock_state=_get(raw, "lock_state") or _get(raw, "lock_relay_status"),
        last_event=_last_event(raw),
    )


def door_group_from_controller(raw: Any) -> DoorGroup:
    """Build a DoorGroup from a manager dict or object."""
    return DoorGroup(
        id=_get(raw, "id"),
        name=_get(raw, "name"),
        door_ids=_door_ids_from_groups(raw),
        location=_get(raw, "location") or _get(raw, "location_type"),
    )


def door_status_from_controller(raw: Any) -> DoorStatus:
    """Build a DoorStatus from a manager dict or object."""
    last = _last_event(raw)
    last_ts = last.get("timestamp") if isinstance(last, dict) else None
    last_type = last.get("name") if isinstance(last, dict) else None
    return DoorStatus(
        door_id=_get(raw, "door_id") or _get(raw, "id"),
        name=_get(raw, "name"),
        is_locked=_is_locked(raw),
        lock_state=_get(raw, "lock_state") or _get(raw, "lock_relay_status"),
        door_position_status=_get(raw, "door_position_status"),
        last_event_at=_stringify_dt(last_ts),
        last_event_type=last_type,
    )
