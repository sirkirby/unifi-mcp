"""Guards on the synthetic InnerSpace fixtures: size, and documentation-only identifiers."""

import json
import re
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
JSON_FILES = sorted(FIXTURES.glob("*.json"))

# The project fixture carries three plans of shapes; every other file stays small.
PER_FILE_LIMIT = {"v1_project.json": 24 * 1024}
DEFAULT_FILE_LIMIT = 8 * 1024
DIRECTORY_LIMIT = 40 * 1024

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
COUNTER_UUID_RE = re.compile(r"00000000-0000-4000-8000-\d{12}")
MAC_RE = re.compile(r"\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b")
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
VERSION_STRINGS = {"1.4.3", "9.0.0"}

EXPECTED = {
    "system.json",
    "v1_project.json",
    "internal_project.json",
    "v1_floor_plans.json",
    "v1_access_points.json",
    "v1_switches.json",
    "v1_inventory.json",
    "errors.json",
}


def test_fixture_set_is_complete():
    assert {p.name for p in JSON_FILES} == EXPECTED


@pytest.mark.parametrize("path", JSON_FILES, ids=lambda p: p.name)
def test_fixture_is_small_sorted_and_pretty(path):
    text = path.read_text()
    assert len(text.encode()) < PER_FILE_LIMIT.get(path.name, DEFAULT_FILE_LIMIT)
    assert text == json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"


def test_directory_is_small():
    total = sum(p.stat().st_size for p in FIXTURES.iterdir() if p.is_file())
    assert total < DIRECTORY_LIMIT


@pytest.mark.parametrize("path", JSON_FILES, ids=lambda p: p.name)
def test_uuids_come_from_the_counter(path):
    for found in UUID_RE.findall(path.read_text()):
        assert COUNTER_UUID_RE.fullmatch(found), "uuid outside the counter set"


@pytest.mark.parametrize("path", JSON_FILES, ids=lambda p: p.name)
def test_macs_and_ips_are_documentation_values(path):
    text = path.read_text()
    for found in MAC_RE.findall(text):
        assert found.startswith("00:00:5e:00:53:"), "mac outside the documentation range"
    for found in IPV4_RE.findall(text):
        assert found.startswith("192.0.2.") or found in VERSION_STRINGS, "ip outside 192.0.2.0/24"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def test_shared_literals_hold():
    project = _load("v1_project.json")["data"]
    plans = {p["title"]: p for p in project["plans"]}
    fps = {f["name"]: f for f in _load("v1_floor_plans.json")["floor_plans"]}
    assert set(plans) == {"Plan A", "Plan B", "Plan C"}
    assert set(fps) == {"Plan A", "Plan B"}
    assert (fps["Plan A"]["ppm"], fps["Plan A"]["width"], fps["Plan A"]["height"]) == (100.0, 1000, 800)
    assert fps["Plan B"]["ppm"] == 50.0

    def on(plan, kind):
        return [s for s in project["shapes"] if s["planId"] == plans[plan]["id"] and s["type"] == kind]

    walls = on("Plan A", "wall")
    assert len(walls) == 3
    assert [(p["x"], p["y"]) for p in walls[0]["position"]] == [(-100, 100), (300, 100)]
    devices = on("Plan A", "device")
    assert len(devices) == 2
    assert devices[0]["position"][0] == {"x": -3.5, "y": 2.7, "z": -2.0}
    assert len(on("Plan A", "scale")) == 1
    (map_a,) = on("Plan A", "map")
    assert map_a["imageScale"] == {"x": 1, "y": 1, "z": 1}
    assert map_a["imageOffset"] == {"x": 0, "y": 0, "z": 0}
    (map_b,) = on("Plan B", "map")
    assert map_b["imageScale"]["x"] == 1.784
    assert any(map_b["imageOffset"][axis] for axis in "xyz")
    assert not on("Plan C", "scale")

    ap = _load("v1_access_points.json")["access_points"][0]
    assert ap["floor_plan_id"] == plans["Plan A"]["id"]
    assert (ap["x"], ap["y"], ap["height"], ap["mount"], ap["status"]) == (250.0, 300.0, 2.7, "ceiling", "online")

    assert _load("internal_project.json")["data"]["project"]["unit"] == "metric"
