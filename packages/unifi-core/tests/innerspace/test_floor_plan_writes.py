"""Floor-plan title, floor attenuation, plan order and plan scale: literal bodies from the 1.4.3 probe."""

import logging
import re

import pytest
from pydantic import ValidationError
from unifi_core.exceptions import UniFiNotFoundError, UniFiValidationError
from unifi_core.innerspace.managers._layout import WritePlan, WriteRequest, apply_write, shape_change_body
from unifi_core.innerspace.managers._writes import InnerSpaceWriteRefusedError
from unifi_core.innerspace.managers.connection_manager import (
    INTEGRATION_PREFIX,
    PLAN_ORDER_PATH,
    PLAN_PATH_PREFIX,
    SHAPE_CHANGE_PATH,
    SYSTEM_PATH,
)
from unifi_core.innerspace.managers.floor_plan_manager import InnerSpaceFloorPlanManager
from unifi_core.innerspace.models.writes import PlanScaleInput

from tests.innerspace.helpers import (
    PLAN_A,
    PLAN_B,
    PLAN_C,
    PROJECT_ID,
    UUID_SHAPED,
    floor_plan_rows,
    internal_state,
    load,
    ready,
    script_preview,
    stored_copy,
    stored_shape,
)

FLOOR_PLANS = f"{INTEGRATION_PREFIX}/floor_plans"
PLAN_D = "00000000-0000-4000-8000-000000000037"
SCALE_A = "00000000-0000-4000-8000-000000000013"
PLAN_A_PATH = f"{PLAN_PATH_PREFIX}/{PLAN_A}"
# Plan A: 1000 x 800 px, 100 per metre, plain map. Frame (1, 1)-(3, 1) m is (-400, 300)-(-200, 300), 200 px long.
LINE = {"x1": 1.0, "y1": 1.0, "x2": 3.0, "y2": 1.0}


def _plan(console, plan_id):
    return next(p for p in console.project["plans"] if p["id"] == plan_id)


def _script_scale_read_back(console, ppm):
    """The floor-plan rows a scale write reads back, with plan A's ``ppm`` as the console computed it."""
    rows = floor_plan_rows()
    rows[0]["ppm"] = ppm
    console.reply("GET", FLOOR_PLANS, {"floor_plans": rows})


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


# ---------------------------------------------------------------------------
# Scale
# ---------------------------------------------------------------------------


async def test_set_scale_replaces_the_scale_line_in_one_call(connected, console):
    ready(console)
    _script_scale_read_back(console, 80.0)

    result = await InnerSpaceFloorPlanManager(connected).apply_set_plan_scale(PLAN_A, **LINE, length=2.5, unit="metric")

    (new_id,) = result.metadata["created_ids"]
    assert console.shape_changes() == [
        {
            "create": [
                {
                    "id": new_id,
                    "type": "scale",
                    "projectId": PROJECT_ID,
                    "planId": PLAN_A,
                    "scale": 2.5,
                    "height": 2.7,
                    "position": [{"x": -400.0, "y": 300.0, "z": 0}, {"x": -200.0, "y": 300.0, "z": 0}],
                    "status": 0,
                    "defaultScale": False,
                    "defaultHeight": True,
                    "computedScale": None,
                }
            ],
            "update": [],
            "remove": [stored_copy(SCALE_A)],
            "mode": "2D",
        }
    ]
    assert result.success is True and result.mutation_applied is True
    assert result.metadata["effects"] == {"devices_shifted": 2}
    assert result.metadata["warnings"]
    assert stored_shape(console, SCALE_A) is None
    assert console.project["planScales"][PLAN_A]["scale"] == pytest.approx(80.0)
    console.assert_csrf()


async def test_set_scale_preview_counts_the_devices_that_shift(connected, console):
    # Feet in, on a metric project: the project unit stays metric, the arguments carry their own unit.
    console.load_project(internal_state())
    script_preview(console, times=2)
    manager = InnerSpaceFloorPlanManager(connected)
    # 3.2808 ft = 1 m: the same line in feet, 8.202 ft = 2.5 m long.
    line = {"x1": 3.2808, "y1": 3.2808, "x2": 9.8424, "y2": 3.2808}

    preview = await manager.preview_set_plan_scale(PLAN_A, **line, length=8.202, unit="imperial")

    assert preview == await manager.preview_set_plan_scale(PLAN_A, **line, length=8.202, unit="imperial")
    assert preview["effects"] == {"devices_shifted": 2}
    assert preview["current"]["scale_per_unit"] == pytest.approx(100 / 3.2808)
    assert preview["proposed"]["scale_per_unit"] == pytest.approx(80 / 3.2808, rel=1e-6)
    assert preview["current"]["line"] == {"x1": 16.404, "y1": 13.1232, "x2": 19.6848, "y2": 13.1232}
    assert preview["proposed"]["line"] == line
    assert "2 devices" in preview["warnings"][0]
    assert set(re.findall(UUID_SHAPED, repr(preview))) == {PLAN_A}
    assert console.writes() == []


