"""Access point, switch and inventory reads."""

import pytest
from pydantic import ValidationError
from unifi_core.exceptions import UniFiMalformedResponseError
from unifi_core.innerspace.managers.connection_manager import SYSTEM_PATH
from unifi_core.innerspace.managers.inventory_manager import InnerSpaceInventoryManager

from tests.innerspace.helpers import (
    AP_PATH,
    INVENTORY_PATH,
    PLAN_A,
    PLANS_PATH,
    SITE,
    SWITCH_PATH,
    load,
    script_placed,
    with_unit,
)


async def test_access_points_parse(connected, console):
    script_placed(console, AP_PATH, "v1_access_points.json")
    points = await InnerSpaceInventoryManager(connected).list_access_points()
    assert len(points) == 2
    first = points[0]
    assert (first.name, first.model, first.mac, first.serial, first.floor_plan_id) == (
        "Device 1",
        "Model AP",
        "00:00:5e:00:53:01",
        "SYN0000001",
        PLAN_A,
    )
    # pixels / ppm: 250/100 and 300/100 metres on Plan A; height is already metres.
    assert (first.x, first.y, first.height, first.azimuth, first.mount, first.status, first.unit) == (
        2.5,
        3.0,
        2.7,
        0.0,
        "ceiling",
        "online",
        "metric",
    )
    assert (points[1].x, points[1].y) == (8.0, 3.0)  # Plan B uses its own ppm of 50


async def test_access_points_imperial(connected, console):
    script_placed(console, AP_PATH, "v1_access_points.json", unit="imperial")
    first = (await InnerSpaceInventoryManager(connected).list_access_points())[0]
    assert (first.x, first.height, first.unit) == (pytest.approx(8.202), pytest.approx(8.85816, abs=1e-4), "imperial")


async def test_switches_parse(connected, console):
    script_placed(console, SWITCH_PATH, "v1_switches.json")
    switches = await InnerSpaceInventoryManager(connected).list_switches()
    assert len(switches) == 2
    assert (switches[0].name, switches[0].type, switches[0].x, switches[0].y, switches[0].unit) == (
        "Switch 1",
        "switch",
        1.0,
        1.0,
        "metric",
    )
    assert (switches[1].x, switches[1].y) == (1.0, 1.0)


async def test_inventory_parses_without_plans_or_unit(connected, console):
    console.reply("GET", SYSTEM_PATH, load("system.json"))
    console.reply("GET", INVENTORY_PATH, load("v1_inventory.json"))
    devices = await InnerSpaceInventoryManager(connected).list_inventory()
    assert len(devices) == 1
    assert (devices[0].name, devices[0].model, devices[0].mac, devices[0].serial) == (
        "Device 1",
        "Model AP",
        "00:00:5e:00:53:01",
        "SYN0000001",
    )
    assert [r.path for r in console.requests if r.path != "/api/auth/login"] == [SYSTEM_PATH, INVENTORY_PATH]


async def test_site_id_is_sent_as_site_id(connected, console):
    script_placed(console, AP_PATH, "v1_access_points.json")
    await InnerSpaceInventoryManager(connected).list_access_points(site_id=SITE)
    assert console.calls("GET", AP_PATH)[0].query == [("siteId", SITE)]
    assert console.calls("GET", PLANS_PATH)[0].query == [("siteId", SITE)]


@pytest.mark.parametrize("method", ["list_access_points", "list_switches", "list_inventory"])
async def test_invalid_site_id_refused_before_any_request(connected, console, method):
    with pytest.raises(ValidationError):
        await getattr(InnerSpaceInventoryManager(connected), method)(site_id="x/y")
    assert [r.path for r in console.requests] == ["/api/auth/login"]


@pytest.mark.parametrize("which", ["access_points", "switches", "inventory", "floor_plans"])
@pytest.mark.parametrize("damage", ["missing", "null", "non-list", "non-object-row"])
async def test_malformed_responses_not_empty(connected, console, which, damage):
    paths = {"access_points": AP_PATH, "switches": SWITCH_PATH, "inventory": INVENTORY_PATH, "floor_plans": PLANS_PATH}
    key = {"inventory": "devices"}.get(which, which)
    bad = {
        "missing": {},
        "null": {key: None},
        "non-list": {key: {"a": 1}},
        "non-object-row": {key: [*load(f"v1_{which}.json")[key], "row"]},
    }[damage]
    console.reply("GET", SYSTEM_PATH, load("system.json"))
    for name, path in paths.items():
        console.reply("GET", path, bad if name == which else load(f"v1_{name}.json"))
    console.reply("GET", "/proxy/innerspace/api/project", with_unit("metric"))
    manager = InnerSpaceInventoryManager(connected)
    call = {
        "access_points": manager.list_access_points,
        "switches": manager.list_switches,
        "inventory": manager.list_inventory,
        "floor_plans": manager.list_access_points,
    }[which]
    with pytest.raises(UniFiMalformedResponseError):
        await call()
