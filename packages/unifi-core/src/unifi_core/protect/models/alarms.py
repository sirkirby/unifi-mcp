"""Shared field models for Protect alarms (read-only).

``protect_alarm_arm`` and ``protect_alarm_disarm`` are action tools; their
input models live in ``_actions.py`` (Task 11). The three classes below
cover the read shapes returned by ``protect_alarm_get_status`` and
``protect_alarm_list_profiles``.
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class AlarmStatus(BaseModel):
    """Canonical Protect alarm arm-state snapshot (read-only)."""

    armed: Optional[bool] = Field(
        default=None, description="Whether the alarm system is currently armed", json_schema_extra={"mutable": False}
    )
    status: Optional[str] = Field(
        default=None, description="Raw status string from the controller", json_schema_extra={"mutable": False}
    )
    active_profile_id: Optional[str] = Field(
        default=None, description="UUID of the active arm profile", json_schema_extra={"mutable": False}
    )
    active_profile_name: Optional[str] = Field(
        default=None, description="Display name of the active arm profile", json_schema_extra={"mutable": False}
    )
    armed_at: Optional[str] = Field(
        default=None, description="ISO timestamp when the system was armed", json_schema_extra={"mutable": False}
    )
    will_be_armed_at: Optional[str] = Field(
        default=None,
        description="ISO timestamp when the system will become armed (activation delay)",
        json_schema_extra={"mutable": False},
    )
    breach_detected_at: Optional[str] = Field(
        default=None,
        description="ISO timestamp of the most recent breach detection",
        json_schema_extra={"mutable": False},
    )
    breach_event_count: Optional[int] = Field(
        default=None, description="Number of breach events since last arm", json_schema_extra={"mutable": False}
    )
    profile_count: Optional[int] = Field(
        default=None, description="Total number of configured arm profiles", json_schema_extra={"mutable": False}
    )


class AlarmProfile(BaseModel):
    """Canonical Protect alarm profile row (read-only)."""

    id: Optional[str] = Field(default=None, description="Alarm profile UUID", json_schema_extra={"mutable": False})
    name: Optional[str] = Field(
        default=None, description="Alarm profile display name", json_schema_extra={"mutable": False}
    )
    record_everything: Optional[bool] = Field(
        default=None,
        description="Whether this profile records all cameras continuously",
        json_schema_extra={"mutable": False},
    )
    activation_delay_ms: Optional[int] = Field(
        default=None,
        description="Delay in milliseconds before the alarm activates after arming",
        json_schema_extra={"mutable": False},
    )
    schedule_count: Optional[int] = Field(
        default=None,
        description="Number of schedules associated with this profile",
        json_schema_extra={"mutable": False},
    )
    automation_count: Optional[int] = Field(
        default=None,
        description="Number of automations associated with this profile",
        json_schema_extra={"mutable": False},
    )


class AlarmProfileList(BaseModel):
    """Wrapper shape returned by ``protect_alarm_list_profiles`` (read-only)."""

    profiles: Optional[List[Any]] = Field(
        default=None, description="List of alarm profile dicts", json_schema_extra={"mutable": False}
    )
    count: Optional[int] = Field(
        default=None, description="Number of profiles in the list", json_schema_extra={"mutable": False}
    )


MUTABLE_FIELDS = frozenset()
READ_ONLY_FIELDS = (
    frozenset(AlarmStatus.model_fields.keys())
    | frozenset(AlarmProfile.model_fields.keys())
    | frozenset(AlarmProfileList.model_fields.keys())
)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _stringify_dt(value: Any) -> Optional[str]:
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


def status_from_controller(raw: Any) -> AlarmStatus:
    """Build an AlarmStatus from a manager dict or object."""
    return AlarmStatus(
        armed=_get(raw, "armed"),
        status=_get(raw, "status"),
        active_profile_id=_get(raw, "active_profile_id"),
        active_profile_name=_get(raw, "active_profile_name"),
        armed_at=_stringify_dt(_get(raw, "armed_at")),
        will_be_armed_at=_stringify_dt(_get(raw, "will_be_armed_at")),
        breach_detected_at=_stringify_dt(_get(raw, "breach_detected_at")),
        breach_event_count=_get(raw, "breach_event_count"),
        profile_count=_get(raw, "profile_count"),
    )


def profile_from_controller(raw: Any) -> AlarmProfile:
    """Build an AlarmProfile from a manager dict or object."""
    return AlarmProfile(
        id=_get(raw, "id"),
        name=_get(raw, "name"),
        record_everything=_get(raw, "record_everything"),
        activation_delay_ms=_get(raw, "activation_delay_ms"),
        schedule_count=_get(raw, "schedule_count"),
        automation_count=_get(raw, "automation_count"),
    )


def profile_list_from_controller(raw: Any) -> AlarmProfileList:
    """Build an AlarmProfileList from a manager dict or object.

    Accepts:
    - a dict with ``profiles`` (list) and ``count`` keys (wrapper shape)
    - anything else: ``profiles`` coalesces to None
    """
    profiles = _get(raw, "profiles")
    if not isinstance(profiles, list):
        profiles = None
    return AlarmProfileList(
        profiles=profiles,
        count=_get(raw, "count"),
    )
