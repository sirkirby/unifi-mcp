"""Every read checks that InnerSpace is running before it asks for data."""

import pytest
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.innerspace.managers.connection_manager import (
    INTERNAL_PROJECT_PATH,
    SYSTEM_PATH,
    InnerSpaceUnavailableError,
)
from unifi_core.innerspace.managers.floor_plan_manager import InnerSpaceFloorPlanManager
from unifi_core.innerspace.managers.inventory_manager import InnerSpaceInventoryManager
from unifi_core.innerspace.managers.project_manager import InnerSpaceProjectManager

from tests.innerspace.helpers import (
    AP_PATH,
    INVENTORY_PATH,
    PLAN_A,
    PLANS_PATH,
    PROJECT_PATH,
    SWITCH_PATH,
    load,
    script_placed,
    script_project,
    with_unit,
)

READS = {
    "get_project": (InnerSpaceProjectManager, (), {}),
    "list_walls": (InnerSpaceProjectManager, (PLAN_A,), {}),
    "list_placed_devices": (InnerSpaceProjectManager, (PLAN_A,), {}),
    "list_floor_plans": (InnerSpaceFloorPlanManager, (), {}),
    "get_plan_asset": (InnerSpaceFloorPlanManager, (PLAN_A,), {}),
    "list_access_points": (InnerSpaceInventoryManager, (), {}),
    "list_switches": (InnerSpaceInventoryManager, (), {}),
    "list_inventory": (InnerSpaceInventoryManager, (), {}),
}


def _stopped():
    system = load("system.json")
    system["apps"]["controllers"][0]["isRunning"] = False
    return system


@pytest.mark.parametrize("name", READS)
async def test_reads_fail_closed_when_app_stopped(connected, console, name):
    manager_class, args, kwargs = READS[name]
    console.reply("GET", SYSTEM_PATH, _stopped())
    with pytest.raises(InnerSpaceUnavailableError) as caught:
        await getattr(manager_class(connected), name)(*args, **kwargs)
    assert not isinstance(caught.value, UniFiNotFoundError)
    assert [r.path for r in console.requests if r.path != "/api/auth/login"] == [SYSTEM_PATH]


def _script(console, name):
    if name in ("get_project", "list_walls", "list_placed_devices"):
        script_project(console)
    elif name in ("list_floor_plans", "get_plan_asset"):
        console.reply("GET", SYSTEM_PATH, load("system.json"))
        console.reply("GET", PLANS_PATH, load("v1_floor_plans.json"))
        console.reply("GET", PROJECT_PATH, load("v1_project.json"))
        console.reply("GET", INTERNAL_PROJECT_PATH, with_unit("metric"))
    elif name == "list_inventory":
        console.reply("GET", SYSTEM_PATH, load("system.json"))
        console.reply("GET", INVENTORY_PATH, load("v1_inventory.json"))
    else:
        path, fixture = (
            (AP_PATH, "v1_access_points.json")
            if name == "list_access_points"
            else (
                SWITCH_PATH,
                "v1_switches.json",
            )
        )
        script_placed(console, path, fixture)


@pytest.mark.parametrize("name", READS)
async def test_every_read_checks_status_first(connected, console, name):
    manager_class, args, kwargs = READS[name]
    _script(console, name)
    await getattr(manager_class(connected), name)(*args, **kwargs)
    paths = [r.path for r in console.requests if r.path != "/api/auth/login"]
    assert paths[0] == SYSTEM_PATH
    assert paths.count(SYSTEM_PATH) == 1
