"""Strawberry types for access/policies.

Phase 6 PR4 Task B migration target. The single read serializer
(``PolicySerializer``) maps to one Strawberry class:

- ``Policy`` — access_list_policies + access_get_policy

Tool-keyed only (the policy serializer never registered a resource
path). Mutation ack (``access_update_policy``) stays in
``serializers/access/policies.py`` — it flows through the manager's
preview path and produces a dict ack.

PolicyManager exposes door associations under varying field names
(``door_ids`` / ``resources``); ``from_manager_output`` normalizes
across both, mirroring the old serializer byte-for-byte.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


def _door_ids(obj: Any) -> list:
    door_ids = _get(obj, "door_ids")
    if isinstance(door_ids, list):
        return door_ids
    resources = _get(obj, "resources")
    if isinstance(resources, list):
        return [r.get("id") if isinstance(r, dict) else r for r in resources if r is not None]
    return []


def _is_enabled(obj: Any) -> bool:
    explicit = _get(obj, "enabled")
    if isinstance(explicit, bool):
        return explicit
    status = _get(obj, "status")
    if isinstance(status, str):
        return status.lower() in {"active", "enabled", "on"}
    return True


def _schedule_id(obj: Any) -> Any:
    schedule = _get(obj, "schedule")
    schedule_id = _get(obj, "schedule_id")
    if not schedule_id and isinstance(schedule, dict):
        schedule_id = schedule.get("id")
    return schedule_id


@strawberry.type(description="A UniFi Access policy (who-can-access-what binding).")
class Policy:
    """Mirrors ``PolicySerializer.serialize`` projection byte-for-byte."""

    id: strawberry.ID | None
    name: str | None
    schedule_id: str | None
    door_ids: list[str]
    user_group_ids: list[str]
    enabled: bool

    # Context for relationship edges — NOT in SDL, NOT in to_dict().
    _controller_id: strawberry.Private[str | None] = None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "schedule_id", "enabled"],
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "Policy":
        return cls(
            id=_get(obj, "id"),
            name=_get(obj, "name"),
            schedule_id=_schedule_id(obj),
            door_ids=_door_ids(obj),
            user_group_ids=_get(obj, "user_group_ids") or [],
            enabled=_is_enabled(obj),
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: v for k, v in out.items() if not k.startswith("_") and not callable(v)}
