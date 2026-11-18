"""Write coordinates: the read frame back to plan units, plan-unit passthrough, bounds and map alignment."""

import pytest
from unifi_core.exceptions import UniFiValidationError
from unifi_core.innerspace.frames import PlanFrame, from_plan_point, to_plan_point
from unifi_core.innerspace.models.floor_plans import PlanGeometry
from unifi_core.innerspace.units import FEET_PER_METRE

from tests.innerspace.helpers import PLAN_A, PLAN_B, floor_plan_rows, internal_state

OP = "create InnerSpace walls"
# W = 1000, H = 800 image pixels, 100 plan units per metre.
GEOMETRY = PlanGeometry(ppm=100.0, width_px=1000.0, height_px=800.0)
ALIGNED = PlanFrame(geometry=GEOMETRY, aligned=True)


def _to(x, y, *, unit="metric", frame=ALIGNED, coordinates="frame"):
    return to_plan_point(x, y, frame=frame, unit=unit, coordinates=coordinates, operation=OP)


@pytest.mark.parametrize(
    "unit, point, expected",
    [
        ("metric", (2.0, 3.0), (2.0 * 100 - 500, 400 - 3.0 * 100)),
        ("metric", (0.0, 0.0), (-500.0, 400.0)),
        ("metric", (10.0, 8.0), (500.0, -400.0)),
        ("imperial", (10.0, 5.0), (10.0 / FEET_PER_METRE * 100 - 500, 400 - 5.0 / FEET_PER_METRE * 100)),
    ],
)
def test_frame_inverses_literal(unit, point, expected):
    plan = _to(*point, unit=unit)

    assert plan == pytest.approx(expected, abs=1e-9)
    assert from_plan_point(*plan, geometry=GEOMETRY, unit=unit) == pytest.approx(point, abs=1e-4)


# An aligned plan at another scale, wider than tall: W = 1200, H = 500 image pixels, 80 plan units per metre.
WIDE = PlanFrame(geometry=PlanGeometry(ppm=80.0, width_px=1200.0, height_px=500.0), aligned=True)


@pytest.mark.parametrize(
    "unit, point, expected",
    [
        ("metric", (2.0, 3.0), (2.0 * 80 - 600, 250 - 3.0 * 80)),
        ("metric", (15.0, 6.25), (600.0, -250.0)),
        ("imperial", (10.0, 5.0), (10.0 / FEET_PER_METRE * 80 - 600, 250 - 5.0 / FEET_PER_METRE * 80)),
    ],
)
def test_frame_inverses_at_another_scale_and_aspect(unit, point, expected):
    plan = _to(*point, unit=unit, frame=WIDE)

    assert plan == pytest.approx(expected, abs=1e-9)
    assert from_plan_point(*plan, geometry=WIDE.geometry, unit=unit) == pytest.approx(point, abs=1e-4)


@pytest.mark.parametrize("point", [(15.01, 1.0), (1.0, 6.26)])
def test_frame_bounds_follow_the_image_at_another_scale(point):
    with pytest.raises(UniFiValidationError):
        _to(*point, frame=WIDE)


def test_imperial_edge_of_the_image_is_inside():
    # 1000 px at 100 px/m is 10 m, which is 32.808 ft by the app's factor.
    assert _to(10.0 * FEET_PER_METRE, 8.0 * FEET_PER_METRE, unit="imperial") == pytest.approx((500.0, -400.0))


@pytest.mark.parametrize("point", [(10.01, 1.0), (-0.01, 1.0), (1.0, 8.01), (1.0, -0.01)])
def test_frame_input_outside_the_image_is_refused(point):
    with pytest.raises(UniFiValidationError) as caught:
        _to(*point)

    assert str(caught.value).startswith(f"{OP}: ")
    assert str(point[0]) not in str(caught.value)


def test_plan_units_pass_through_without_unit_scaling_or_bounds():
    unaligned = PlanFrame(geometry=PlanGeometry(ppm=None, width_px=None, height_px=None), aligned=False)

    assert _to(-2500.5, 9000.0, unit="imperial", frame=unaligned, coordinates="plan_units") == (-2500.5, 9000.0)


@pytest.mark.parametrize(
    "frame",
    [
        PlanFrame(geometry=GEOMETRY, aligned=False),
        PlanFrame(geometry=PlanGeometry(ppm=0.0, width_px=1000.0, height_px=800.0), aligned=True),
        PlanFrame(geometry=PlanGeometry(ppm=100.0, width_px=None, height_px=800.0), aligned=True),
    ],
)
def test_frame_input_is_refused_on_a_shifted_map_or_without_geometry(frame):
    with pytest.raises(UniFiValidationError) as caught:
        _to(1.0, 1.0, frame=frame)

    assert "plan_units" in str(caught.value)


def _map(plan_id):
    return next(s for s in internal_state()["shapes"] if s["type"] == "map" and s["planId"] == plan_id)


def _row(plan_id):
    return next(r for r in floor_plan_rows() if r["id"] == plan_id)


def test_frame_from_a_plain_map_is_aligned():
    frame = PlanFrame.from_api(_row(PLAN_A), _map(PLAN_A))

    assert frame.aligned is True
    assert frame.geometry == GEOMETRY


@pytest.mark.parametrize(
    "change",
    [
        {"imageOffset": {"x": 5, "y": 0, "z": 0}},
        {"imageOffset": {"x": 0, "y": -1, "z": 0}},
        {"imageScale": {"x": 1, "y": 2, "z": 1}},
        {"imageScale": None},
        {"imageOffset": {"x": "0", "y": 0, "z": 0}},
    ],
)
def test_a_shifted_scaled_or_unreadable_map_is_not_aligned(change):
    assert PlanFrame.from_api(_row(PLAN_A), {**_map(PLAN_A), **change}).aligned is False


def test_a_plan_without_a_map_or_with_the_shifted_fixture_map_is_not_aligned():
    assert PlanFrame.from_api(_row(PLAN_A), None).aligned is False
    assert PlanFrame.from_api(_row(PLAN_B), _map(PLAN_B)).aligned is False
