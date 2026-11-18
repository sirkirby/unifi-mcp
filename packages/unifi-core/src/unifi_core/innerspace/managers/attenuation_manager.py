"""InnerSpace attenuation objects (closed polygons) and their types.

Objects: create, update (full stored object) and remove (stored objects),
stored with ``type: "attenuationObject"``. The console rejects an open
polygon, so the input must repeat its first point last. Types: create and
update; removal is not built.
"""

from __future__ import annotations

from functools import partial
from typing import Any, Sequence

from unifi_core.innerspace.frames import Coordinates
from unifi_core.innerspace.managers._layout import apply_write, preview_write
from unifi_core.innerspace.managers._shapes import ShapeKind, plan_create, plan_remove, plan_update
from unifi_core.innerspace.managers._types import TypeKind, plan_type_create, plan_type_update
from unifi_core.innerspace.managers.connection_manager import (
    ATTENUATION_OBJECT_TYPE_PATH,
    InnerSpaceConnectionManager,
    reconnects_on_demand,
)
from unifi_core.innerspace.models.writes import (
    AttenuationObjectTypeCreate,
    AttenuationObjectTypeUpdate,
    CreateAttenuationObjectsInput,
    RemoveAttenuationObjectsInput,
    UpdateAttenuationObjectsInput,
)
from unifi_core.innerspace.units import Unit
from unifi_core.write_verification import WriteVerificationResult

_CREATE = "create InnerSpace attenuation objects"
_UPDATE = "update InnerSpace attenuation objects"
_REMOVE = "remove InnerSpace attenuation objects"
_CREATE_TYPE = "create InnerSpace attenuation-object type"
_UPDATE_TYPE = "update InnerSpace attenuation-object type"


def _corners(item: Any) -> list[tuple[float, float]] | None:
    return None if item.points is None else [(point.x, point.y) for point in item.points]


def _show(points: Sequence[tuple[float | None, float | None]]) -> dict[str, Any]:
    return {"points": [{"x": x, "y": y} for x, y in points]}


ATTENUATION_OBJECT = ShapeKind(
    shape_type="attenuationObject",
    noun="attenuation object",
    type_key="attenuationObjectTypeId",
    types_key="attenuationObjectTypes",
    type_noun="attenuation-object type",
    type_field="attenuation_object_type_id",
    points=_corners,
    show=_show,
)
ATTENUATION_OBJECT_TYPE = TypeKind(
    path=ATTENUATION_OBJECT_TYPE_PATH,
    types_key="attenuationObjectTypes",
    noun="attenuation-object type",
    shape_type="attenuationObject",
    reference="attenuationObjectTypeId",
    shape_noun="attenuation object",
    effect="objects_using_type",
    new_fields={"isDeleted": False, "overridesVariant": None, "bottomHeight": None, "topHeight": None},
)


def _create_plan(args: CreateAttenuationObjectsInput) -> partial:
    return partial(
        plan_create,
        ATTENUATION_OBJECT,
        plan_id=args.plan_id,
        items=args.objects,
        unit=args.unit,
        coordinates=args.coordinates,
        operation=_CREATE,
    )


def _update_plan(args: UpdateAttenuationObjectsInput) -> partial:
    return partial(
        plan_update,
        ATTENUATION_OBJECT,
        plan_id=args.plan_id,
        items=args.objects,
        unit=args.unit,
        coordinates=args.coordinates,
        operation=_UPDATE,
    )


def _remove_plan(args: RemoveAttenuationObjectsInput) -> partial:
    return partial(plan_remove, ATTENUATION_OBJECT, plan_id=args.plan_id, ids=args.object_ids, operation=_REMOVE)


def _type_update(type_id: str, fields: dict[str, Any]) -> AttenuationObjectTypeUpdate:
    return AttenuationObjectTypeUpdate(
        id=type_id, **{name: value for name, value in fields.items() if value is not None}
    )


