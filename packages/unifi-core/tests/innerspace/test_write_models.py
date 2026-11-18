"""Closed write inputs: required unit, caps, field names shared with the reads, and mutable fields."""

import pytest
from pydantic import ValidationError
from unifi_core.innerspace.models.project import Wall, WallType
from unifi_core.innerspace.models.writes import (
    MAX_CREATE,
    MAX_REMOVE,
    MAX_UPDATE,
    CreateWallsInput,
    RemoveWallsInput,
    UpdateWallsInput,
    WallCreate,
    WallTypeCreate,
    WallTypeUpdate,
    WallUpdate,
)

from tests.innerspace.helpers import PLAN_A, WALL_TYPE

WALL_ID = "00000000-0000-4000-8000-000000000008"
SECRET = "marker-c41b"
WALL = {"x1": 1.0, "y1": 1.0, "x2": 3.0, "y2": 1.0, "variant": "drywall"}


def test_caps():
    assert (MAX_CREATE, MAX_UPDATE, MAX_REMOVE) == (100, 100, 50)


def test_create_and_update_use_the_read_field_names():
    assert set(WallCreate.model_fields) <= set(Wall.model_fields)
    assert WallUpdate.MUTABLE_FIELDS <= set(Wall.model_fields)
    assert set(WallUpdate.model_fields) == WallUpdate.MUTABLE_FIELDS | {"id"}
    assert set(WallTypeCreate.model_fields) <= set(WallType.model_fields)
    assert set(WallTypeUpdate.model_fields) == WallTypeUpdate.MUTABLE_FIELDS | {"id"}


@pytest.mark.parametrize("model", [CreateWallsInput, UpdateWallsInput])
def test_unit_is_required(model):
    item = WALL if model is CreateWallsInput else {"id": WALL_ID, "variant": "glass"}
    with pytest.raises(ValidationError):
        model(plan_id=PLAN_A, walls=[item])

    assert model(plan_id=PLAN_A, unit="imperial", walls=[item]).coordinates == "frame"


@pytest.mark.parametrize(
    "model, field, item, cap",
    [
        (CreateWallsInput, "walls", WALL, MAX_CREATE),
        (UpdateWallsInput, "walls", None, MAX_UPDATE),
    ],
)
def test_batch_caps(model, field, item, cap):
    def items(count):
        if item is not None:
            return [dict(item) for _ in range(count)]
        return [{"id": f"00000000-0000-4000-8000-{n:012d}", "variant": "glass"} for n in range(count)]

    assert len(getattr(model(plan_id=PLAN_A, unit="metric", **{field: items(cap)}), field)) == cap
    with pytest.raises(ValidationError):
        model(plan_id=PLAN_A, unit="metric", **{field: items(cap + 1)})
    with pytest.raises(ValidationError):
        model(plan_id=PLAN_A, unit="metric", **{field: []})


def test_remove_cap():
    ids = [f"00000000-0000-4000-8000-{n:012d}" for n in range(MAX_REMOVE + 1)]

    assert len(RemoveWallsInput(plan_id=PLAN_A, wall_ids=ids[:MAX_REMOVE]).wall_ids) == MAX_REMOVE
    with pytest.raises(ValidationError):
        RemoveWallsInput(plan_id=PLAN_A, wall_ids=ids)


@pytest.mark.parametrize(
    "ids",
    [[WALL_ID, WALL_ID], ["a/b"], [""]],
)
def test_remove_ids_are_single_segments_and_unique(ids):
    with pytest.raises(ValidationError):
        RemoveWallsInput(plan_id=PLAN_A, wall_ids=ids)


@pytest.mark.parametrize(
    "item",
    [
        {**WALL, "colour": "red"},
        {**WALL, "x1": "1.0"},
        {**WALL, "x1": float("nan")},
        {**WALL, "x2": float("inf")},
        {**WALL, "variant": "elevator"},
        {**WALL, "variant": "custom"},
        {**WALL, "wall_type_id": WALL_TYPE},
        {k: v for k, v in WALL.items() if k != "y2"},
    ],
)
def test_wall_create_is_closed(item):
    with pytest.raises(ValidationError):
        WallCreate(**item)


def test_custom_wall_names_its_type():
    assert WallCreate(**{**WALL, "variant": "custom", "wall_type_id": WALL_TYPE}).wall_type_id == WALL_TYPE


@pytest.mark.parametrize(
    "item",
    [
        {"id": WALL_ID},
        {"id": WALL_ID, "x1": 1.0, "y1": 2.0},
        {"id": WALL_ID, "variant": "custom"},
        {"id": WALL_ID, "wall_type_id": WALL_TYPE},
        {"id": "../x", "variant": "glass"},
        {"id": WALL_ID, "variant": "glass", "status": 0},
    ],
)
def test_wall_update_is_closed(item):
    with pytest.raises(ValidationError):
        WallUpdate(**item)


def test_wall_update_changes_are_only_the_fields_given():
    update = WallUpdate(id=WALL_ID, x1=1.0, y1=2.0, x2=3.0, y2=4.0)

    assert update.changes() == {"x1": 1.0, "y1": 2.0, "x2": 3.0, "y2": 4.0}
    assert WallUpdate(id=WALL_ID, variant="custom", wall_type_id=WALL_TYPE).changes() == {
        "variant": "custom",
        "wall_type_id": WALL_TYPE,
    }


def test_update_ids_are_unique():
    with pytest.raises(ValidationError):
        UpdateWallsInput(
            plan_id=PLAN_A,
            unit="metric",
            walls=[{"id": WALL_ID, "variant": "glass"}, {"id": WALL_ID, "variant": "brick"}],
        )


@pytest.mark.parametrize(
    "item",
    [
        {"name": "", "attenuation_db": 5.0, "color": "#112233"},
        {"name": " ", "attenuation_db": 5.0, "color": "#112233"},
        {"name": "x" * 33, "attenuation_db": 5.0, "color": "#112233"},
        {"name": "Glass", "attenuation_db": -1.0, "color": "#112233"},
        {"name": "Glass", "attenuation_db": 100.0, "color": "#112233"},
        {"name": "Glass", "attenuation_db": 5.0, "color": "red"},
        {"name": "Glass", "attenuation_db": 5.0, "color": "#112233", "isDeleted": True},
    ],
)
def test_wall_type_create_is_closed(item):
    with pytest.raises(ValidationError):
        WallTypeCreate(**item)


def test_wall_type_update_needs_a_change():
    with pytest.raises(ValidationError):
        WallTypeUpdate(id=WALL_TYPE)

    assert WallTypeUpdate(id=WALL_TYPE, attenuation_db=12.0).changes() == {"attenuation_db": 12.0}


def test_errors_never_echo_the_input():
    with pytest.raises(ValidationError) as caught:
        WallTypeCreate(name=SECRET * 10, attenuation_db=5.0, color=SECRET)

    assert SECRET not in str(caught.value)
