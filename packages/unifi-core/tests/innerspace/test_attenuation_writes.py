"""Attenuation objects (closed polygons) and their types: literal bodies from the 1.4.3 probe, previews, refusals."""

import re
from copy import deepcopy

import pytest
from pydantic import ValidationError
from unifi_core.exceptions import UniFiNotFoundError, UniFiValidationError
from unifi_core.innerspace.managers.attenuation_manager import InnerSpaceAttenuationManager
from unifi_core.innerspace.managers.connection_manager import ATTENUATION_OBJECT_TYPE_PATH
from unifi_core.innerspace.models.writes import AttenuationObjectCreate, AttenuationObjectTypeUpdate

from tests.innerspace.helpers import (
    PLAN_A,
    PLAN_B,
    PROJECT_ID,
    STAMP_STATE,
    UUID_SHAPED,
    floor_plan_rows,
    internal_state,
    ready,
    script_preview,
    stored_shape,
)

OBJECT = "00000000-0000-4000-8000-0000000000b1"
OBJECT_TYPE = "00000000-0000-4000-8000-0000000000c1"
WALL_08 = "00000000-0000-4000-8000-000000000008"
# A 1 m square at (1, 1) m in Plan A's frame (1000 x 800 px, 100 per metre), closed.
SQUARE = [{"x": 1.0, "y": 1.0}, {"x": 2.0, "y": 1.0}, {"x": 2.0, "y": 2.0}, {"x": 1.0, "y": 2.0}, {"x": 1.0, "y": 1.0}]
SQUARE_UNITS = [
    {"x": -400.0, "y": 300.0, "z": 0},
    {"x": -300.0, "y": 300.0, "z": 0},
    {"x": -300.0, "y": 200.0, "z": 0},
    {"x": -400.0, "y": 200.0, "z": 0},
    {"x": -400.0, "y": 300.0, "z": 0},
]
STORED_OBJECT = {
    "id": OBJECT,
    "type": "attenuationObject",
    "projectId": PROJECT_ID,
    "planId": PLAN_A,
    "position": [
        {"x": 0, "y": 0, "z": 0},
        {"x": 50, "y": 0, "z": 0},
        {"x": 50, "y": 50, "z": 0},
        {"x": 0, "y": 0, "z": 0},
    ],
    "variant": "custom",
    "attenuationObjectTypeId": OBJECT_TYPE,
    "status": 0,
    **STAMP_STATE,
}
STORED_TYPE = {
    "id": OBJECT_TYPE,
    "projectId": PROJECT_ID,
    "name": "Racking",
    "attenuation": 9,
    "color": "#334455",
    "isDeleted": False,
    "overridesVariant": None,
    "bottomHeight": None,
    "topHeight": None,
    **STAMP_STATE,
}


def _state():
    state = internal_state()
    state["shapes"].append(deepcopy(STORED_OBJECT))
    state["attenuationObjectTypes"] = [deepcopy(STORED_TYPE)]
    return state


def _type_writes(console):
    return [r.body for r in console.calls("POST", ATTENUATION_OBJECT_TYPE_PATH)]


async def test_create_sends_a_closed_polygon_as_probed(connected, console):
    ready(console, _state())

    result = await InnerSpaceAttenuationManager(connected).apply_create_attenuation_objects(
        PLAN_A, [{"points": SQUARE, "variant": "car"}], unit="metric"
    )

    (new_id,) = result.metadata["created_ids"]
    assert console.shape_changes() == [
        {
            "create": [
                {
                    "id": new_id,
                    "type": "attenuationObject",
                    "projectId": PROJECT_ID,
                    "planId": PLAN_A,
                    "position": SQUARE_UNITS,
                    "variant": "car",
                    "status": 0,
                }
            ],
            "update": [],
            "remove": [],
            "mode": "2D",
        }
    ]
    assert result.success is True and result.mutation_applied is True
    assert stored_shape(console, new_id)["attenuationObjectTypeId"] is None
    console.assert_csrf()


async def test_custom_object_names_its_type(connected, console):
    ready(console, _state())
    item = {"points": SQUARE, "variant": "custom", "attenuation_object_type_id": OBJECT_TYPE}

    result = await InnerSpaceAttenuationManager(connected).apply_create_attenuation_objects(
        PLAN_A, [item], unit="metric"
    )

    assert console.shape_changes()[0]["create"][0]["attenuationObjectTypeId"] == OBJECT_TYPE
    assert result.success is True


@pytest.mark.parametrize(
    "points",
    [
        SQUARE[:-1],  # open
        [SQUARE[0], SQUARE[1], SQUARE[0]],  # too few corners
        [*SQUARE[:-1], {"x": 1.0, "y": 1.5}],  # last point is not the first
    ],
)
async def test_open_polygons_are_refused_with_fixed_text(connected, console, points):
    ready(console, _state())
    start = len(console.requests)

    with pytest.raises(ValidationError) as caught:
        await InnerSpaceAttenuationManager(connected).apply_create_attenuation_objects(
            PLAN_A, [{"points": points, "variant": "car"}], unit="metric"
        )

    assert "1.5" not in str(caught.value)
    assert console.requests[start:] == []


