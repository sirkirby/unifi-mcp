"""Building blocks shared by the InnerSpace layout write managers.

Each operation is one ``build`` function from a fresh :class:`Snapshot` to a
:class:`WritePlan`. :func:`preview_write` runs it on a plain read and returns
the preview; :func:`apply_write` runs it again under the write lock on a fresh
read, so a shape that is gone, changed type or moved to another plan since the
preview is refused before anything is sent (other fields are taken from that
fresh read), then makes the ids, sends the one request and lets the read-back
decide. A plan without a request is a no-op: nothing is sent.

Previews carry no ids for new objects; those are made in :func:`apply_write`.
Read-backs compare positions in plan units within :data:`POSITION_TOLERANCE`.
"""

from __future__ import annotations

import math
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from pydantic import BaseModel

from unifi_core.exceptions import UniFiMalformedResponseError, UniFiNotFoundError
from unifi_core.innerspace.frames import Coordinates, PlanFrame, from_plan_point, to_plan_point
from unifi_core.innerspace.managers._writes import (
    InnerSpaceWriteRefusedError,
    ensure_writable,
    locked_write,
    read_internal_project,
    send_write,
    write_ids,
)
from unifi_core.innerspace.managers.connection_manager import InnerSpaceConnectionManager
from unifi_core.innerspace.models._coerce import as_dict, number, text
from unifi_core.innerspace.models.floor_plans import PlanGeometry, plan_geometry_from_api
from unifi_core.innerspace.units import Unit, parse_unit
from unifi_core.write_verification import WriteVerificationResult, noop_write

# Plan units (image pixels) a read-back position may differ from the one sent and still count as in place.
POSITION_TOLERANCE = 0.01
# Items listed in a preview; the counts cover all of them.
PREVIEW_ITEMS = 5

Point = tuple[float, float]
Expect = Callable[["Snapshot"], Mapping[str, "bool | None"]]


@dataclass
class WriteRequest:
    method: str
    path: str
    body: Any
    expect: Expect
    created_ids: list[str] = field(default_factory=list)


@dataclass
class WritePlan:
    """What one call would change: the preview, and the request to send (``None`` for a no-op)."""

    preview: dict[str, Any]
    request: Callable[[list[str]], WriteRequest] | None
    new_ids: int = 0
    effects: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    already_applied: bool = False  # a no-op because an identical earlier call is in place
    none_found: bool = False  # a remove no-op: none of the named objects is in the project


class Snapshot:
    """One fresh read of the stored project, with the floor-plan rows that give each plan's geometry."""

    def __init__(self, data: dict[str, Any], rows: Iterable[dict[str, Any]] = ()) -> None:
        self.data = data
        self.rows = {row["id"]: row for row in rows if isinstance(row.get("id"), str)}
        self.shapes = {s["id"]: s for s in data["shapes"] if isinstance(s, dict) and isinstance(s.get("id"), str)}
        self.plans = {p["id"]: p for p in data["plans"] if isinstance(p, dict) and isinstance(p.get("id"), str)}

    @property
    def project_id(self) -> str:
        project_id = text(as_dict(self.data.get("project")).get("id"))
        if project_id is None:
            raise UniFiMalformedResponseError("InnerSpace project response has no project id")
        return project_id

    @property
    def unit(self) -> Unit:
        return parse_unit(as_dict(self.data.get("project")).get("unit"))

    def plan(self, plan_id: str, operation: str) -> dict[str, Any]:
        plan = self.plans.get(plan_id)
        if plan is None:
            raise UniFiNotFoundError("floor plan", "InnerSpace", f"{operation}: no such floor plan")
        return plan

    def geometry(self, plan_id: str) -> PlanGeometry:
        return plan_geometry_from_api(self.rows.get(plan_id))

    def frame(self, plan_id: str) -> PlanFrame:
        image_map = next(iter(self.on_plan(plan_id, "map")), None)
        return PlanFrame.from_api(self.rows.get(plan_id), image_map)

    def on_plan(self, plan_id: str, shape_type: str) -> list[dict[str, Any]]:
        return [s for s in self.shapes.values() if s.get("type") == shape_type and s.get("planId") == plan_id]

    def stored(self, ids: Sequence[str], shape_type: str, plan_id: str, noun: str, operation: str) -> list[dict]:
        """The stored shapes, each checked to still be a ``shape_type`` on the plan; anything else is refused."""
        found = []
        for index, shape_id in enumerate(ids):
            shape = self.shapes.get(shape_id)
            if shape is None or shape.get("type") != shape_type or shape.get("planId") != plan_id:
                raise UniFiNotFoundError(
                    noun,
                    "InnerSpace",
                    f"{operation}: item {index} is not a {noun} on this plan now; read the plan again. "
                    "Nothing was sent.",
                )
            found.append(shape)
        return found

    def types(self, key: str) -> dict[str, dict[str, Any]]:
        """The live rows of a type list (``wallTypes``, ``attenuationObjectTypes``), by id."""
        return {
            row["id"]: row
            for row in self.data.get(key) or []
            if isinstance(row, dict) and isinstance(row.get("id"), str) and row.get("isDeleted") is not True
        }

    def require_type(self, key: str, type_id: str, noun: str, operation: str) -> dict[str, Any]:
        row = self.types(key).get(type_id)
        if row is None:
            raise UniFiNotFoundError(noun, "InnerSpace", f"{operation}: no such {noun}")
        return row


