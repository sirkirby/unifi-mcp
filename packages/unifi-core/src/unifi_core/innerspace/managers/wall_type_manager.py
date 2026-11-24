"""InnerSpace wall types: create and update. Removal is not built (the console answers 500 while a wall uses it)."""

from __future__ import annotations

from functools import partial
from typing import Any

from unifi_core.innerspace.managers._layout import apply_write, preview_write
from unifi_core.innerspace.managers._types import TypeKind, plan_type_create, plan_type_update
from unifi_core.innerspace.managers.connection_manager import (
    WALL_TYPE_PATH,
    InnerSpaceConnectionManager,
    reconnects_on_demand,
)
from unifi_core.innerspace.models.writes import WallTypeCreate, WallTypeUpdate
from unifi_core.write_verification import WriteVerificationResult

_CREATE = "create InnerSpace wall type"
_UPDATE = "update InnerSpace wall type"

WALL_TYPE = TypeKind(
    path=WALL_TYPE_PATH,
    types_key="wallTypes",
    noun="wall type",
    shape_type="wall",
    reference="wallTypeId",
    shape_noun="wall",
    effect="walls_using_type",
    new_fields={
        "isDeleted": False,
        "overridesVariant": None,
        "bottomHeight": None,
        "topHeight": None,
        "transparent": False,
        "autoFillEnabled": False,
    },
)


def _update_input(wall_type_id: str, fields: dict[str, Any]) -> WallTypeUpdate:
    return WallTypeUpdate(id=wall_type_id, **{name: value for name, value in fields.items() if value is not None})


@reconnects_on_demand
class InnerSpaceWallTypeManager:
    def __init__(self, cm: InnerSpaceConnectionManager) -> None:
        self._cm = cm

    async def preview_create_wall_type(
        self, name: str, attenuation_db: float, color: str, *, transparent: bool = False
    ) -> dict[str, Any]:
        """The wall type that ``apply_create_wall_type`` would add, and a warning when its name is taken."""
        item = WallTypeCreate(name=name, attenuation_db=attenuation_db, color=color, transparent=transparent)
        return await preview_write(
            self._cm,
            operation=_CREATE,
            build=partial(plan_type_create, WALL_TYPE, item=item),
            tool="innerspace_create_wall_type",
            args=item,
        )

    async def apply_create_wall_type(
        self, name: str, attenuation_db: float, color: str, *, transparent: bool = False
    ) -> WriteVerificationResult:
        """Add a project wall type; walls use it with variant ``custom``. Its id is in ``created_ids``."""
        item = WallTypeCreate(name=name, attenuation_db=attenuation_db, color=color, transparent=transparent)
        return await apply_write(
            self._cm,
            operation=_CREATE,
            tool="innerspace_create_wall_type",
            args=item,
            build=partial(plan_type_create, WALL_TYPE, item=item),
        )

    async def preview_update_wall_type(
        self,
        wall_type_id: str,
        *,
        name: str | None = None,
        attenuation_db: float | None = None,
        color: str | None = None,
        transparent: bool | None = None,
    ) -> dict[str, Any]:
        """Current and proposed values, and the walls the change reaches (a type is project-wide)."""
        item = _update_input(
            wall_type_id, {"name": name, "attenuation_db": attenuation_db, "color": color, "transparent": transparent}
        )
        return await preview_write(
            self._cm, operation=_UPDATE, build=partial(plan_type_update, WALL_TYPE, item=item, operation=_UPDATE)
        )

    async def apply_update_wall_type(
        self,
        wall_type_id: str,
        *,
        name: str | None = None,
        attenuation_db: float | None = None,
        color: str | None = None,
        transparent: bool | None = None,
    ) -> WriteVerificationResult:
        """Change a wall type; the whole stored type is sent with the given fields changed."""
        item = _update_input(
            wall_type_id, {"name": name, "attenuation_db": attenuation_db, "color": color, "transparent": transparent}
        )
        return await apply_write(
            self._cm,
            operation=_UPDATE,
            tool="innerspace_update_wall_type",
            args=item,
            build=partial(plan_type_update, WALL_TYPE, item=item, operation=_UPDATE),
        )
