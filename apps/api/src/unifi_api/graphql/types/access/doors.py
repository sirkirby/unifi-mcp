"""Strawberry types for access/doors.

Phase 6 PR4 Task A migration target. Three read serializers in
``unifi_api.serializers.access.doors`` map to three Strawberry classes:

- ``Door``        — access_list_doors + access_get_door
- ``DoorGroup``   — access_list_door_groups
- ``DoorStatus``  — access_get_door_status (per-door nested status)

Each type's ``from_manager_output(raw)`` classmethod replaces the dict-
shaping logic that used to live in serializers/access/doors.py.
``to_dict()`` exposes the same dict contract the REST routes return today.

Mutation ack (``access_lock_door`` / ``access_unlock_door``) stays in the
serializer module — those tools dispatch via the manager's preview path,
not a typed read.

DoorManager populates two slightly different shapes (API-client path vs
proxy path); ``from_manager_output`` normalizes across both, mirroring the
old serializer byte-for-byte.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Annotated, Any

import strawberry
from strawberry.types import Info

if TYPE_CHECKING:
    from unifi_api.graphql.types.access.policies import Policy


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


def _is_locked(obj: Any) -> bool | None:
    explicit = _get(obj, "is_locked")
    if explicit is not None:
        return bool(explicit)
    relay = _get(obj, "lock_relay_status")
    if relay is None:
        return None
    return relay == "lock"


def _last_event(obj: Any) -> Any:
    raw = _get(obj, "last_event")
    if isinstance(raw, dict):
        return {
            "name": raw.get("name"),
            "timestamp": raw.get("timestamp") or raw.get("created_at"),
        }
    return raw


def _door_ids_from_groups(obj: Any) -> list:
    """Door groups may carry resources/door_ids in either field name."""
    door_ids = _get(obj, "door_ids")
    if isinstance(door_ids, list):
        return door_ids
    resources = _get(obj, "resources")
    if isinstance(resources, list):
        return [r.get("id") if isinstance(r, dict) else r for r in resources if r is not None]
    return []


@strawberry.type(description="A UniFi Access door (list + detail shape).")
class Door:
    """Mirrors ``DoorSerializer.serialize`` projection byte-for-byte."""

    id: strawberry.ID | None
    name: str | None
    location: str | None
    is_online: bool | None
    is_locked: bool | None
    lock_state: str | None
    last_event: strawberry.scalars.JSON | None  # type: ignore[name-defined]

    # Context for relationship edges — NOT in SDL, NOT in to_dict().
    _controller_id: strawberry.Private[str | None] = None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "location", "is_online", "is_locked"],
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "Door":
        return cls(
            id=_get(obj, "id"),
            name=_get(obj, "name"),
            location=_get(obj, "location") or _get(obj, "location_type"),
            is_online=_get(obj, "is_online"),
            is_locked=_is_locked(obj),
            lock_state=_get(obj, "lock_state") or _get(obj, "lock_relay_status"),
            last_event=_last_event(obj),
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: v for k, v in out.items() if not k.startswith("_") and not callable(v)}

    @strawberry.field(description="Policies assigned to this door.")
    async def policy_assignments(
        self,
        info: Info,
    ) -> list[Annotated["Policy", strawberry.lazy("unifi_api.graphql.types.access.policies")]]:
        from unifi_api.graphql.resolvers.access import _fetch_policies
        from unifi_api.graphql.types.access.policies import Policy

        if not self._controller_id or not self.id:
            return []
        all_policies = await _fetch_policies(info.context, self._controller_id)
        out: list[Policy] = []
        for p in all_policies:
            door_ids = p.get("door_ids") if isinstance(p, dict) else getattr(p, "door_ids", None)
            if not isinstance(door_ids, list):
                resources = p.get("resources") if isinstance(p, dict) else getattr(p, "resources", None)
                if isinstance(resources, list):
                    door_ids = [r.get("id") if isinstance(r, dict) else r for r in resources if r is not None]
            if door_ids and self.id in door_ids:
                inst = Policy.from_manager_output(p)
                inst._controller_id = self._controller_id
                out.append(inst)
        return out


@strawberry.type(description="A UniFi Access door group (list of doors).")
class DoorGroup:
    """Mirrors ``DoorGroupSerializer.serialize`` projection byte-for-byte."""

    id: strawberry.ID | None
    name: str | None
    door_ids: list[str]
    location: str | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "location"],
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "DoorGroup":
        return cls(
            id=_get(obj, "id"),
            name=_get(obj, "name"),
            door_ids=_door_ids_from_groups(obj),
            location=_get(obj, "location") or _get(obj, "location_type"),
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: v for k, v in out.items() if not k.startswith("_") and not callable(v)}


@strawberry.type(description="Per-door live status (lock state + last event).")
class DoorStatus:
    """Mirrors ``DoorStatusSerializer.serialize`` projection byte-for-byte.

    DETAIL kind. ``last_event_at`` / ``last_event_type`` are flattened from
    the ``last_event`` sub-dict (when present).
    """

    door_id: strawberry.ID | None
    name: str | None
    is_locked: bool | None
    lock_state: str | None
    door_position_status: str | None
    last_event_at: str | None
    last_event_type: str | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "door_id",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "DoorStatus":
        last = _last_event(obj)
        last_ts = last.get("timestamp") if isinstance(last, dict) else None
        last_type = last.get("name") if isinstance(last, dict) else None
        return cls(
            door_id=_get(obj, "door_id") or _get(obj, "id"),
            name=_get(obj, "name"),
            is_locked=_is_locked(obj),
            lock_state=_get(obj, "lock_state") or _get(obj, "lock_relay_status"),
            door_position_status=_get(obj, "door_position_status"),
            last_event_at=last_ts,
            last_event_type=last_type,
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: v for k, v in out.items() if not k.startswith("_") and not callable(v)}
