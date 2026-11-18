"""Floor-plan title, floor attenuation and plan order: literal bodies from the 1.4.3 probe."""

import logging

import pytest
from pydantic import ValidationError
from unifi_core.exceptions import UniFiNotFoundError, UniFiValidationError
from unifi_core.innerspace.managers.connection_manager import (
    INTEGRATION_PREFIX,
    PLAN_ORDER_PATH,
    PLAN_PATH_PREFIX,
)
from unifi_core.innerspace.managers.floor_plan_manager import InnerSpaceFloorPlanManager

from tests.innerspace.helpers import (
    PLAN_A,
    PLAN_B,
    PLAN_C,
    floor_plan_rows,
    internal_state,
    ready,
    script_preview,
)

FLOOR_PLANS = f"{INTEGRATION_PREFIX}/floor_plans"
PLAN_D = "00000000-0000-4000-8000-000000000037"
SCALE_A = "00000000-0000-4000-8000-000000000013"
PLAN_A_PATH = f"{PLAN_PATH_PREFIX}/{PLAN_A}"


def _plan(console, plan_id):
    return next(p for p in console.project["plans"] if p["id"] == plan_id)


# ---------------------------------------------------------------------------
# Title
# ---------------------------------------------------------------------------


async def test_rename_sends_the_title_only(connected, console, caplog):
    ready(console)
    caplog.set_level(logging.DEBUG)

    result = await InnerSpaceFloorPlanManager(connected).apply_rename_floor_plan(PLAN_A, " Ground floor ")

    assert [(r.method, r.path, r.body) for r in console.writes()] == [("PATCH", PLAN_A_PATH, {"title": "Ground floor"})]
    assert result.success is True and result.mutation_applied is True
    assert _plan(console, PLAN_A)["title"] == "Ground floor"
    # The reply carries every shape of the project; none of it is logged or returned.
    assert "Ground floor" not in caplog.text and SCALE_A not in caplog.text
    assert SCALE_A not in repr(result.to_dict())
    console.assert_csrf()


async def test_rename_preview_and_no_op(connected, console):
    console.load_project(internal_state())
    script_preview(console)
    manager = InnerSpaceFloorPlanManager(connected)

    preview = await manager.preview_rename_floor_plan(PLAN_A, "Ground floor")
    assert (preview["current"], preview["proposed"], preview["no_op"]) == (
        {"title": "Plan A"},
        {"title": "Ground floor"},
        False,
    )

    console.script_write(floor_plans=floor_plan_rows())
    result = await manager.apply_rename_floor_plan(PLAN_A, "Plan A")
    assert (result.success, result.mutation_applied) == (True, False)
    assert console.writes() == []


async def test_rename_refuses_an_unknown_plan_and_a_long_title(connected, console):
    ready(console)
    manager = InnerSpaceFloorPlanManager(connected)

    with pytest.raises(ValidationError):
        await manager.apply_rename_floor_plan(PLAN_A, "x" * 33)
    with pytest.raises(UniFiNotFoundError):
        await manager.apply_rename_floor_plan("00000000-0000-4000-8000-0000000000ff", "Loft")
    assert console.writes() == []


# ---------------------------------------------------------------------------
# Floor attenuation
# ---------------------------------------------------------------------------


async def test_floor_attenuation_set_and_restore_to_null(connected, console):
    ready(console, writes=2)
    manager = InnerSpaceFloorPlanManager(connected)

    first = await manager.apply_set_floor_attenuation(PLAN_A, 25)
    second = await manager.apply_set_floor_attenuation(PLAN_A, None)

    assert [r.body for r in console.writes()] == [{"attenuation": 25.0}, {"attenuation": None}]
    assert first.success and second.success
    assert _plan(console, PLAN_A)["attenuation"] is None


async def test_floor_attenuation_preview_names_the_default(connected, console):
    console.load_project(internal_state())
    script_preview(console)

    preview = await InnerSpaceFloorPlanManager(connected).preview_set_floor_attenuation(PLAN_A, 30)

    assert (preview["current"], preview["proposed"]) == ({"attenuation_db": None}, {"attenuation_db": 30.0})
    assert preview["warnings"] == ["null means the app default of 20 dB"]


