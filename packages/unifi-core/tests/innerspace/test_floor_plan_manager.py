"""Floor plan reads."""

import pytest
from pydantic import ValidationError
from unifi_core.exceptions import UniFiMalformedResponseError
from unifi_core.innerspace.managers.connection_manager import INTERNAL_PROJECT_PATH, SYSTEM_PATH
from unifi_core.innerspace.managers.floor_plan_manager import InnerSpaceFloorPlanManager

from tests.innerspace.helpers import PLAN_A, PLAN_B, PLANS_PATH, PROJECT_PATH, SITE, load, with_unit


def _script(console, unit="metric", plans=None):
    console.reply("GET", SYSTEM_PATH, load("system.json"))
    console.reply("GET", PLANS_PATH, load("v1_floor_plans.json") if plans is None else plans)
    console.reply("GET", PROJECT_PATH, load("v1_project.json"))
    console.reply("GET", INTERNAL_PROJECT_PATH, with_unit(unit))


async def test_list_floor_plans(connected, console):
    _script(console)
    plans = await InnerSpaceFloorPlanManager(connected).list_floor_plans()
    assert len(plans) == 2
    first = plans[0]
    assert (first.id, first.name, first.floor_number, first.scale_per_unit, first.unit) == (
        PLAN_A,
        "Plan A",
        1,
        100.0,
        "metric",
    )
    assert (first.width_px, first.height_px, first.site_id) == (1000.0, 800.0, SITE)
    assert first.image_filename == "00000000-0000-4000-8000-000000000014.png"
    assert (first.image_scale, first.image_offset) == (1.0, (0.0, 0.0))


async def test_scaled_plan_keeps_the_vendor_frame_and_exposes_the_transform(connected, console):
    """Plan B's map is scaled and offset: the plan keeps the vendor's numbers and reports both."""
    _script(console)
    plans = {p.id: p for p in await InnerSpaceFloorPlanManager(connected).list_floor_plans()}
    plan_b = plans[PLAN_B]
    assert (plan_b.image_scale, plan_b.image_offset) == (1.784, (12.5, -7.5))
    # Scale is the vendor's ppm, unchanged by the image scale.
    assert (plan_b.scale_per_unit, plan_b.width_px, plan_b.height_px) == (50.0, 800.0, 600.0)


@pytest.mark.parametrize("bad_id", [["list"], {"k": 1}, 7, None])
async def test_row_with_a_non_string_id_is_read_without_a_map(connected, console, bad_id):
    plans = load("v1_floor_plans.json")
    plans["floor_plans"][0]["id"] = bad_id
    _script(console, plans=plans)
    first = (await InnerSpaceFloorPlanManager(connected).list_floor_plans())[0]
    assert (first.id, first.image_scale, first.image_offset) == (None, None, None)


async def test_list_floor_plans_imperial(connected, console):
    _script(console, unit="imperial")
    plans = await InnerSpaceFloorPlanManager(connected).list_floor_plans()
    assert plans[0].scale_per_unit == pytest.approx(30.48, rel=1e-3)
    assert plans[0].unit == "imperial"


async def test_site_id_is_sent_as_site_id(connected, console):
    _script(console)
    await InnerSpaceFloorPlanManager(connected).list_floor_plans(site_id=SITE)
    assert console.calls("GET", PLANS_PATH)[0].query == [("siteId", SITE)]


async def test_invalid_site_id_refused_before_any_request(connected, console):
    with pytest.raises(ValidationError):
        await InnerSpaceFloorPlanManager(connected).list_floor_plans(site_id="a/../b")
    assert [r.path for r in console.requests] == ["/api/auth/login"]


@pytest.mark.parametrize("plans", [{}, {"floor_plans": None}, {"floor_plans": {}}, [], {"floor_plans": [None]}])
async def test_malformed_floor_plans_are_not_empty(connected, console, plans):
    _script(console, plans=plans)
    with pytest.raises(UniFiMalformedResponseError):
        await InnerSpaceFloorPlanManager(connected).list_floor_plans()