def test_a_closed_polygon_model_accepts_the_repeated_first_point():
    assert len(AttenuationObjectCreate(points=SQUARE, variant="truck").points) == 5


async def test_create_preview_is_a_summary_without_new_ids(connected, console):
    console.load_project(_state())
    script_preview(console, times=2)
    manager = InnerSpaceAttenuationManager(connected)
    objects = [{"points": SQUARE, "variant": "car"}] * 6

    preview = await manager.preview_create_attenuation_objects(PLAN_A, objects, unit="metric")

    assert preview == await manager.preview_create_attenuation_objects(PLAN_A, objects, unit="metric")
    assert (preview["count"], len(preview["items"])) == (6, 5)
    assert preview["items"][0]["proposed"] == {"points": SQUARE, "variant": "car", "attenuation_object_type_id": None}
    assert preview["bounding_box"] == {"x_min": 1.0, "y_min": 1.0, "x_max": 2.0, "y_max": 2.0}
    assert set(re.findall(UUID_SHAPED, repr(preview))) == {PLAN_A}
    assert console.writes() == []


async def test_update_sends_the_full_stored_object_and_clears_the_type(connected, console):
    console.load_project(_state())
    script_preview(console)
    manager = InnerSpaceAttenuationManager(connected)

    preview = await manager.preview_update_attenuation_objects(
        PLAN_A, [{"id": OBJECT, "variant": "truck"}], unit="metric"
    )
    assert preview["items"] == [
        {
            "id": OBJECT,
            "current": {"attenuation_object_type_id": OBJECT_TYPE, "variant": "custom"},
            "proposed": {"variant": "truck"},
            "cleared": ["attenuation_object_type_id"],
        }
    ]

    console.script_write(floor_plans=floor_plan_rows())
    result = await manager.apply_update_attenuation_objects(PLAN_A, [{"id": OBJECT, "variant": "truck"}], unit="metric")

    expected = {key: value for key, value in STORED_OBJECT.items() if key != "attenuationObjectTypeId"}
    assert console.shape_changes() == [
        {"create": [], "update": [{**expected, "variant": "truck"}], "remove": [], "mode": "2D"}
    ]
    assert result.success is True
    assert stored_shape(console, OBJECT)["attenuationObjectTypeId"] is None


async def test_update_moves_the_polygon(connected, console):
    ready(console, _state())

    result = await InnerSpaceAttenuationManager(connected).apply_update_attenuation_objects(
        PLAN_A, [{"id": OBJECT, "points": SQUARE}], unit="metric"
    )

    (sent,) = console.shape_changes()[0]["update"]
    assert sent["position"] == SQUARE_UNITS
    assert sent["variant"] == "custom" and sent["attenuationObjectTypeId"] == OBJECT_TYPE
    assert result.success is True


async def test_update_equal_to_the_stored_object_sends_nothing(connected, console):
    ready(console, _state())
    same = {"id": OBJECT, "variant": "custom", "attenuation_object_type_id": OBJECT_TYPE}

    result = await InnerSpaceAttenuationManager(connected).apply_update_attenuation_objects(
        PLAN_A, [same], unit="metric"
    )

    assert (result.success, result.mutation_applied) == (True, False)
    assert console.writes() == []


@pytest.mark.parametrize("change", ["vanished", "other_type", "other_plan"])
async def test_apply_rereads_and_refuses_changed_shape(connected, console, change):
    state = _state()
    shape = next(s for s in state["shapes"] if s["id"] == OBJECT)
    if change == "vanished":
        state["shapes"].remove(shape)
    elif change == "other_type":
        shape["type"] = "wall"
    else:
        shape["planId"] = PLAN_B
    ready(console, state, writes=2)
    manager = InnerSpaceAttenuationManager(connected)

    with pytest.raises(UniFiNotFoundError):
        await manager.apply_update_attenuation_objects(PLAN_A, [{"id": OBJECT, "variant": "car"}], unit="metric")
    if change == "vanished":
        # Gone from the whole project: a retried remove, so a no-op rather than a refusal.
        removed = await manager.apply_remove_attenuation_objects(PLAN_A, [OBJECT])
        assert (removed.success, removed.mutation_applied) == (True, False)
    else:
        with pytest.raises(UniFiNotFoundError):
            await manager.apply_remove_attenuation_objects(PLAN_A, [OBJECT])
    assert console.writes() == []


async def test_a_wall_id_is_not_an_attenuation_object(connected, console):
    ready(console, _state())

    with pytest.raises(UniFiNotFoundError):
        await InnerSpaceAttenuationManager(connected).apply_remove_attenuation_objects(PLAN_A, [WALL_08])

    assert console.writes() == []


async def test_remove_sends_the_stored_objects(connected, console):
    ready(console, _state())

    result = await InnerSpaceAttenuationManager(connected).apply_remove_attenuation_objects(PLAN_A, [OBJECT])

    assert console.shape_changes() == [{"create": [], "update": [], "remove": [STORED_OBJECT], "mode": "2D"}]
    assert result.success is True and result.mutation_applied is True
    assert stored_shape(console, OBJECT) is None


