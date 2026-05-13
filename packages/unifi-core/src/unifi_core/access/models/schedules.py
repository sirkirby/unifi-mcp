"""Shared field model for Access schedules (read-only)."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class Schedule(BaseModel):
    """Canonical Access schedule model (read-only)."""

    id: Optional[str] = Field(default=None, description="Schedule UUID", json_schema_extra={"mutable": False})
    name: Optional[str] = Field(default=None, description="Schedule display name", json_schema_extra={"mutable": False})
    weekly_pattern: Optional[Any] = Field(default=None, description="Weekly time-block configuration (JSON)", json_schema_extra={"mutable": False})
    enabled: Optional[bool] = Field(default=None, description="Whether the schedule is active", json_schema_extra={"mutable": False})


MUTABLE_FIELDS = frozenset()
READ_ONLY_FIELDS = frozenset(Schedule.model_fields.keys())


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def from_controller(raw: Any) -> Schedule:
    """Build a Schedule from a manager dict or object."""
    return Schedule(
        id=_get(raw, "id"),
        name=_get(raw, "name"),
        weekly_pattern=_get(raw, "weekly_pattern"),
        enabled=_get(raw, "enabled"),
    )