# ---------------------------------------------------------------------------
# Running a plan
# ---------------------------------------------------------------------------


ALREADY_APPLIED = (
    "Every object this call creates already exists with the same content, from an earlier call with the same "
    "arguments, so nothing was sent"
)
_PARTLY_PRESENT = (
    "an object created by an identical earlier call was changed, or some of those objects were removed while "
    "others remain; change an argument or remove the existing object. Nothing was sent."
)

_CREATE_AND_CHANGE = (
    "this call would create an object that it also changes or removes, which the console was never tested "
    "with. Nothing was sent; read the plan again."
)


def _touched_ids(body: Any) -> set[str]:
    """The ids a ``shape/change``-style body updates or removes."""
    if not isinstance(body, dict):
        return set()
    items = [*(body.get("update") or ()), *(body.get("remove") or ())]
    return {item["id"] for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)}


def _created_state(request: WriteRequest, snapshot: Snapshot) -> bool | None:
    """Whether the objects to create are all stored with the requested content (True), none is (False), or neither."""
    if not request.created_ids:
        return False
    states = request.expect(snapshot)
    found = [states.get(created) for created in request.created_ids]
    if all(value is True for value in found):
        return True
    if all(value is False for value in found):
        return False
    return None


async def preview_write(
    cm: InnerSpaceConnectionManager,
    *,
    operation: str,
    build: Callable[[Snapshot], WritePlan],
    tool: str | None = None,
    args: BaseModel | None = None,
) -> dict[str, Any]:
    """Read only, without the write lock, and describe what ``apply`` would send now (never the new ids).

    The app checks of a write run first, so a preview is refused wherever ``apply`` would be.

    For a create, ``tool`` and ``args`` (as ``apply`` gets them) let the preview say when an earlier identical
    call already created the objects.
    """
    rows = await ensure_writable(cm, operation=operation)
    snapshot = Snapshot(await read_internal_project(cm, operation=operation), rows)
    plan = build(snapshot)
    warnings = list(plan.warnings)
    no_op = plan.request is None
    if plan.request is not None and plan.new_ids and tool is not None and args is not None:
        existing = _created_state(plan.request(write_ids(tool, args.model_dump(mode="json"), plan.new_ids)), snapshot)
        if existing is True:
            no_op = True
            warnings.append("An identical object from an earlier call already exists; confirming sends nothing")
        elif existing is None:
            warnings.append(
                "Some objects of an earlier identical call exist and some do not, or they differ; "
                "confirming will be refused"
            )
    return {"operation": operation, **plan.preview, "no_op": no_op, "effects": plan.effects, "warnings": warnings}


async def apply_write(
    cm: InnerSpaceConnectionManager,
    *,
    operation: str,
    tool: str,
    args: BaseModel,
    build: Callable[[Snapshot], WritePlan],
) -> WriteVerificationResult:
    """Under the write lock: fresh read, the same checks as the preview, one request, read-back.

    New ids depend only on the call, so before sending a create the fresh read is
    checked for them: all present with the requested content is a no-op ("already
    applied"), some present is refused, none present is sent.
    """
    async with locked_write(cm, operation=operation) as rows:
        snapshot = Snapshot(await read_internal_project(cm, operation=operation), rows)
        plan = build(snapshot)
        metadata: dict[str, Any] = {"effects": plan.effects}
        if plan.request is None:
            if plan.already_applied:
                metadata["already_applied"] = True
            if plan.none_found:
                metadata["none_found"] = True
            return noop_write(operation=operation, metadata={**metadata, "warnings": plan.warnings})
        request = plan.request(write_ids(tool, args.model_dump(mode="json"), plan.new_ids))
        if _touched_ids(request.body) & set(request.created_ids):
            raise InnerSpaceWriteRefusedError(f"{operation}: {_CREATE_AND_CHANGE}")
        metadata["created_ids"] = request.created_ids
        existing = _created_state(request, snapshot)
        if existing is None:
            raise InnerSpaceWriteRefusedError(f"{operation}: {_PARTLY_PRESENT}")
        if existing:
            metadata.update(already_applied=True, warnings=[*plan.warnings, ALREADY_APPLIED])
            return noop_write(operation=operation, metadata=metadata)

        async def read_back() -> Mapping[str, bool | None]:
            return request.expect(Snapshot(await read_internal_project(cm, operation=operation)))

        return await send_write(
            cm,
            request.method,
            request.path,
            request.body,
            operation=operation,
            read_back=read_back,
            metadata=metadata,
            warnings=plan.warnings,
        )