async def test_set_scale_preview_shows_the_stored_length_unrounded(connected, console):
    """The current length is what an undo sends back, so it is not cut to display precision."""
    state = internal_state()
    next(s for s in state["shapes"] if s["id"] == SCALE_A)["scale"] = 1.234567891
    console.load_project(state)
    script_preview(console)

    preview = await InnerSpaceFloorPlanManager(connected).preview_set_plan_scale(
        PLAN_A, **LINE, length=2.5, unit="metric"
    )

    assert preview["current"]["length"] == pytest.approx(1.234567891, rel=1e-12)


async def test_set_scale_equal_to_the_stored_line_sends_nothing(connected, console):
    ready(console)
    # The stored line is (0, 0)-(100, 0) plan units with scale 100.
    same = {"x1": 0.0, "y1": 0.0, "x2": 100.0, "y2": 0.0}

    result = await InnerSpaceFloorPlanManager(connected).apply_set_plan_scale(
        PLAN_A, **same, length=100.0, unit="metric", coordinates="plan_units"
    )

    assert (result.success, result.mutation_applied) == (True, False)
    assert console.writes() == []


async def test_a_scale_write_that_did_not_land_reads_back_as_not_applied_when_the_scale_is_unchanged(
    connected, console
):
    """A line moved at the same pixels per metre leaves the computed scale equal either way: it decides nothing."""
    ready(console)
    _script_scale_read_back(console, 100.0)
    console.drop_connection("POST", SHAPE_CHANGE_PATH, apply=False)
    # The stored line is 100 plan units at 100 per metre; this one is moved, at the same scale.
    moved = {"x1": 0.0, "y1": 10.0, "x2": 100.0, "y2": 10.0}

    result = await InnerSpaceFloorPlanManager(connected).apply_set_plan_scale(
        PLAN_A, **moved, length=1.0, unit="metric", coordinates="plan_units"
    )

    assert result.mutation_applied is False
    assert stored_shape(console, SCALE_A) is not None


@pytest.mark.parametrize("shapes", [0, 2])
async def test_set_scale_needs_exactly_one_scale_line(connected, console, shapes):
    state = internal_state()
    scale = next(s for s in state["shapes"] if s["id"] == SCALE_A)
    state["shapes"] = [s for s in state["shapes"] if s["id"] != SCALE_A]
    if shapes == 2:
        state["shapes"] += [scale, {**scale, "id": "00000000-0000-4000-8000-0000000000d1"}]
    ready(console, state)

    with pytest.raises(InnerSpaceWriteRefusedError):
        await InnerSpaceFloorPlanManager(connected).apply_set_plan_scale(PLAN_A, **LINE, length=2.0, unit="metric")

    assert console.writes() == []


async def test_set_scale_refuses_frame_points_on_a_shifted_map(connected, console):
    ready(console)

    with pytest.raises(UniFiValidationError, match="plan_units"):
        await InnerSpaceFloorPlanManager(connected).apply_set_plan_scale(PLAN_B, **LINE, length=2.0, unit="metric")

    assert console.writes() == []


async def test_only_the_scale_write_carries_scale_shapes_and_none_carries_a_map(connected, console):
    ready(console)
    _script_scale_read_back(console, 80.0)
    await InnerSpaceFloorPlanManager(connected).apply_set_plan_scale(PLAN_A, **LINE, length=2.5, unit="metric")

    (body,) = console.shape_changes()
    assert [s["type"] for s in body["create"] + body["remove"]] == ["scale", "scale"]
    assert body["update"] == []


async def test_a_retried_scale_in_the_frame_finds_its_line_and_sends_nothing(connected, console):
    ready(console)
    rows = floor_plan_rows()
    # After the first call the console reports the new scale, so the same frame points convert differently.
    rows[0]["ppm"] = 80.0
    console.script_write(floor_plans=rows)
    manager = InnerSpaceFloorPlanManager(connected)
    first = await manager.apply_set_plan_scale(PLAN_A, **LINE, length=2.5, unit="metric")
    console.script_write(floor_plans=rows)

    console.reply("GET", SYSTEM_PATH, load("system.json"))
    console.reply("GET", FLOOR_PLANS, {"floor_plans": rows})
    preview = await manager.preview_set_plan_scale(PLAN_A, **LINE, length=2.5, unit="metric")
    retry = await manager.apply_set_plan_scale(PLAN_A, **LINE, length=2.5, unit="metric")

    assert first.mutation_applied is True
    assert preview["no_op"] is True
    assert (retry.success, retry.mutation_applied) == (True, False)
    assert retry.metadata["already_applied"] is True
    assert len(console.shape_changes()) == 1


async def test_a_scale_line_from_an_identical_call_with_another_length_is_refused(connected, console):
    ready(console)
    rows = floor_plan_rows()
    rows[0]["ppm"] = 80.0
    console.script_write(floor_plans=rows)
    _script_scale_read_back(console, 80.0)
    manager = InnerSpaceFloorPlanManager(connected)
    first = await manager.apply_set_plan_scale(PLAN_A, **LINE, length=2.5, unit="metric")
    # Someone changes the stored length of that line in the app; the same call again cannot replace its own line.
    line = stored_shape(console, first.metadata["created_ids"][0])
    line["scale"] = 3.0

    with pytest.raises(InnerSpaceWriteRefusedError, match="identical earlier call"):
        await manager.apply_set_plan_scale(PLAN_A, **LINE, length=2.5, unit="metric")

    assert len(console.shape_changes()) == 1


