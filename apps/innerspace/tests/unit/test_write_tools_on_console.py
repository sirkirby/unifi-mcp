"""One write tool per group, end to end: the tool, the real core manager, and the stateful loopback console.

The console holds the project recorded in the core fixtures, and the write routes change it the way
InnerSpace 1.4.3 does, so preview, confirm, read-back and a repeated confirm all run for real.
"""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import pytest

import unifi_innerspace_mcp.main as main_mod
from unifi_core.innerspace.managers.attenuation_manager import InnerSpaceAttenuationManager
from unifi_core.innerspace.managers.connection_manager import (
    INTEGRATION_PREFIX,
    PLAN_PATH_PREFIX,
    SHAPE_CHANGE_PATH,
    SYSTEM_PATH,
    WALL_TYPE_PATH,
)
from unifi_core.innerspace.managers.floor_plan_manager import InnerSpaceFloorPlanManager
from unifi_core.innerspace.managers.project_settings_manager import InnerSpaceProjectSettingsManager
from unifi_core.innerspace.managers.wall_manager import InnerSpaceWallManager
from unifi_core.innerspace.managers.wall_type_manager import InnerSpaceWallTypeManager
from unifi_core.operation_gate import reset_gate_registry_for_tests
from unifi_innerspace_mcp import runtime
from unifi_innerspace_mcp.tools import attenuation, floor_plans, project, wall_types, walls

FIXTURES = Path(__file__).resolve().parents[4] / "packages/unifi-core/tests/innerspace/fixtures"
PLAN_A = "00000000-0000-4000-8000-000000000003"
# Plan A: 1000 x 800 px at 100 plan units per metre, plain map; frame (1, 1)-(3, 1) m is inside the image.
WALL = {"x1": 1.0, "y1": 1.0, "x2": 3.0, "y2": 1.0, "variant": "drywall"}
POLYGON = {"points": [{"x": 1, "y": 1}, {"x": 2, "y": 1}, {"x": 2, "y": 2}, {"x": 1, "y": 1}], "variant": "car"}


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _rows():
    return deepcopy(_load("v1_floor_plans.json")["floor_plans"])


def _state():
    data = deepcopy(_load("v1_project.json")["data"])
    data["project"]["unit"] = "metric"
    return data


def _ready(console, *, previews=1, applies=1):
    """Serve the project from state; script the reads of ``previews`` previews and the checks of ``applies``."""
    console.load_project(_state())
    for _ in range(previews):
        console.reply("GET", SYSTEM_PATH, _load("system.json"))
        console.reply("GET", f"{INTEGRATION_PREFIX}/floor_plans", {"floor_plans": _rows()})
    for _ in range(applies):
        console.script_write(floor_plans=_rows())


async def test_create_walls_preview_confirm_and_a_repeated_confirm(monkeypatch, connected, console):
    monkeypatch.setattr(walls, "wall_manager", InnerSpaceWallManager(connected))
    _ready(console, applies=2)

    preview = await walls.innerspace_create_walls(PLAN_A, [WALL], "metric")
    assert preview["success"] is True and preview["requires_confirmation"] is True
    assert preview["preview"]["count"] == 1 and console.writes() == []

    applied = await walls.innerspace_create_walls(PLAN_A, [WALL], "metric", confirm=True)
    assert applied["success"] is True and applied["mutation_applied"] is True
    (wall_id,) = applied["created_ids"]
    assert any(shape["id"] == wall_id for shape in console.project["shapes"])

    again = await walls.innerspace_create_walls(PLAN_A, [WALL], "metric", confirm=True)
    assert again["success"] is True and again["mutation_applied"] is False
    assert again["noop"] == "already_applied" and again["created_ids"] == [wall_id]
    assert again["message"].startswith("Already applied:")
    assert len(console.shape_changes()) == 1
    console.assert_csrf()


async def test_a_lost_create_the_read_back_does_not_find_is_an_unknown_failure(monkeypatch, connected, console):
    """The answer was lost and the reads never show the wall: it may still land, so read before retrying."""
    monkeypatch.setattr(walls, "wall_manager", InnerSpaceWallManager(connected))
    _ready(console, previews=0)
    console.drop_connection("POST", SHAPE_CHANGE_PATH, apply=False)

    result = await walls.innerspace_create_walls(PLAN_A, [WALL], "metric", confirm=True)

    assert result["success"] is False and result["mutation_applied"] is None
    assert result["error"].startswith("Failed to create InnerSpace walls: the console did not answer")
    assert "read before retrying" in result["error"].lower()
    assert len(console.shape_changes()) == 1