async def test_floor_attenuation_equal_to_the_stored_value_sends_nothing(connected, console):
    ready(console)

    result = await InnerSpaceFloorPlanManager(connected).apply_set_floor_attenuation(PLAN_A, None)

    assert (result.success, result.mutation_applied) == (True, False)
    assert console.writes() == []


# 1.4.3 refuses 0 and 0.5 with 400 ("Number must be greater than or equal to 1") and stores 1.
@pytest.mark.parametrize("value", [-1, 0, 0.5, 100, "20"])
async def test_floor_attenuation_is_bounded(connected, console, value):
    with pytest.raises(ValidationError):
        await InnerSpaceFloorPlanManager(connected).apply_set_floor_attenuation(PLAN_A, value)

    assert console.writes() == []


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------


async def test_reorder_sends_every_plan(connected, console):
    ready(console)

    result = await InnerSpaceFloorPlanManager(connected).apply_reorder_floor_plans([PLAN_D, PLAN_A, PLAN_B, PLAN_C])

    assert [(r.method, r.path, r.body) for r in console.writes()] == [
        (
            "PATCH",
            PLAN_ORDER_PATH,
            [
                {"id": PLAN_D, "ordering": 1},
                {"id": PLAN_A, "ordering": 2},
                {"id": PLAN_B, "ordering": 3},
                {"id": PLAN_C, "ordering": 4},
            ],
        )
    ]
    assert result.success is True and result.mutation_applied is True
    assert [_plan(console, p)["ordering"] for p in (PLAN_D, PLAN_A, PLAN_B, PLAN_C)] == [1, 2, 3, 4]


async def test_a_reorder_that_did_not_land_reads_back_as_not_applied(connected, console):
    """Plans that keep their place read the same either way, so only the moved ones decide the outcome."""
    ready(console)
    before = [_plan(console, p)["ordering"] for p in (PLAN_A, PLAN_B, PLAN_C, PLAN_D)]
    console.drop_connection("PATCH", PLAN_ORDER_PATH, apply=False)

    result = await InnerSpaceFloorPlanManager(connected).apply_reorder_floor_plans([PLAN_A, PLAN_C, PLAN_B, PLAN_D])

    assert result.mutation_applied is False
    assert [_plan(console, p)["ordering"] for p in (PLAN_A, PLAN_B, PLAN_C, PLAN_D)] == before


@pytest.mark.parametrize(
    "plans",
    [
        [PLAN_A, PLAN_B, PLAN_C],  # one missing
        [PLAN_A, PLAN_B, PLAN_C, PLAN_D, "00000000-0000-4000-8000-0000000000ff"],  # one unknown
    ],
)
async def test_reorder_requires_a_full_permutation(connected, console, plans):
    ready(console)

    with pytest.raises(UniFiValidationError, match="every floor plan"):
        await InnerSpaceFloorPlanManager(connected).apply_reorder_floor_plans(plans)

    assert console.writes() == []


async def test_reorder_rejects_a_repeated_plan_before_any_request(connected, console):
    with pytest.raises(ValidationError):
        await InnerSpaceFloorPlanManager(connected).apply_reorder_floor_plans([PLAN_A, PLAN_A, PLAN_B, PLAN_C])

    assert [r.path for r in console.requests] == ["/api/auth/login"]


async def test_reorder_preview_and_no_op(connected, console):
    state = internal_state()
    for ordering, plan in enumerate(state["plans"], start=1):
        plan["ordering"] = ordering
    order = [plan["id"] for plan in state["plans"]]
    console.load_project(state)
    script_preview(console)
    manager = InnerSpaceFloorPlanManager(connected)

    preview = await manager.preview_reorder_floor_plans(list(reversed(order)))
    assert preview["items"][0] == {"id": order[-1], "title": "Plan D", "current": 4, "proposed": 1}
    assert preview["effects"] == {"plans_moved": 4}

    console.script_write(floor_plans=floor_plan_rows())
    result = await manager.apply_reorder_floor_plans(order)
    assert (result.success, result.mutation_applied) == (True, False)
    assert console.writes() == []
