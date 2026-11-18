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
