"""Create, update and remove for the plan shapes drawn as points: walls and attenuation objects.

Both are stored with a ``position`` list in plan units, a built-in ``variant``
or ``custom`` with a project type id, and are written through ``shape/change``
in ``mode: "2D"``. Updates send the whole stored object with the requested
fields changed; removes send the stored objects. A custom shape changed to a
built-in variant is sent without its type id, which the console stores as
``null``; the preview lists that field under ``cleared``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from pydantic import BaseModel

from unifi_core.innerspace.frames import Coordinates
from unifi_core.innerspace.managers._layout import (
    PREVIEW_ITEMS,
    Display,
    Point,
    Snapshot,
    WritePlan,
    WriteRequest,
    bounding_box,
    copy_of,
    pick,
    plan_points,
    points_close,
    shape_change_body,
    state,
)
from unifi_core.innerspace.managers.connection_manager import SHAPE_CHANGE_PATH
from unifi_core.innerspace.units import Unit

ALREADY_REMOVED = "None of the objects named is in the project (already removed, or never existed), so nothing was sent"


@dataclass(frozen=True)
class ShapeKind:
    shape_type: str  # the stored ``type``
    noun: str  # for messages
    type_key: str  # stored type reference, e.g. ``wallTypeId``
    types_key: str  # project type list, e.g. ``wallTypes``
    type_noun: str
    type_field: str  # input name of the type reference, e.g. ``wall_type_id``
    points: Callable[[BaseModel], Sequence[Point] | None]  # an input item's points, None when not given
    show: Callable[[Sequence[tuple[float | None, float | None]]], dict[str, Any]]  # points as preview fields

    @property
    def compared(self) -> tuple[str, ...]:
        return ("type", "planId", "position", "variant", self.type_key)


def _fields(kind: ShapeKind, shape: dict[str, Any], display: Display) -> dict[str, Any]:
    return {
        **kind.show(display.position(shape.get("position"))),
        "variant": shape.get("variant"),
        kind.type_field: shape.get(kind.type_key),
    }


def _check_type(kind: ShapeKind, snapshot: Snapshot, item: BaseModel, operation: str) -> str | None:
    type_id = getattr(item, kind.type_field)
    if type_id is not None:
        snapshot.require_type(kind.types_key, type_id, kind.type_noun, operation)
    return type_id


def plan_create(
    kind: ShapeKind,
    snapshot: Snapshot,
    *,
    plan_id: str,
    items: Sequence[BaseModel],
    unit: Unit,
    coordinates: Coordinates,
    operation: str,
) -> WritePlan:
    plan = snapshot.plan(plan_id, operation)
    frame = snapshot.frame(plan_id)
    project_id = snapshot.project_id
    prepared = []
    given: list[tuple[float, float]] = []
    for item in items:
        points = list(kind.points(item) or ())
        type_id = _check_type(kind, snapshot, item, operation)
        position = plan_points(points, frame=frame, unit=unit, coordinates=coordinates, operation=operation)
        prepared.append((position, item.variant, type_id))  # type: ignore[attr-defined]
        given.extend(points)

    def request(ids: list[str]) -> WriteRequest:
        shapes = []
        for shape_id, (position, variant, type_id) in zip(ids, prepared):
            shape = {
                "id": shape_id,
                "type": kind.shape_type,
                "projectId": project_id,
                "planId": plan_id,
                "position": position,
                "variant": variant,
                "status": 0,
            }
            if type_id is not None:
                shape[kind.type_key] = type_id
            shapes.append(shape)
        wanted = {s["id"]: pick(s, kind.compared) for s in shapes}

        def expect(after: Snapshot) -> dict[str, bool | None]:
            return {shape_id: state(after.shapes.get(shape_id), fields, None) for shape_id, fields in wanted.items()}

        return WriteRequest("POST", SHAPE_CHANGE_PATH, shape_change_body(create=shapes), expect, list(wanted))

    preview = {
        "plan_id": plan_id,
        "plan_title": plan.get("title"),
        "unit": unit,
        "coordinates": coordinates,
        "count": len(items),
        "bounding_box": bounding_box(given),
        "items": [{"index": index, "proposed": item.model_dump()} for index, item in enumerate(items[:PREVIEW_ITEMS])],
    }
    return WritePlan(preview=preview, request=request, new_ids=len(items))


def plan_update(
    kind: ShapeKind,
    snapshot: Snapshot,
    *,
    plan_id: str,
    items: Sequence[BaseModel],
    unit: Unit,
    coordinates: Coordinates,
    operation: str,
) -> WritePlan:
    plan = snapshot.plan(plan_id, operation)
    stored = snapshot.stored([item.id for item in items], kind.shape_type, plan_id, kind.noun, operation)  # type: ignore[attr-defined]
    display = Display(snapshot.geometry(plan_id), unit, coordinates)
    frame = None
    changed: list[tuple[dict[str, Any], dict[str, Any]]] = []
    shown = []
    proposed_points: list[tuple[float | None, float | None]] = []
    for item, shape in zip(items, stored):
        new = copy_of(shape)
        cleared = []
        points = kind.points(item)
        moved = False
        if points is not None:
            frame = frame or snapshot.frame(plan_id)
            position = plan_points(points, frame=frame, unit=unit, coordinates=coordinates, operation=operation)
            moved = not points_close(shape.get("position"), position)
            if moved:
                new["position"] = position
            proposed_points.extend(points)
        variant = item.variant  # type: ignore[attr-defined]
        if variant is not None:
            type_id = _check_type(kind, snapshot, item, operation)
            new["variant"] = variant
            if type_id is not None:
                new[kind.type_key] = type_id
            elif shape.get(kind.type_key) is not None:
                # Sent without the key, the console stores null (recorded live on 1.4.3).
                del new[kind.type_key]
                cleared.append(kind.type_field)
        if new == shape:
            continue
        changed.append((shape, new))
        before, after = _fields(kind, shape, display), _fields(kind, new, display)
        if moved:
            after.update(kind.show(list(points or ())))
        diff = sorted(key for key in after if after[key] != before[key])
        shown.append(
            {
                "id": shape["id"],
                "current": {key: before[key] for key in diff},
                "proposed": {key: after[key] for key in diff if key not in cleared},
                "cleared": cleared,
            }
        )

    def request(ids: list[str]) -> WriteRequest:
        wanted = {new["id"]: (pick(new, kind.compared), pick(old, kind.compared)) for old, new in changed}

        def expect(after: Snapshot) -> dict[str, bool | None]:
            return {key: state(after.shapes.get(key), new, old) for key, (new, old) in wanted.items()}

        body = shape_change_body(update=[new for _, new in changed])
        return WriteRequest("POST", SHAPE_CHANGE_PATH, body, expect)

    preview = {
        "plan_id": plan_id,
        "plan_title": plan.get("title"),
        "unit": unit,
        "coordinates": coordinates,
        "count": len(changed),
        "unchanged": len(items) - len(changed),
        "bounding_box": bounding_box(proposed_points),
        "items": shown[:PREVIEW_ITEMS],
    }
    return WritePlan(preview=preview, request=request if changed else None)


def _on_plan(snapshot: Snapshot, plan_id: str) -> set[str]:
    return {shape_id for shape_id, shape in snapshot.shapes.items() if shape.get("planId") == plan_id}


def plan_remove(kind: ShapeKind, snapshot: Snapshot, *, plan_id: str, ids: Sequence[str], operation: str) -> WritePlan:
    """Remove stored shapes. When none of ``ids`` is anywhere in the project the call is a no-op (a retry).

    The read-back counts a shape as removed only when its absence is plausible: the plan is still there and
    either other shapes of the plan are, or the plan lost exactly the shapes removed. An empty or cut-short
    read-back is unknown, not applied.
    """
    plan = snapshot.plan(plan_id, operation)
    display = Display(snapshot.geometry(plan_id), snapshot.unit, "frame")
    preview: dict[str, Any] = {"plan_id": plan_id, "plan_title": plan.get("title"), "unit": display.unit}
    if not any(shape_id in snapshot.shapes for shape_id in ids):
        preview.update(count=0, bounding_box=None, items=[])
        return WritePlan(preview=preview, request=None, warnings=[ALREADY_REMOVED], none_found=True)
    stored = snapshot.stored(ids, kind.shape_type, plan_id, kind.noun, operation)
    current = [_fields(kind, shape, display) for shape in stored]
    removing = set(ids)
    before = _on_plan(snapshot, plan_id)

    def request(_: list[str]) -> WriteRequest:
        def expect(after: Snapshot) -> dict[str, bool | None]:
            remaining = _on_plan(after, plan_id)
            plausible = plan_id in after.plans and (
                bool(remaining - removing) or len(before) - len(remaining) == len(removing)
            )
            gone: bool | None = True if plausible else None
            return {shape_id: False if shape_id in after.shapes else gone for shape_id in ids}

        return WriteRequest("POST", SHAPE_CHANGE_PATH, shape_change_body(remove=stored), expect)

    preview.update(
        count=len(stored),
        bounding_box=bounding_box(p for shape in stored for p in display.position(shape.get("position"))),
        items=[{"id": shape["id"], "current": fields} for shape, fields in zip(stored, current)][:PREVIEW_ITEMS],
    )
    return WritePlan(preview=preview, request=request)