@reconnects_on_demand
class InnerSpaceAttenuationManager:
    def __init__(self, cm: InnerSpaceConnectionManager) -> None:
        self._cm = cm

    async def preview_create_attenuation_objects(
        self, plan_id: str, objects: list[dict[str, Any]], *, unit: Unit, coordinates: Coordinates = "frame"
    ) -> dict[str, Any]:
        """What ``apply_create_attenuation_objects`` would create: count, bounding box, first objects, no ids."""
        args = CreateAttenuationObjectsInput(plan_id=plan_id, objects=objects, unit=unit, coordinates=coordinates)
        return await preview_write(
            self._cm,
            operation=_CREATE,
            build=_create_plan(args),
            tool="innerspace_create_attenuation_objects",
            args=args,
        )

    async def apply_create_attenuation_objects(
        self, plan_id: str, objects: list[dict[str, Any]], *, unit: Unit, coordinates: Coordinates = "frame"
    ) -> WriteVerificationResult:
        """Create attenuation objects on one plan (at most 100); ``created_ids`` in the result metadata."""
        args = CreateAttenuationObjectsInput(plan_id=plan_id, objects=objects, unit=unit, coordinates=coordinates)
        return await apply_write(
            self._cm,
            operation=_CREATE,
            tool="innerspace_create_attenuation_objects",
            args=args,
            build=_create_plan(args),
        )

    async def preview_update_attenuation_objects(
        self, plan_id: str, objects: list[dict[str, Any]], *, unit: Unit, coordinates: Coordinates = "frame"
    ) -> dict[str, Any]:
        """Current and proposed values of each object that would change, and the fields that would be cleared."""
        args = UpdateAttenuationObjectsInput(plan_id=plan_id, objects=objects, unit=unit, coordinates=coordinates)
        return await preview_write(self._cm, operation=_UPDATE, build=_update_plan(args))

    async def apply_update_attenuation_objects(
        self, plan_id: str, objects: list[dict[str, Any]], *, unit: Unit, coordinates: Coordinates = "frame"
    ) -> WriteVerificationResult:
        """Change objects' polygons or kinds (at most 100); each is sent as its whole stored object."""
        args = UpdateAttenuationObjectsInput(plan_id=plan_id, objects=objects, unit=unit, coordinates=coordinates)
        return await apply_write(
            self._cm,
            operation=_UPDATE,
            tool="innerspace_update_attenuation_objects",
            args=args,
            build=_update_plan(args),
        )

    async def preview_remove_attenuation_objects(self, plan_id: str, object_ids: list[str]) -> dict[str, Any]:
        """The objects that would be removed, in the project unit."""
        args = RemoveAttenuationObjectsInput(plan_id=plan_id, object_ids=object_ids)
        return await preview_write(self._cm, operation=_REMOVE, build=_remove_plan(args))

    async def apply_remove_attenuation_objects(self, plan_id: str, object_ids: list[str]) -> WriteVerificationResult:
        """Remove attenuation objects from one plan (at most 50); the stored objects are sent."""
        args = RemoveAttenuationObjectsInput(plan_id=plan_id, object_ids=object_ids)
        return await apply_write(
            self._cm,
            operation=_REMOVE,
            tool="innerspace_remove_attenuation_objects",
            args=args,
            build=_remove_plan(args),
        )

    async def preview_create_attenuation_object_type(
        self, name: str, attenuation_db: float, color: str
    ) -> dict[str, Any]:
        """The type that ``apply_create_attenuation_object_type`` would add, and a warning when its name is taken."""
        item = AttenuationObjectTypeCreate(name=name, attenuation_db=attenuation_db, color=color)
        return await preview_write(
            self._cm,
            operation=_CREATE_TYPE,
            build=partial(plan_type_create, ATTENUATION_OBJECT_TYPE, item=item),
            tool="innerspace_create_attenuation_object_type",
            args=item,
        )

    async def apply_create_attenuation_object_type(
        self, name: str, attenuation_db: float, color: str
    ) -> WriteVerificationResult:
        """Add a project attenuation-object type, used with variant ``custom``. Its id is in ``created_ids``."""
        item = AttenuationObjectTypeCreate(name=name, attenuation_db=attenuation_db, color=color)
        return await apply_write(
            self._cm,
            operation=_CREATE_TYPE,
            tool="innerspace_create_attenuation_object_type",
            args=item,
            build=partial(plan_type_create, ATTENUATION_OBJECT_TYPE, item=item),
        )

    async def preview_update_attenuation_object_type(
        self,
        attenuation_object_type_id: str,
        *,
        name: str | None = None,
        attenuation_db: float | None = None,
        color: str | None = None,
    ) -> dict[str, Any]:
        """Current and proposed values, and the objects the change reaches (a type is project-wide)."""
        item = _type_update(
            attenuation_object_type_id, {"name": name, "attenuation_db": attenuation_db, "color": color}
        )
        return await preview_write(
            self._cm,
            operation=_UPDATE_TYPE,
            build=partial(plan_type_update, ATTENUATION_OBJECT_TYPE, item=item, operation=_UPDATE_TYPE),
        )

    async def apply_update_attenuation_object_type(
        self,
        attenuation_object_type_id: str,
        *,
        name: str | None = None,
        attenuation_db: float | None = None,
        color: str | None = None,
    ) -> WriteVerificationResult:
        """Change an attenuation-object type; the whole stored type is sent with the given fields changed."""
        item = _type_update(
            attenuation_object_type_id, {"name": name, "attenuation_db": attenuation_db, "color": color}
        )
        return await apply_write(
            self._cm,
            operation=_UPDATE_TYPE,
            tool="innerspace_update_attenuation_object_type",
            args=item,
            build=partial(plan_type_update, ATTENUATION_OBJECT_TYPE, item=item, operation=_UPDATE_TYPE),
        )
