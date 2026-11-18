"""Closed arguments for InnerSpace layout writes.

Write inputs use the field names the reads return (``x1``, ``y1``, ``x2``,
``y2``, ``variant``, ``wall_type_id``, ``attenuation_db``, ...), so a value read
can be sent back as it is. Every write that takes a length has a required
``unit``: the unit is part of the call, so changing the project unit between a
preview and its confirm cannot rescale it. Batches are capped. An update item
names its object and only the fields to change; ``MUTABLE_FIELDS`` lists the
fields an update may change and :meth:`InnerSpaceUpdateItem.changes` returns
the ones given. Validation errors never echo the input.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from unifi_core.innerspace.frames import Coordinates
from unifi_core.innerspace.models.reads import _identifier
from unifi_core.innerspace.units import Unit

MAX_CREATE = 100
MAX_UPDATE = 100
MAX_REMOVE = 50

# The built-in wall materials of InnerSpace 1.4.3, plus ``custom`` for a project wall type.
WritableWallVariant = Literal[
    "concrete",
    "drywall",
    "drywall_heavy",
    "glass",
    "glass_thin",
    "brick",
    "metal",
    "wood",
    "door_wood",
    "door_metal",
    "door_glass",
    "window_1_pane",
    "window_2_pane",
    "window_3_pane",
    "custom",
]

_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")


class InnerSpaceWriteInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True, allow_inf_nan=False)


class InnerSpaceLengthInput(InnerSpaceWriteInput):
    """Arguments that carry lengths or coordinates: the unit is required, the frame is the read frame by default."""

    unit: Unit = Field(description="Unit of every length in this call: metric (metres) or imperial (feet)")
    coordinates: Coordinates = Field(
        default="frame",
        description='"frame": the read frame (top-left, y down, in unit); "plan_units": the console\'s own values',
    )


class InnerSpaceUpdateItem(InnerSpaceWriteInput):
    """One object to update: its id and only the fields to change."""

    MUTABLE_FIELDS: ClassVar[frozenset[str]] = frozenset()

    id: str

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        return _identifier(value, "object")

    @model_validator(mode="after")
    def _has_a_change(self) -> InnerSpaceUpdateItem:
        if not self.changes():
            raise ValueError("Name at least one field to change")
        return self

    def changes(self) -> dict[str, Any]:
        """The fields given for this update, by name; a field given as ``None`` is not a change."""
        given = sorted(self.MUTABLE_FIELDS & self.model_fields_set)
        return {name: getattr(self, name) for name in given if getattr(self, name) is not None}


def _unique(values: list[str]) -> list[str]:
    if len(set(values)) != len(values):
        raise ValueError("Each id may appear once per call")
    return values


def _check_wall_type(variant: str | None, wall_type_id: str | None) -> None:
    """``custom`` needs a wall type; a wall type needs ``custom``."""
    if (variant == "custom") != (wall_type_id is not None):
        raise ValueError('A wall type id goes with variant "custom", and only with it')


# ---------------------------------------------------------------------------
# Walls
# ---------------------------------------------------------------------------


class WallCreate(InnerSpaceWriteInput):
    x1: float
    y1: float
    x2: float
    y2: float
    variant: WritableWallVariant
    wall_type_id: str | None = None

    @field_validator("wall_type_id")
    @classmethod
    def _valid_type(cls, value: str | None) -> str | None:
        return None if value is None else _identifier(value, "wall type")

    @model_validator(mode="after")
    def _type_matches_variant(self) -> WallCreate:
        _check_wall_type(self.variant, self.wall_type_id)
        return self


class WallUpdate(InnerSpaceUpdateItem):
    """A wall's new end points (all four together), material, or both."""

    MUTABLE_FIELDS: ClassVar[frozenset[str]] = frozenset({"x1", "y1", "x2", "y2", "variant", "wall_type_id"})
    _ENDS: ClassVar[frozenset[str]] = frozenset({"x1", "y1", "x2", "y2"})

    x1: float | None = None
    y1: float | None = None
    x2: float | None = None
    y2: float | None = None
    variant: WritableWallVariant | None = None
    wall_type_id: str | None = None

    @field_validator("wall_type_id")
    @classmethod
    def _valid_type(cls, value: str | None) -> str | None:
        return None if value is None else _identifier(value, "wall type")

    @model_validator(mode="after")
    def _whole_ends_and_matching_type(self) -> WallUpdate:
        ends = self._ENDS & set(self.changes())
        if ends and ends != self._ENDS:
            raise ValueError("Give all four of x1, y1, x2 and y2, or none of them")
        if self.variant is not None or self.wall_type_id is not None:
            _check_wall_type(self.variant, self.wall_type_id)
        return self


class CreateWallsInput(InnerSpaceLengthInput):
    plan_id: str
    walls: list[WallCreate] = Field(min_length=1, max_length=MAX_CREATE, description="At most 100 walls per call")

    @field_validator("plan_id")
    @classmethod
    def _plan(cls, value: str) -> str:
        return _identifier(value, "plan")


class UpdateWallsInput(InnerSpaceLengthInput):
    plan_id: str
    walls: list[WallUpdate] = Field(min_length=1, max_length=MAX_UPDATE, description="At most 100 walls per call")

    @field_validator("plan_id")
    @classmethod
    def _plan(cls, value: str) -> str:
        return _identifier(value, "plan")

    @model_validator(mode="after")
    def _unique_walls(self) -> UpdateWallsInput:
        _unique([wall.id for wall in self.walls])
        return self


class RemoveWallsInput(InnerSpaceWriteInput):
    plan_id: str
    wall_ids: list[str] = Field(min_length=1, max_length=MAX_REMOVE, description="At most 50 walls per call")

    @field_validator("plan_id")
    @classmethod
    def _plan(cls, value: str) -> str:
        return _identifier(value, "plan")

    @field_validator("wall_ids")
    @classmethod
    def _walls(cls, values: list[str]) -> list[str]:
        return _unique([_identifier(value, "wall") for value in values])


# ---------------------------------------------------------------------------
# Wall types
# ---------------------------------------------------------------------------


def _name(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= 32:
        raise ValueError("A name has 1 to 32 characters")
    return value


def _color(value: str) -> str:
    if not _COLOR.fullmatch(value):
        raise ValueError("A color is #RRGGBB")
    return value


class WallTypeCreate(InnerSpaceWriteInput):
    name: str
    attenuation_db: float = Field(ge=0, le=99, description="Loss through the wall in dB, 0 to 99")
    color: str = Field(description="#RRGGBB")
    transparent: bool = False

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        return _name(value)

    @field_validator("color")
    @classmethod
    def _valid_color(cls, value: str) -> str:
        return _color(value)


class WallTypeUpdate(InnerSpaceUpdateItem):
    MUTABLE_FIELDS: ClassVar[frozenset[str]] = frozenset({"name", "attenuation_db", "color", "transparent"})

    name: str | None = None
    attenuation_db: float | None = Field(default=None, ge=0, le=99)
    color: str | None = None
    transparent: bool | None = None

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str | None) -> str | None:
        return None if value is None else _name(value)

    @field_validator("color")
    @classmethod
    def _valid_color(cls, value: str | None) -> str | None:
        return None if value is None else _color(value)