async def test_a_partly_applied_create_is_a_failure_to_read_before_retrying(monkeypatch, connected, console):
    monkeypatch.setattr(walls, "wall_manager", InnerSpaceWallManager(connected))
    _ready(console, previews=0)
    console.mixed_batch(keep=1)
    second = {**WALL, "y1": 2.0, "y2": 2.0}

    result = await walls.innerspace_create_walls(PLAN_A, [WALL, second], "metric", confirm=True)

    assert result["success"] is False and result["mutation_applied"] is None
    assert "read before retrying" in result["error"].lower()


async def test_create_wall_type(monkeypatch, connected, console):
    monkeypatch.setattr(wall_types, "wall_type_manager", InnerSpaceWallTypeManager(connected))
    _ready(console)

    preview = await wall_types.innerspace_create_wall_type("Brick wall", 12.0, "#aa5500")
    applied = await wall_types.innerspace_create_wall_type("Brick wall", 12.0, "#aa5500", confirm=True)

    assert preview["preview"]["proposed"]["name"] == "Brick wall"
    assert applied["success"] is True and applied["mutation_applied"] is True
    (type_id,) = applied["created_ids"]
    assert [t["name"] for t in console.project["wallTypes"] if t["id"] == type_id] == ["Brick wall"]
    assert len(console.calls("POST", WALL_TYPE_PATH)) == 1


async def test_create_attenuation_objects(monkeypatch, connected, console):
    monkeypatch.setattr(attenuation, "attenuation_manager", InnerSpaceAttenuationManager(connected))
    _ready(console)

    preview = await attenuation.innerspace_create_attenuation_objects(PLAN_A, [POLYGON], "metric")
    applied = await attenuation.innerspace_create_attenuation_objects(PLAN_A, [POLYGON], "metric", confirm=True)

    assert preview["preview"]["count"] == 1
    assert applied["success"] is True and applied["mutation_applied"] is True
    (object_id,) = applied["created_ids"]
    stored = [s for s in console.project["shapes"] if s["id"] == object_id]
    assert [s["type"] for s in stored] == ["attenuationObject"]


async def test_rename_floor_plan(monkeypatch, connected, console):
    monkeypatch.setattr(floor_plans, "floor_plan_manager", InnerSpaceFloorPlanManager(connected))
    _ready(console)

    preview = await floor_plans.innerspace_rename_floor_plan(PLAN_A, "Upstairs")
    applied = await floor_plans.innerspace_rename_floor_plan(PLAN_A, "Upstairs", confirm=True)

    assert (preview["preview"]["current"], preview["preview"]["proposed"]) == (
        {"title": "Plan A"},
        {"title": "Upstairs"},
    )
    assert applied["success"] is True and applied["mutation_applied"] is True
    assert [r.body for r in console.calls("PATCH", f"{PLAN_PATH_PREFIX}/{PLAN_A}")] == [{"title": "Upstairs"}]


async def test_set_project_unit_and_a_repeat_that_changes_nothing(monkeypatch, connected, console):
    monkeypatch.setattr(project, "project_settings_manager", InnerSpaceProjectSettingsManager(connected))
    _ready(console, applies=2)

    preview = await project.innerspace_set_project_unit("imperial")
    applied = await project.innerspace_set_project_unit("imperial", confirm=True)
    again = await project.innerspace_set_project_unit("imperial", confirm=True)

    assert preview["success"] is True and preview["requires_confirmation"] is True
    assert applied["success"] is True and applied["mutation_applied"] is True
    assert console.project["project"]["unit"] == "imperial"
    assert again["success"] is True and again["mutation_applied"] is False
    assert again["message"].startswith("No change:")
    assert len(console.writes()) == 1