async def test_caps_are_enforced_before_any_request(connected, console):
    ready(console, _state(), writes=2)
    manager = InnerSpaceAttenuationManager(connected)
    start = len(console.requests)
    ids = [f"00000000-0000-4000-8000-{n:012d}" for n in range(101)]

    with pytest.raises(ValidationError):
        await manager.apply_create_attenuation_objects(
            PLAN_A, [{"points": SQUARE, "variant": "car"}] * 101, unit="metric"
        )
    with pytest.raises(ValidationError):
        await manager.apply_update_attenuation_objects(
            PLAN_A, [{"id": i, "variant": "car"} for i in ids], unit="metric"
        )
    with pytest.raises(ValidationError):
        await manager.apply_remove_attenuation_objects(PLAN_A, ids[:51])
    assert console.requests[start:] == []

    result = await manager.apply_create_attenuation_objects(
        PLAN_A, [{"points": SQUARE, "variant": "car"}] * 100, unit="metric"
    )
    assert result.success is True
    assert len(console.shape_changes()[0]["create"]) == 100
    removed = await manager.apply_remove_attenuation_objects(PLAN_A, result.metadata["created_ids"][:50])
    assert removed.success is True
    assert len(console.shape_changes()[1]["remove"]) == 50


async def test_create_type_sends_the_probe_body(connected, console):
    ready(console, _state())

    result = await InnerSpaceAttenuationManager(connected).apply_create_attenuation_object_type("Pallets", 6, "#665544")

    (new_id,) = result.metadata["created_ids"]
    assert _type_writes(console) == [
        {
            "create": [
                {
                    "id": new_id,
                    "projectId": PROJECT_ID,
                    "name": "Pallets",
                    "attenuation": 6.0,
                    "color": "#665544",
                    "isDeleted": False,
                    "overridesVariant": None,
                    "bottomHeight": None,
                    "topHeight": None,
                }
            ],
            "update": [],
            "remove": [],
        }
    ]
    assert result.success is True and result.mutation_applied is True


async def test_update_type_sends_the_full_stored_type_with_its_usage(connected, console):
    ready(console, _state())

    result = await InnerSpaceAttenuationManager(connected).apply_update_attenuation_object_type(
        OBJECT_TYPE, attenuation_db=11
    )

    assert _type_writes(console) == [{"create": [], "update": [{**STORED_TYPE, "attenuation": 11.0}], "remove": []}]
    assert result.metadata["effects"] == {"objects_using_type": {"total": 1, "by_plan": {PLAN_A: 1}}}
    assert result.metadata["warnings"] == ["This type is project-wide: the change applies to 1 attenuation object"]
    assert result.success is True


async def test_update_type_equal_to_the_stored_type_sends_nothing(connected, console):
    ready(console, _state())

    result = await InnerSpaceAttenuationManager(connected).apply_update_attenuation_object_type(
        OBJECT_TYPE, name="Racking", color="#334455"
    )

    assert (result.success, result.mutation_applied) == (True, False)
    assert console.writes() == []


def test_type_update_fields_match_the_stored_type_keys():
    assert AttenuationObjectTypeUpdate.MUTABLE_FIELDS == {"name", "attenuation_db", "color"}


def test_type_remove_is_not_built():
    assert not [name for name in dir(InnerSpaceAttenuationManager) if "type" in name and "remove" in name]


# ---------------------------------------------------------------------------
# Units and frame, as for walls
# ---------------------------------------------------------------------------


async def test_imperial_attenuation_object_create(connected, console):
    ready(console, _state())
    feet = [{"x": p["x"] * 3.2808, "y": p["y"] * 3.2808} for p in SQUARE]

    result = await InnerSpaceAttenuationManager(connected).apply_create_attenuation_objects(
        PLAN_A, [{"points": feet, "variant": "car"}], unit="imperial"
    )

    (sent,) = console.shape_changes()[0]["create"]
    assert sent["position"] == [{"x": pytest.approx(p["x"]), "y": pytest.approx(p["y"]), "z": 0} for p in SQUARE_UNITS]
    assert result.success is True


async def test_attenuation_objects_on_a_shifted_map(connected, console):
    """Plan B's map is shifted: frame points are refused, plan units are taken as they are."""
    ready(console, _state(), writes=2)
    manager = InnerSpaceAttenuationManager(connected)

    with pytest.raises(UniFiValidationError, match="plan_units"):
        await manager.apply_create_attenuation_objects(PLAN_B, [{"points": SQUARE, "variant": "car"}], unit="metric")
    assert console.writes() == []

    units = [{"x": -10.0, "y": 5.0}, {"x": 10.0, "y": 5.0}, {"x": 10.0, "y": -5.0}, {"x": -10.0, "y": 5.0}]
    created = await manager.apply_create_attenuation_objects(
        PLAN_B, [{"points": units, "variant": "car"}], unit="metric", coordinates="plan_units"
    )
    assert created.success is True
    assert console.shape_changes()[-1]["create"][0]["position"] == [{**p, "z": 0} for p in units]
