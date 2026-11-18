"""Create and update for the project's own materials: wall types and attenuation-object types.

Both live in a project list (``wallTypes``, ``attenuationObjectTypes``) and are
written through their own route with ``create``, ``update`` and ``remove``
lists. An update sends the whole stored type with the requested fields
changed. A type is project-wide: the preview counts the shapes using it.
Removal is not built: the console answers 500 while a shape uses the type.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from pydantic import BaseModel

from unifi_core.innerspace.managers._layout import (
    Snapshot,
    WritePlan,
    WriteRequest,
    copy_of,
    matches,
    pick,
    state,
    usage_by_plan,
)

# Input field name to stored key.
_STORED = {"name": "name", "attenuation_db": "attenuation", "color": "color", "transparent": "transparent"}


@dataclass(frozen=True)
class TypeKind:
    path: str
    types_key: str  # the project list
    noun: str
    shape_type: str  # shapes that use the type
    reference: str  # their reference key
    shape_noun: str
    effect: str  # effects key for the usage count
    new_fields: Mapping[str, Any]  # stored defaults of a new type, after the given fields


def _stored_values(item: BaseModel) -> dict[str, Any]:
    return {_STORED[name]: value for name, value in item.model_dump().items() if name in _STORED and value is not None}


def _name_in_use(kind: TypeKind, snapshot: Snapshot, name: str, other_than: str | None = None) -> list[str]:
    taken = {
        str(row.get("name", "")).strip().casefold()
        for type_id, row in snapshot.types(kind.types_key).items()
        if type_id != other_than
    }
    return [f"Another {kind.noun} already has this name"] if name.casefold() in taken else []


def plan_type_create(kind: TypeKind, snapshot: Snapshot, *, item: BaseModel) -> WritePlan:
    project_id = snapshot.project_id
    values = _stored_values(item)

    def request(ids: list[str]) -> WriteRequest:
        row = {"id": ids[0], "projectId": project_id, **kind.new_fields, **values}
        wanted = pick(row, values)

        def expect(after: Snapshot) -> dict[str, bool | None]:
            return {row["id"]: state(after.types(kind.types_key).get(row["id"]), wanted, None)}

        body = {"create": [row], "update": [], "remove": []}
        return WriteRequest("POST", kind.path, body, expect, [row["id"]])

    preview = {"count": 1, "proposed": item.model_dump()}
    return WritePlan(
        preview=preview,
        request=request,
        new_ids=1,
        warnings=_name_in_use(kind, snapshot, item.name),  # type: ignore[attr-defined]
    )


def plan_type_update(kind: TypeKind, snapshot: Snapshot, *, item: BaseModel, operation: str) -> WritePlan:
    type_id: str = item.id  # type: ignore[attr-defined]
    stored = snapshot.require_type(kind.types_key, type_id, kind.noun, operation)
    changes = {_STORED[name]: value for name, value in item.changes().items()}  # type: ignore[attr-defined]
    diff = sorted(key for key, value in changes.items() if not matches(stored, {key: value}))
    new = {**copy_of(stored), **{key: changes[key] for key in diff}}
    by_stored = {stored_key: name for name, stored_key in _STORED.items()}
    usage = usage_by_plan(snapshot, kind.shape_type, kind.reference, type_id)
    warnings = []
    if diff and usage["total"]:
        noun = kind.shape_noun if usage["total"] == 1 else f"{kind.shape_noun}s"
        warnings.append(f"This type is project-wide: the change applies to {usage['total']} {noun}")
    if "name" in diff:
        warnings += _name_in_use(kind, snapshot, new["name"], other_than=type_id)

    def request(_: list[str]) -> WriteRequest:
        wanted, prior = pick(new, diff), pick(stored, diff)

        def expect(after: Snapshot) -> dict[str, bool | None]:
            return {type_id: state(after.types(kind.types_key).get(type_id), wanted, prior)}

        return WriteRequest("POST", kind.path, {"create": [], "update": [new], "remove": []}, expect)

    preview = {
        "id": type_id,
        "current": {by_stored[key]: stored.get(key) for key in diff},
        "proposed": {by_stored[key]: new[key] for key in diff},
    }
    return WritePlan(
        preview=preview, request=request if diff else None, effects={kind.effect: usage}, warnings=warnings
    )
