"""Strawberry types for network/client_groups + usergroups.

Phase 6 PR2 Task 24 migration target. Two read shapes that used to live in
``unifi_api.serializers.network.client_groups``:

- ``ClientGroup`` — list_client_groups + get_client_group_details
                    (V2 ``/network-members-group`` payloads from
                    ``ClientGroupManager`` for OON/firewall membership grouping).
- ``UserGroup``   — list_usergroups + get_usergroup_details
                    (V1 ``/rest/usergroup`` payloads from ``UsergroupManager``
                    for QoS bandwidth limits).

Both expose the same useful list/detail fields (``_id``, ``name``,
``qos_rate_max_down``, ``qos_rate_max_up``) so we render them with the same
shape. Two distinct types are kept so the type registry tool-keyed lookup
can resolve each tool independently and so per-resource resolvers can
attach different relationship edges in Task 25.

The mutation ack serializer (``ClientGroupMutationAckSerializer``) stays in the
original module for create/update/delete dispatch across both manager kinds.

Each type's ``from_manager_output(raw)`` classmethod replaces the dict-shaping
logic that used to live in serializers/network/client_groups.py.
``to_dict()`` exposes the same dict contract the REST routes return today.
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


@strawberry.type(description="A network member client group (V2 /network-members-group entry).")
class ClientGroup:
    id: strawberry.ID | None
    name: str | None
    qos_rate_max_down: int | None
    qos_rate_max_up: int | None
    members: list[str]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "qos_rate_max_down", "qos_rate_max_up"],
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "ClientGroup":
        members = _get(obj, "members") or []
        if not isinstance(members, list):
            members = []
        return cls(
            id=_get(obj, "_id") or _get(obj, "id"),
            name=_get(obj, "name"),
            qos_rate_max_down=_get(obj, "qos_rate_max_down"),
            qos_rate_max_up=_get(obj, "qos_rate_max_up"),
            members=list(members),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@strawberry.type(description="A QoS user group (V1 /rest/usergroup entry).")
class UserGroup:
    id: strawberry.ID | None
    name: str | None
    qos_rate_max_down: int | None
    qos_rate_max_up: int | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "qos_rate_max_down", "qos_rate_max_up"],
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "UserGroup":
        return cls(
            id=_get(obj, "_id") or _get(obj, "id"),
            name=_get(obj, "name"),
            qos_rate_max_down=_get(obj, "qos_rate_max_down"),
            qos_rate_max_up=_get(obj, "qos_rate_max_up"),
        )

    def to_dict(self) -> dict:
        return asdict(self)