@pytest.mark.parametrize("entry", [{"isInstalled": False}, {"isRunning": False}], ids=["not-installed", "not-running"])
async def test_a_stopped_or_missing_app_refuses_the_write(monkeypatch, connected, console, entry):
    monkeypatch.setattr(walls, "wall_manager", InnerSpaceWallManager(connected))
    console.load_project(_state())
    app = {"name": "innerspace", "isInstalled": True, "isRunning": True, "version": "1.4.3", **entry}
    for _ in range(2):
        console.reply("GET", SYSTEM_PATH, {"apps": {"controllers": [app]}})

    previewed = await walls.innerspace_create_walls(PLAN_A, [WALL], "metric")
    result = await walls.innerspace_create_walls(PLAN_A, [WALL], "metric", confirm=True)

    assert result["success"] is False
    assert ("not installed" if "isInstalled" in entry else "not running") in result["error"]
    # The preview is refused too, with the same text.
    assert previewed == result
    assert console.writes() == []


@pytest.mark.parametrize("case", ["other-version", "no-version", "two-sites"])
async def test_a_write_runs_on_any_version_and_site_layout(monkeypatch, connected, console, case):
    monkeypatch.setattr(walls, "wall_manager", InnerSpaceWallManager(connected))
    console.load_project(_state())
    rows = _rows()
    if case == "two-sites":
        rows[1]["site_id"] = "00000000-0000-4000-8000-0000000000ff"
    console.script_write(version={"other-version": "1.5.0", "no-version": None}.get(case, "1.4.3"), floor_plans=rows)

    result = await walls.innerspace_create_walls(PLAN_A, [WALL], "metric", confirm=True)

    assert result["success"] is True and result["mutation_applied"] is True
    (wall_id,) = result["created_ids"]
    assert any(shape["id"] == wall_id for shape in console.project["shapes"])


async def test_set_plan_scale_runs_on_an_imperial_project(monkeypatch, connected, console):
    monkeypatch.setattr(floor_plans, "floor_plan_manager", InnerSpaceFloorPlanManager(connected))
    _ready(console, previews=0)
    console.project["project"]["unit"] = "imperial"
    # The read-back: 200 plan units over 2.5 m, as the console computes it.
    rows = _rows()
    rows[0]["ppm"] = 80.0
    console.reply("GET", f"{INTEGRATION_PREFIX}/floor_plans", {"floor_plans": rows})

    result = await floor_plans.innerspace_set_plan_scale(PLAN_A, 1.0, 1.0, 3.0, 1.0, 2.5, "metric", confirm=True)

    assert result["success"] is True and result["mutation_applied"] is True
    ((line,),) = [body["create"] for body in console.shape_changes()]
    assert line["scale"] == pytest.approx(2.5)


# A confirmed write whose hold budget runs out, through MCP dispatch: the shared gate wrapper and the
# console's operation gate are both in the path, with the gate's clock set by hand. After the fresh
# reads the gate's ticket records a request as sent; only the write layer knows the write never went
# out, and the tool must carry its ``mutation_applied: false``.


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


@pytest.fixture
def gate_clock(monkeypatch):
    monkeypatch.setattr(runtime.connection_manager, "host", "innerspace.test")
    monkeypatch.setattr(runtime.connection_manager, "port", 443)
    reset_gate_registry_for_tests()
    clock = _Clock()
    runtime.get_operation_gate().clock = clock
    yield clock
    reset_gate_registry_for_tests()


@pytest.mark.parametrize("spent_at", ["turn_start", "before_the_write"])
async def test_a_write_out_of_time_reports_nothing_applied(monkeypatch, connected, console, gate_clock, spent_at):
    console.load_project(_state())
    console.script_write(floor_plans=_rows())
    manager = InnerSpaceWallManager(connected)
    monkeypatch.setattr(walls, "wall_manager", manager)
    real_apply = manager.apply_create_walls
    real_request = connected.request

    async def spend_first(*args, **kwargs):
        gate_clock.value += 10_000
        return await real_apply(*args, **kwargs)

    async def spend_before_post(method, path, **kwargs):
        if method == "POST":
            gate_clock.value += 10_000
        return await real_request(method, path, **kwargs)

    if spent_at == "turn_start":
        monkeypatch.setattr(manager, "apply_create_walls", spend_first)
    else:
        monkeypatch.setattr(connected, "request", spend_before_post)

    result = await main_mod.server.call_tool(
        "innerspace_create_walls", {"plan_id": PLAN_A, "walls": [WALL], "unit": "metric", "confirm": True}
    )
    payload = json.loads(result.content[0].text)

    assert payload["success"] is False
    assert payload["mutation_applied"] is False
    assert "time budget ran out before the change was sent" in payload["error"]
    assert console.writes() == []
