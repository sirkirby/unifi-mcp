"""Project reads: summary, walls and placed devices in the project unit."""

import pytest
from pydantic import ValidationError
from unifi_core.exceptions import UniFiMalformedResponseError, UniFiNotFoundError
from unifi_core.innerspace.managers.connection_manager import INTERNAL_PROJECT_PATH
from unifi_core.innerspace.managers.project_manager import InnerSpaceProjectManager

from tests.innerspace.helpers import PLAN_A, PLAN_C, PLANS_PATH, PROJECT_PATH, load, script_project, with_unit


async def test_summary_omits_shapes_unless_asked(connected, console):
    script_project(console)
    summary = await InnerSpaceProjectManager(connected).get_project()
    assert summary.shapes is None
    assert (summary.unit, summary.project.unit, summary.project.title) == ("metric", "metric", "Project 1")
    assert [p.title for p in summary.plans] == ["Plan A", "Plan B", "Plan C", "Plan D"]


async def test_summary_shape_counts_plan_a(connected, console):
    script_project(console)
    summary = await InnerSpaceProjectManager(connected).get_project()
    assert summary.plans[0].shape_counts == {"wall": 3, "device": 2, "scale": 1, "map": 1}
    assert [p.scale_missing for p in summary.plans] == [False, False, True, True]


async def test_summary_reads_3d_project_once(connected, console):
    script_project(console)
    await InnerSpaceProjectManager(connected).get_project()
    assert console.calls("GET", PROJECT_PATH)[0].query == [("mode", "3D")]
    assert len(console.calls("GET", PROJECT_PATH)) == 1


async def test_summary_with_shapes_drops_device_mac(connected, console):
    script_project(console)
    summary = await InnerSpaceProjectManager(connected).get_project(include_shapes=True)
    assert len(summary.shapes) == 21
    assert all("mac" not in s and "meta" not in s for s in summary.shapes)


async def test_list_walls_limit_truncates(connected, console):
    script_project(console)
    page = await InnerSpaceProjectManager(connected).list_walls(PLAN_A, limit=2)
    assert len(page.walls) == 2
    assert (page.total, page.truncated) == (3, True)


async def test_list_walls_within_limit(connected, console):
    script_project(console)
    page = await InnerSpaceProjectManager(connected).list_walls(PLAN_A, limit=10)
    assert (len(page.walls), page.total, page.truncated, page.scale_missing) == (3, 3, False, False)
    first = page.walls[0]
    assert (first.x1, first.y1, first.x2, first.y2, first.length) == (4.0, 3.0, 8.0, 3.0, 4.0)


async def test_list_placed_devices_plan_a(connected, console):
    script_project(console)
    page = await InnerSpaceProjectManager(connected).list_placed_devices(PLAN_A)
    assert (len(page.devices), page.total, page.truncated) == (2, 2, False)
    first = page.devices[0]
    assert (first.x, first.y, first.height, first.mount) == (1.5, 2.0, 2.7, "ceiling")


async def test_imperial_project_lengths(connected, console):
    script_project(console, unit="imperial")
    page = await InnerSpaceProjectManager(connected).list_walls(PLAN_A)
    assert page.unit == "imperial"
    assert page.walls[0].length == pytest.approx(13.1232)
    console.requests.clear()
    script_project(console, unit="imperial")
    devices = await InnerSpaceProjectManager(connected).list_placed_devices(PLAN_A)
    assert devices.devices[0].height == pytest.approx(8.85816, abs=1e-4)
    script_project(console, unit="imperial")
    summary = await InnerSpaceProjectManager(connected).get_project()
    assert summary.plans[0].scale_per_unit == pytest.approx(30.48, rel=1e-3)
    assert (summary.unit, summary.project.unit) == ("imperial", "imperial")


async def test_unit_argument_overrides_project_unit(connected, console):
    script_project(console, unit=None)
    page = await InnerSpaceProjectManager(connected).list_walls(PLAN_A, unit="imperial")
    assert page.walls[0].length == pytest.approx(13.1232)
    assert console.calls("GET", INTERNAL_PROJECT_PATH) == []


@pytest.mark.parametrize("change", [0, None, -5, "absent", "no-width", "no-height"])
async def test_plan_without_scale(connected, console, change):
    plans = load("v1_floor_plans.json")
    row = plans["floor_plans"][0]
    if change == "absent":
        plans["floor_plans"] = [p for p in plans["floor_plans"] if p["id"] != PLAN_A]
    elif change == "no-width":
        del row["width"]
    elif change == "no-height":
        del row["height"]
    else:
        row["ppm"] = change
    script_project(console, plans=plans)
    walls = await InnerSpaceProjectManager(connected).list_walls(PLAN_A)
    assert walls.scale_missing is True
    assert len(walls.walls) == 3
    assert all((w.x1, w.y1, w.x2, w.y2, w.length) == (None,) * 5 for w in walls.walls)
    script_project(console, plans=plans)
    devices = await InnerSpaceProjectManager(connected).list_placed_devices(PLAN_A)
    assert devices.scale_missing is True
    assert len(devices.devices) == 2
    assert devices.devices[0].height == 2.7
    assert (devices.devices[0].x, devices.devices[0].y) == (None, None)


async def test_plan_in_project_but_not_in_floor_plans(connected, console):
    script_project(console)
    page = await InnerSpaceProjectManager(connected).list_walls(PLAN_C)
    assert page.scale_missing is True


async def test_unknown_plan_is_not_found(connected, console):
    script_project(console)
    with pytest.raises(UniFiNotFoundError) as caught:
        await InnerSpaceProjectManager(connected).list_walls("00000000-0000-4000-8000-000000009999")
    assert str(caught.value) == "list InnerSpace walls: no such floor plan"
    assert caught.value.identifier == "00000000-0000-4000-8000-000000009999"


@pytest.mark.parametrize("plan_id", ["../x", "a/b", "", "a?b"])
async def test_invalid_plan_id_refused_before_any_request(connected, console, plan_id):
    with pytest.raises(ValidationError):
        await InnerSpaceProjectManager(connected).list_walls(plan_id)
    assert [r.path for r in console.requests] == ["/api/auth/login"]


@pytest.mark.parametrize("key", ["plans", "shapes"])
async def test_project_without_plans_or_shapes_is_malformed_not_missing(connected, console, key):
    project = load("v1_project.json")
    del project["data"][key]
    script_project(console, project=project)
    with pytest.raises(UniFiMalformedResponseError):
        await InnerSpaceProjectManager(connected).list_walls(PLAN_A)


@pytest.mark.parametrize("which", ["project", "floor_plans", "internal"])
@pytest.mark.parametrize("damage", ["missing", "null", "non-list"])
async def test_malformed_project_reads(connected, console, which, damage):
    project, plans, internal = load("v1_project.json"), load("v1_floor_plans.json"), with_unit("metric")
    if which == "project":
        if damage == "missing":
            del project["data"]["project"]
        else:
            project["data"]["project"] = None if damage == "null" else []
    elif which == "floor_plans":
        if damage == "missing":
            plans = {}
        else:
            plans["floor_plans"] = None if damage == "null" else {}
    else:
        if damage == "missing":
            del internal["data"]["project"]["unit"]
        else:
            internal["data"]["project"]["unit"] = None if damage == "null" else ["metric"]
    console.reply("GET", "/api/system", load("system.json"))
    console.reply("GET", PROJECT_PATH, project)
    console.reply("GET", PLANS_PATH, plans)
    console.reply("GET", INTERNAL_PROJECT_PATH, internal)
    with pytest.raises(UniFiMalformedResponseError):
        await InnerSpaceProjectManager(connected).get_project()
