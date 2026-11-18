"""InnerSpace walls: create, update (full stored object) and remove (stored objects)."""

from __future__ import annotations

from functools import partial
from typing import Any, Sequence

from unifi_core.innerspace.frames import Coordinates
from unifi_core.innerspace.managers._layout import apply_write, preview_write
from unifi_core.innerspace.managers._shapes import ShapeKind, plan_create, plan_remove, plan_update
from unifi_core.innerspace.managers.connection_manager import InnerSpaceConnectionManager, reconnects_on_demand
from unifi_core.innerspace.models.writes import CreateWallsInput, RemoveWallsInput, UpdateWallsInput
from unifi_core.innerspace.units import Unit
from unifi_core.write_verification import WriteVerificationResult

_CREATE = "create InnerSpace walls"
_UPDATE = "update InnerSpace walls"
_REMOVE = "remove InnerSpace walls"


def _ends(wall: Any) -> list[tuple[float, float]] | None:
    if wall.x1 is None:
        return None
    return [(wall.x1, wall.y1), (wall.x2, wall.y2)]


def _show(points: Sequence[tuple[float | None, float | None]]) -> dict[str, Any]:
    (x1, y1), (x2, y2) = (list(points) + [(None, None)] * 2)[:2]
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}


WALL = ShapeKind(
    shape_type="wall",
    noun="wall",
    type_key="wallTypeId",
    types_key="wallTypes",
    type_noun="wall type",
    type_field="wall_type_id",
    points=_ends,
    show=_show,
)


def _create_plan(args: CreateWallsInput) -> partial:
    return partial(
        plan_create,
        WALL,
        plan_id=args.plan_id,
        items=args.walls,
        unit=args.unit,
        coordinates=args.coordinates,
        operation=_CREATE,
    )


def _update_plan(args: UpdateWallsInput) -> partial:
    return partial(
        plan_update,
        WALL,
        plan_id=args.plan_id,
        items=args.walls,
        unit=args.unit,
        coordinates=args.coordinates,
        operation=_UPDATE,
    )


def _remove_plan(args: RemoveWallsInput) -> partial:
    return partial(plan_remove, WALL, plan_id=args.plan_id, ids=args.wall_ids, operation=_REMOVE)


@reconnects_on_demand
class InnerSpaceWallManager:
    def __init__(self, cm: InnerSpaceConnectionManager) -> None:
        self._cm = cm

    async def preview_create_walls(
        self, plan_id: str, walls: list[dict[str, Any]], *, unit: Unit, coordinates: Coordinates = "frame"
    ) -> dict[str, Any]:
        """What ``apply_create_walls`` would create: count, bounding box and the first walls, without ids."""
        args = CreateWallsInput(plan_id=plan_id, walls=walls, unit=unit, coordinates=coordinates)
        return await preview_write(
            self._cm, operation=_CREATE, build=_create_plan(args), tool="innerspace_create_walls", args=args
        )

    async def apply_create_walls(
        self, plan_id: str, walls: list[dict[str, Any]], *, unit: Unit, coordinates: Coordinates = "frame"
    ) -> WriteVerificationResult:
        """Create walls on one plan (at most 100); ``created_ids`` in the result metadata."""
        args = CreateWallsInput(plan_id=plan_id, walls=walls, unit=unit, coordinates=coordinates)
        return await apply_write(
            self._cm, operation=_CREATE, tool="innerspace_create_walls", args=args, build=_create_plan(args)
        )

    async def preview_update_walls(
        self, plan_id: str, walls: list[dict[str, Any]], *, unit: Unit, coordinates: Coordinates = "frame"
    ) -> dict[str, Any]:
        """Current and proposed values of each wall that would change, and the fields that would be cleared."""
        args = UpdateWallsInput(plan_id=plan_id, walls=walls, unit=unit, coordinates=coordinates)
        return await preview_write(self._cm, operation=_UPDATE, build=_update_plan(args))

    async def apply_update_walls(
        self, plan_id: str, walls: list[dict[str, Any]], *, unit: Unit, coordinates: Coordinates = "frame"
    ) -> WriteVerificationResult:
        """Change walls' end points or material (at most 100); each is sent as its whole stored object."""
        args = UpdateWallsInput(plan_id=plan_id, walls=walls, unit=unit, coordinates=coordinates)
        return await apply_write(
            self._cm, operation=_UPDATE, tool="innerspace_update_walls", args=args, build=_update_plan(args)
        )

    async def preview_remove_walls(self, plan_id: str, wall_ids: list[str]) -> dict[str, Any]:
        """The walls that would be removed, in the project unit."""
        args = RemoveWallsInput(plan_id=plan_id, wall_ids=wall_ids)
        return await preview_write(self._cm, operation=_REMOVE, build=_remove_plan(args))

    async def apply_remove_walls(self, plan_id: str, wall_ids: list[str]) -> WriteVerificationResult:
        """Remove walls from one plan (at most 50); the stored objects are sent."""
        args = RemoveWallsInput(plan_id=plan_id, wall_ids=wall_ids)
        return await apply_write(
            self._cm, operation=_REMOVE, tool="innerspace_remove_walls", args=args, build=_remove_plan(args)
        )