async def test_apply_refuses_a_body_that_creates_and_removes_one_id(connected, console):
    ready(console)

    def build(snapshot):
        def request(ids):
            shape = stored_copy(SCALE_A)
            body = shape_change_body(create=[{**shape, "id": ids[0]}], remove=[{**shape, "id": ids[0]}], scale=True)
            return WriteRequest("POST", SHAPE_CHANGE_PATH, body, lambda after: {ids[0]: False}, [ids[0]])

        return WritePlan(preview={}, request=request, new_ids=1)

    args = PlanScaleInput(plan_id=PLAN_A, **LINE, length=2.5, unit="metric")
    with pytest.raises(InnerSpaceWriteRefusedError, match="also changes or removes"):
        await apply_write(connected, operation="op", tool="innerspace_set_plan_scale", args=args, build=build)

    assert console.writes() == []


# The same physical line, 1-3 m along y = 1 m and 2.5 m long, in feet (3.2808 ft = 1 m).
LINE_FEET = {"x1": 3.2808, "y1": 3.2808, "x2": 9.8424, "y2": 3.2808}


@pytest.mark.parametrize(
    "line, length, unit", [(LINE, 2.5, "metric"), (LINE_FEET, 8.202, "imperial")], ids=["metres", "feet"]
)
async def test_set_scale_on_an_imperial_project_sends_what_a_metric_project_sends(
    connected, console, line, length, unit
):
    """The project unit is display only, so it never changes the stored scale line.

    The console keeps every stored length in metres and plan units whatever the project unit says: a
    unit change rewrites no shape, and every read converts metres to feet only for display. So on an
    imperial project the line goes out exactly as on a metric project: positions in plan units and
    ``scale`` in metres (2.5), never in feet (8.202). Only the call's own ``unit`` argument is converted.
    """
    ready(console, internal_state("imperial"))
    _script_scale_read_back(console, 80.0)

    result = await InnerSpaceFloorPlanManager(connected).apply_set_plan_scale(PLAN_A, **line, length=length, unit=unit)

    ((sent,),) = [body["create"] for body in console.shape_changes()]
    assert sent["scale"] == pytest.approx(2.5)
    assert [(p["x"], p["y"]) for p in sent["position"]] == [
        (pytest.approx(-400.0), pytest.approx(300.0)),
        (pytest.approx(-200.0), pytest.approx(300.0)),
    ]
    assert (result.success, result.mutation_applied) == (True, True)
    assert console.project["planScales"][PLAN_A]["scale"] == pytest.approx(80.0)


@pytest.mark.parametrize("project_unit", ["metric", "imperial"])
@pytest.mark.parametrize(
    "ppm, applied",
    [(80.0, True), (80.05, True), (80.2, False), (100.0, False), (200 / (2.5 * 0.3048), False)],
    ids=["equal", "within-0.1%", "off-0.25%", "unchanged", "length-taken-as-feet"],
)
async def test_set_scale_reads_back_the_scale_the_console_computes(connected, console, project_unit, ppm, applied):
    """The stored line only echoes what was sent; the plan's ``ppm`` is what the console made of it.

    200 plan units over 2.5 m is 80 per metre on either project unit. Within 0.1 % is applied; the old 100,
    or 200 over 2.5 ft, is an unknown outcome, never success.
    """
    ready(console, internal_state(project_unit))
    _script_scale_read_back(console, ppm)

    result = await InnerSpaceFloorPlanManager(connected).apply_set_plan_scale(PLAN_A, **LINE, length=2.5, unit="metric")

    assert (result.success, result.mutation_applied) == ((True, True) if applied else (False, None))
    assert ("floor_plan_scale" in result.metadata["missing"]) is not applied
    assert len(console.shape_changes()) == 1


@pytest.mark.parametrize(
    "drift, applied",
    [(1 + 3.6e-9, True), (1 + 1e-4, False)],
    ids=["float-round-trip", "real-difference"],
)
async def test_set_scale_read_back_absorbs_a_float_round_trip_in_the_stored_length(
    connected, console, monkeypatch, drift, applied
):
    """The console may store the length a few parts per billion off the metres sent; 1e-4 off is not the same."""
    import innerspace_stub

    real = innerspace_stub._apply_shape

    def drifting(kind, item, stored):
        real(kind, item, stored)
        if kind == "create" and item.get("type") == "scale":
            stored[item["id"]]["scale"] = item["scale"] * drift

    monkeypatch.setattr(innerspace_stub, "_apply_shape", drifting)
    ready(console, internal_state("imperial"))
    _script_scale_read_back(console, 80.0)

    result = await InnerSpaceFloorPlanManager(connected).apply_set_plan_scale(PLAN_A, **LINE, length=2.5, unit="metric")

    assert (result.success, result.mutation_applied) == ((True, True) if applied else (False, None))
    assert len(console.shape_changes()) == 1