# ---------------------------------------------------------------------------
# Bodies and read-back
# ---------------------------------------------------------------------------


def shape_change_body(
    *,
    create: Sequence[dict[str, Any]] = (),
    update: Sequence[dict[str, Any]] = (),
    remove: Sequence[dict[str, Any]] = (),
    scale: bool = False,
) -> dict[str, Any]:
    """A ``shape/change`` body; a ``map`` shape is never sent and a ``scale`` shape only by the scale write."""
    for item in (*create, *update, *remove):
        kind = item.get("type")
        if kind == "map" or (kind == "scale" and not scale):
            raise InnerSpaceWriteRefusedError("InnerSpace layout writes never send a map shape or a stray scale shape")
    return {"create": list(create), "update": list(update), "remove": list(remove), "mode": "2D"}


def points_close(stored: Any, wanted: Any) -> bool:
    """Whether two position lists have the same length and every x and y within the tolerance."""
    if not isinstance(stored, list) or not isinstance(wanted, list) or len(stored) != len(wanted):
        return False
    for a, b in zip(stored, wanted):
        ax, ay = number(as_dict(a).get("x")), number(as_dict(a).get("y"))
        bx, by = number(as_dict(b).get("x")), number(as_dict(b).get("y"))
        if None in (ax, ay, bx, by):
            return False
        if abs(ax - bx) > POSITION_TOLERANCE or abs(ay - by) > POSITION_TOLERANCE:  # type: ignore[operator]
            return False
    return True


def _same(stored: Any, wanted: Any) -> bool:
    a, b = number(stored), number(wanted)
    if a is not None and b is not None:
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return bool(stored == wanted) and type(stored) is type(wanted)


def matches(stored: Mapping[str, Any] | None, fields: Mapping[str, Any]) -> bool:
    """Whether ``stored`` holds every value in ``fields`` (positions within the tolerance)."""
    if stored is None:
        return False
    for key, value in fields.items():
        if key == "position":
            if not points_close(stored.get(key), value):
                return False
        elif key == "color" and isinstance(value, str) and isinstance(stored.get(key), str):
            # Hex: the console may store either case.
            if stored[key].casefold() != value.casefold():
                return False
        elif not _same(stored.get(key), value):
            return False
    return True


def state(stored: Mapping[str, Any] | None, wanted: Mapping[str, Any], prior: Mapping[str, Any] | None) -> bool | None:
    """True when the requested values are in place, False when the prior ones are (or, for a create, nothing)."""
    if matches(stored, wanted):
        return True
    if prior is None:
        return False if stored is None else None
    return False if matches(stored, prior) else None


def pick(source: Mapping[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    return {key: source.get(key) for key in keys}


# ---------------------------------------------------------------------------
# Preview helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Display:
    """Shows plan-unit points the way the caller gives them: the read frame in ``unit``, or plan units."""

    geometry: PlanGeometry
    unit: Unit
    coordinates: Coordinates

    def point(self, x: float, y: float) -> tuple[float | None, float | None]:
        if self.coordinates == "plan_units":
            return round(x, 4), round(y, 4)
        shown = from_plan_point(x, y, geometry=self.geometry, unit=self.unit)
        return (None, None) if shown is None else shown

    def position(self, position: Any) -> list[tuple[float | None, float | None]]:
        points = []
        for raw in position if isinstance(position, list) else []:
            x, y = number(as_dict(raw).get("x")), number(as_dict(raw).get("y"))
            points.append((None, None) if x is None or y is None else self.point(x, y))
        return points


def bounding_box(points: Iterable[tuple[float | None, float | None]]) -> dict[str, float] | None:
    known = [(x, y) for x, y in points if x is not None and y is not None]
    if not known:
        return None
    xs, ys = [x for x, _ in known], [y for _, y in known]
    return {"x_min": min(xs), "y_min": min(ys), "x_max": max(xs), "y_max": max(ys)}


def plan_points(
    points: Sequence[Point], *, frame: PlanFrame, unit: Unit, coordinates: Coordinates, operation: str
) -> list[dict[str, float]]:
    """The caller's points as a stored ``position`` list (plan units, ``z`` 0)."""
    converted = [
        to_plan_point(x, y, frame=frame, unit=unit, coordinates=coordinates, operation=operation) for x, y in points
    ]
    return [{"x": x, "y": y, "z": 0} for x, y in converted]


def usage_by_plan(snapshot: Snapshot, shape_type: str, key: str, type_id: str) -> dict[str, Any]:
    """How many shapes of ``shape_type`` reference the type, in total and per plan id."""
    counts = Counter(
        s.get("planId") for s in snapshot.shapes.values() if s.get("type") == shape_type and s.get(key) == type_id
    )
    return {"total": sum(counts.values()), "by_plan": {str(plan): n for plan, n in sorted(counts.items(), key=str)}}


def copy_of(shape: Mapping[str, Any]) -> dict[str, Any]:
    return deepcopy(dict(shape))
