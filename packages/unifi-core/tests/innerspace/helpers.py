"""Scripting helpers for the InnerSpace read tests."""

import json
from copy import deepcopy
from pathlib import Path

from unifi_core.innerspace.managers.connection_manager import INTEGRATION_PREFIX, INTERNAL_PROJECT_PATH, SYSTEM_PATH

FIXTURES = Path(__file__).parent / "fixtures"
PLAN_A = "00000000-0000-4000-8000-000000000003"
PLAN_B = "00000000-0000-4000-8000-000000000004"
PLAN_C = "00000000-0000-4000-8000-000000000005"
SITE = "00000000-0000-4000-8000-000000000001"
PROJECT_PATH = f"{INTEGRATION_PREFIX}/project"
PLANS_PATH = f"{INTEGRATION_PREFIX}/floor_plans"
AP_PATH = f"{INTEGRATION_PREFIX}/access_points"
SWITCH_PATH = f"{INTEGRATION_PREFIX}/switches"
INVENTORY_PATH = f"{INTEGRATION_PREFIX}/inventory"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def with_unit(unit):
    internal = deepcopy(load("internal_project.json"))
    internal["data"]["project"]["unit"] = unit
    return internal


def script_project(console, *, project=None, plans=None, unit="metric"):
    """Script the three reads behind a project read, plus a running app."""
    console.reply("GET", SYSTEM_PATH, load("system.json"))
    console.reply("GET", PROJECT_PATH, load("v1_project.json") if project is None else project)
    console.reply("GET", PLANS_PATH, load("v1_floor_plans.json") if plans is None else plans)
    if unit is not None:
        console.reply("GET", INTERNAL_PROJECT_PATH, with_unit(unit))


def script_placed(console, path, fixture, *, unit="metric"):
    console.reply("GET", SYSTEM_PATH, load("system.json"))
    console.reply("GET", path, load(fixture))
    console.reply("GET", PLANS_PATH, load("v1_floor_plans.json"))
    if unit is not None:
        console.reply("GET", INTERNAL_PROJECT_PATH, with_unit(unit))


def png_bytes(size=64):
    """A minimal valid PNG signature plus filler; only the leading bytes are inspected."""
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * size


def jpeg_bytes(size=64):
    return b"\xff\xd8\xff\xe0" + b"\x00" * size


PROJECT_ID = "00000000-0000-4000-8000-000000000002"
WALL_TYPE = "00000000-0000-4000-8000-000000000028"


def internal_state(unit="metric"):
    """The ``data`` member of an internal project read, for the stateful stub."""
    data = deepcopy(load("v1_project.json")["data"])
    data["project"]["unit"] = unit
    data["planScales"] = {PLAN_A: {"scale": 100.0, "height": 2.7}, PLAN_B: {"scale": 50.0, "height": 2.7}}
    return data


def floor_plan_rows():
    return deepcopy(load("v1_floor_plans.json")["floor_plans"])


def new_wall(shape_id, *, x=0.0, variant="drywall", plan_id=PLAN_A):
    """A wall create in the form recorded live on 1.4.3."""
    return {
        "id": shape_id,
        "type": "wall",
        "projectId": PROJECT_ID,
        "planId": plan_id,
        "position": [{"x": x, "y": 0, "z": 0}, {"x": x + 100, "y": 0, "z": 0}],
        "variant": variant,
        "status": 0,
    }


def stored_shape(console, shape_id):
    return next((s for s in console.project["shapes"] if s["id"] == shape_id), None)


UUID_SHAPED = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def script_preview(console, times=1):
    """Script the reads of ``times`` previews besides the internal project: the app check and the floor plans."""
    for _ in range(times):
        console.reply("GET", SYSTEM_PATH, load("system.json"))
        console.reply("GET", PLANS_PATH, {"floor_plans": floor_plan_rows()})


def ready(console, state=None, writes=1):
    """Load the stateful project and script the checks of ``writes`` applies."""
    console.load_project(internal_state() if state is None else state)
    for _ in range(writes):
        console.script_write(floor_plans=floor_plan_rows())


def stored_copy(shape_id):
    """The fixture's stored shape, as the stateful stub serves it."""
    return deepcopy(next(s for s in internal_state()["shapes"] if s["id"] == shape_id))
