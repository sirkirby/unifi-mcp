"""InnerSpace response models and input models, built from the synthetic fixtures."""

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError
from unifi_core.exceptions import UniFiMalformedResponseError
from unifi_core.innerspace.models._coerce import finite
from unifi_core.innerspace.models.devices import (
    access_point_from_api,
    inventory_device_from_api,
    switch_from_api,
)
from unifi_core.innerspace.models.floor_plans import PlanGeometry, floor_plan_from_api, plan_geometry_from_api
from unifi_core.innerspace.models.project import (
    placed_devices_from_api,
    project_summary_from_api,
    walls_from_api,
)
from unifi_core.innerspace.models.reads import (
    InnerSpaceAssetInput,
    InnerSpaceListInput,
    InnerSpacePlanInput,
    InnerSpaceProjectInput,
    InnerSpaceSiteInput,
    InnerSpaceUnitInput,
)
from unifi_core.innerspace.models.status import app_status_from_api

FIXTURES = Path(__file__).parent / "fixtures"
PLAN_A = "00000000-0000-4000-8000-000000000003"
PLAN_B = "00000000-0000-4000-8000-000000000004"
PLAN_C = "00000000-0000-4000-8000-000000000005"


def load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def project():
    return load("v1_project.json")


@pytest.fixture
def geometry():
    rows = load("v1_floor_plans.json")["floor_plans"]
    return {row["id"]: plan_geometry_from_api(row) for row in rows}


def geo(geometry, plan_id):
    return geometry.get(plan_id, PlanGeometry(ppm=None, width_px=None, height_px=None))


def test_walls_plan_a_metric(project, geometry):
    page = walls_from_api(project, PLAN_A, geometry=geo(geometry, PLAN_A), unit="metric", limit=500)
    assert len(page.walls) == 3
    assert (page.total, page.truncated, page.unit, page.scale_missing) == (3, False, "metric", False)
    first, second, _ = page.walls
    assert (first.x1, first.y1, first.x2, first.y2, first.length) == (4.0, 3.0, 8.0, 3.0, 4.0)
    assert first.variant == "drywall"
    assert first.wall_type_id is None
    # A vertical wall: plan y 100 -> -200 (up is positive) becomes image y 3 -> 6 (down is positive).
    assert (second.x1, second.y1, second.x2, second.y2, second.length) == (8.0, 3.0, 8.0, 6.0, 3.0)
    assert second.y2 > second.y1


def test_walls_imperial(project, geometry):
    page = walls_from_api(project, PLAN_A, geometry=geo(geometry, PLAN_A), unit="imperial", limit=500)
    first = page.walls[0]
    # 4 m and 3 m from the top-left, 4 m long, in feet.
    assert (first.x1, first.y1) == (pytest.approx(13.1232), pytest.approx(9.8424))
    assert first.length == pytest.approx(13.1232)


def test_devices_imperial(project, geometry):
    page = placed_devices_from_api(project, PLAN_A, geometry=geo(geometry, PLAN_A), unit="imperial", limit=500)
    first = page.devices[0]
    # 1.5 m, 2.0 m and a 2.7 m height, in feet.
    assert (first.x, first.y, first.height) == (pytest.approx(4.9212), pytest.approx(6.5616), pytest.approx(8.8582))


def test_walls_limit_truncates(project, geometry):
    page = walls_from_api(project, PLAN_A, geometry=geo(geometry, PLAN_A), unit="metric", limit=2)
    assert (len(page.walls), page.total, page.truncated) == (2, 3, True)


def test_walls_without_scale_have_no_coordinates(project):
    page = walls_from_api(project, PLAN_C, geometry=PlanGeometry(None, None, None), unit="metric", limit=500)
    assert page.scale_missing is True
    assert len(page.walls) == 3
    assert all(w.x1 is None and w.y2 is None and w.length is None for w in page.walls)


def test_devices_plan_a(project, geometry):
    page = placed_devices_from_api(project, PLAN_A, geometry=geo(geometry, PLAN_A), unit="metric", limit=500)
    assert len(page.devices) == 2
    first = page.devices[0]
    assert (first.x, first.y, first.height) == (1.5, 2.0, 2.7)
    assert first.mac == "00:00:5e:00:53:01"
    # The console sends this one as twelve bare hex digits.
    assert page.devices[1].mac == "00:00:5e:00:53:02"
    assert first.mount == "ceiling"
    assert first.title == "Device 1"
    assert first.plan_id == PLAN_A


def test_devices_without_scale_keep_height(project):
    page = placed_devices_from_api(project, PLAN_C, geometry=PlanGeometry(None, None, None), unit="metric", limit=500)
    assert page.scale_missing is True
    assert len(page.devices) == 2
    assert all(d.x is None and d.y is None and d.height == 2.7 for d in page.devices)


def test_summary(project, geometry):
    summary = project_summary_from_api(project, geometry=geometry, unit="metric", include_shapes=False)
    assert summary.unit == "metric"
    assert summary.shapes is None
    # Sorted by ordering (sent as 1, 3, 2, null); a plan without one comes last.
    assert [p.title for p in summary.plans] == ["Plan A", "Plan B", "Plan C", "Plan D"]
    assert [p.ordering for p in summary.plans] == [1, 2, 3, None]
    a, b, c, d = summary.plans
    assert (a.scale_per_unit, a.scale_missing) == (100.0, False)
    assert b.image_scale == 1.784
    assert b.image_offset == (12.5, -7.5)
    assert (c.scale_per_unit, c.scale_missing) == (None, True)
    assert (d.shape_counts, d.image_scale, d.image_offset) == ({}, None, None)
    assert a.shape_counts == {"wall": 3, "device": 2, "scale": 1, "map": 1}
    assert summary.wall_types[0].attenuation_db == 10
    assert summary.wall_types[0].name == "Wall Type 1"


def test_device_without_plan_is_only_in_the_shape_listing(project, geometry):
    unplaced = "00000000-0000-4000-8000-000000000038"
    for plan in (PLAN_A, PLAN_B, PLAN_C):
        page = placed_devices_from_api(project, plan, geometry=geo(geometry, plan), unit="metric", limit=500)
        assert unplaced not in [d.id for d in page.devices]
    summary = project_summary_from_api(project, geometry=geometry, unit="metric", include_shapes=True)
    (entry,) = [s for s in summary.shapes if s["id"] == unplaced]
    assert (entry["type"], entry["plan_id"], entry["height"]) == ("device", None, 2.7)
    assert (entry["x"], entry["y"]) == (None, None)


def test_custom_wall_passes_its_type_through(project, geometry):
    page = walls_from_api(project, PLAN_B, geometry=geo(geometry, PLAN_B), unit="metric", limit=500)
    custom = page.walls[2]
    assert (custom.variant, custom.wall_type_id) == ("custom", "00000000-0000-4000-8000-000000000028")
    assert custom.length == 8.0


def test_integer_position_and_rotation_are_read(project, geometry):
    page = placed_devices_from_api(project, PLAN_B, geometry=geo(geometry, PLAN_B), unit="metric", limit=500)
    device_3 = page.devices[0]
    # x = -2 (int) and z = 1 metres on an 800 x 600 px plan at 50 ppm: (-100 + 400) / 50 and (300 + 50) / 50.
    assert (device_3.x, device_3.y) == (6.0, 7.0)
    assert device_3.rotation["base"] == {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0}


def test_summary_imperial_scale(project, geometry):
    summary = project_summary_from_api(project, geometry=geometry, unit="imperial", include_shapes=False)
    assert summary.plans[0].scale_per_unit == pytest.approx(100.0 / 3.2808)


def test_summary_shapes_drop_raw_device_meta(project, geometry):
    summary = project_summary_from_api(project, geometry=geometry, unit="metric", include_shapes=True)
    assert summary.shapes
    assert "192.0.2.1" not in json.dumps(summary.shapes)


def test_summary_accepts_envelope_or_data(project, geometry):
    a = project_summary_from_api(project, geometry=geometry, unit="metric", include_shapes=False)
    b = project_summary_from_api(project["data"], geometry=geometry, unit="metric", include_shapes=False)
    assert a == b


def test_summary_rejects_non_project(geometry):
    with pytest.raises(UniFiMalformedResponseError):
        project_summary_from_api({"data": []}, geometry=geometry, unit="metric", include_shapes=False)


def test_floor_plan(geometry):
    row = load("v1_floor_plans.json")["floor_plans"][0]
    plan = floor_plan_from_api(row, unit="metric")
    assert (plan.scale_per_unit, plan.width_px, plan.height_px) == (100.0, 1000.0, 800.0)
    assert plan.image_filename == "00000000-0000-4000-8000-000000000014.png"
    assert plan.unit == "metric"
    assert floor_plan_from_api(row, unit="imperial").scale_per_unit == pytest.approx(100.0 / 3.2808)


def test_floor_plan_image_filename_is_one_safe_segment():
    row = dict(load("v1_floor_plans.json")["floor_plans"][0], image_url="/a/../b/%2e%2e.png?x=1")
    assert floor_plan_from_api(row, unit="metric").image_filename is None


def test_string_ppm_coerces_and_nan_is_none():
    assert plan_geometry_from_api({"ppm": "100.0", "width": 10, "height": 10}).ppm == 100.0
    assert plan_geometry_from_api({"ppm": math.nan, "width": 10, "height": 10}).ppm is None
    assert finite(True) is None
    assert finite(math.inf) is None


def test_unknown_field_dropped_known_survive():
    row = dict(load("v1_floor_plans.json")["floor_plans"][0], surprise={"k": "v"})
    plan = floor_plan_from_api(row, unit="metric")
    assert plan.name == "Plan A"
    assert not hasattr(plan, "surprise")
    assert "surprise" not in plan.model_dump()


def test_access_point():
    raw = load("v1_access_points.json")["access_points"][0]
    ap = access_point_from_api(raw, ppm=100.0, unit="metric")
    assert (ap.x, ap.y, ap.height) == (2.5, 3.0, 2.7)
    assert (ap.mount, ap.status, ap.azimuth, ap.unit) == ("ceiling", "online", 0, "metric")
    assert access_point_from_api(raw, ppm=None, unit="metric").x is None


def test_switch_and_inventory():
    sw = switch_from_api(load("v1_switches.json")["switches"][0], ppm=100.0, unit="metric")
    assert (sw.x, sw.y, sw.type, sw.status) == (1.0, 1.0, "switch", "online")
    inv = inventory_device_from_api(load("v1_inventory.json")["devices"][0])
    assert (inv.name, inv.serial) == ("Device 1", "SYN0000001")


def test_app_status():
    status = app_status_from_api(load("system.json"))
    assert (status.installed, status.running, status.version, status.update_available) == (True, True, "1.4.3", None)
    missing = app_status_from_api({"apps": {"controllers": []}})
    assert (missing.installed, missing.running, missing.version) == (False, False, None)


@pytest.mark.parametrize("bad", ["", "../x", "a/b", "a b"])
def test_plan_input_rejects_unsafe_ids(bad):
    with pytest.raises(ValidationError):
        InnerSpacePlanInput(plan_id=bad)
    with pytest.raises(ValidationError):
        InnerSpaceAssetInput(plan_id=bad)


def test_inputs_reject_extra_keys_and_hide_values():
    with pytest.raises(ValidationError) as err:
        InnerSpacePlanInput(plan_id=PLAN_A, extra="secret-value")
    assert "secret-value" not in str(err.value)
    with pytest.raises(ValidationError):
        InnerSpaceProjectInput(unexpected=1)


@pytest.mark.parametrize("limit", [0, 2001])
def test_list_limit_bounds(limit):
    with pytest.raises(ValidationError):
        InnerSpaceListInput(limit=limit)


def test_input_defaults():
    assert InnerSpaceListInput().limit == 500
    assert InnerSpaceSiteInput().site_id is None
    assert InnerSpaceAssetInput(plan_id=PLAN_A).include_image is False
    assert InnerSpaceProjectInput().include_shapes is False
    assert InnerSpaceUnitInput().unit is None


def test_site_input_rejects_spaces():
    with pytest.raises(ValidationError):
        InnerSpaceSiteInput(site_id="a b")


def test_unknown_unit_input_rejected():
    with pytest.raises(ValidationError):
        InnerSpaceUnitInput(unit="furlongs")
    with pytest.raises(ValidationError):
        InnerSpaceProjectInput(unit="furlongs")


def _with(shape_type, **changes):
    data = load("v1_project.json")["data"]
    shape = next(s for s in data["shapes"] if s["type"] == shape_type)
    shape.update(changes)
    return data, shape["planId"]


def test_unknown_wall_variant_round_trips(geometry):
    data, plan = _with("wall", variant="future_wall")
    page = walls_from_api(data, plan, geometry=geo(geometry, plan), unit="metric", limit=5)
    assert page.walls[0].variant == "future_wall"


def test_unknown_wall_type_override_round_trips(geometry):
    data = load("v1_project.json")["data"]
    data["wallTypes"][0]["overridesVariant"] = "future_wall"
    summary = project_summary_from_api(data, geometry=geometry, unit="metric", include_shapes=False)
    assert summary.wall_types[0].overrides_variant == "future_wall"


def test_unknown_device_mount_round_trips(geometry):
    data, plan = _with("device", mount="ceiling_tile")
    page = placed_devices_from_api(data, plan, geometry=geo(geometry, plan), unit="metric", limit=5)
    assert page.devices[0].mount == "ceiling_tile"


def test_unknown_ap_mount_and_status_round_trip():
    raw = dict(load("v1_access_points.json")["access_points"][0], mount="pole", status="adopting")
    ap = access_point_from_api(raw, ppm=100.0, unit="metric")
    assert (ap.mount, ap.status) == ("pole", "adopting")
    assert access_point_from_api(dict(raw, mount=None, status=None), ppm=100.0, unit="metric").status is None


def test_unknown_switch_status_round_trips():
    raw = dict(load("v1_switches.json")["switches"][0], status="upgrading")
    assert switch_from_api(raw, ppm=100.0, unit="metric").status == "upgrading"


# ---------------------------------------------------------------------------
# Fail closed: no invented values
# ---------------------------------------------------------------------------


def _first_wall(data):
    return next(s for s in data["shapes"] if s["type"] == "wall" and s["planId"] == PLAN_A)


@pytest.mark.parametrize(
    "position",
    [
        [{"x": "bad", "y": 100, "z": 0}, {"x": 300, "y": 100, "z": 0}, {"x": 300, "y": -200, "z": 0}],
        [{"x": -100, "y": 100, "z": 0}],
        [{"x": -100, "y": 100, "z": 0}, {"x": 300, "y": 100, "z": 0}, {"x": 300, "y": -200, "z": 0}],
        [{"x": -100, "y": 100, "z": 0}, "not a point"],
        [{"x": "-100", "y": 100, "z": 0}, {"x": 300, "y": 100, "z": 0}],
        None,
    ],
    ids=["bad-first-of-three", "one-point", "three-points", "non-object-point", "string-number", "no-position"],
)
def test_wall_without_two_readable_points_has_no_coordinates(geometry, position):
    data = load("v1_project.json")["data"]
    _first_wall(data)["position"] = position
    page = walls_from_api(data, PLAN_A, geometry=geo(geometry, PLAN_A), unit="metric", limit=500)
    assert (page.total, page.unreadable) == (3, 1)
    first = page.walls[0]
    assert (first.x1, first.y1, first.x2, first.y2, first.length) == (None,) * 5
    assert first.id == "00000000-0000-4000-8000-000000000008"
    # The readable walls keep their coordinates.
    assert page.walls[1].length == 3.0


def test_readable_walls_count_none_unreadable(project, geometry):
    page = walls_from_api(project, PLAN_A, geometry=geo(geometry, PLAN_A), unit="metric", limit=500)
    assert page.unreadable == 0


def test_scale_missing_walls_are_not_unreadable(project):
    page = walls_from_api(project, PLAN_C, geometry=PlanGeometry(None, None, None), unit="metric", limit=500)
    assert (page.total, page.unreadable, page.scale_missing) == (3, 0, True)


@pytest.mark.parametrize("key", ["plans", "shapes"])
@pytest.mark.parametrize("damage", ["missing", None, {}])
def test_project_without_plans_or_shapes_list_is_malformed(geometry, key, damage):
    data = load("v1_project.json")["data"]
    if damage == "missing":
        del data[key]
    else:
        data[key] = damage
    with pytest.raises(UniFiMalformedResponseError):
        project_summary_from_api(data, geometry=geometry, unit="metric", include_shapes=False)
    with pytest.raises(UniFiMalformedResponseError):
        walls_from_api(data, PLAN_A, geometry=geo(geometry, PLAN_A), unit="metric", limit=5)


def _map_of(data, plan_id):
    return next(s for s in data["shapes"] if s["type"] == "map" and s["planId"] == plan_id)


def test_image_transform_is_never_invented(geometry):
    data = load("v1_project.json")["data"]
    del _map_of(data, PLAN_A)["imageScale"]
    del _map_of(data, PLAN_A)["imageOffset"]
    _map_of(data, PLAN_B)["imageScale"].update(x=0.0, y=0.0)
    _map_of(data, PLAN_B)["imageOffset"] = {"x": 0.0, "y": "1"}
    data["shapes"].remove(_map_of(data, PLAN_C))
    a, b, c, _ = project_summary_from_api(data, geometry=geometry, unit="metric", include_shapes=False).plans
    assert (a.image_scale, a.image_offset) == (None, None)
    assert (b.image_scale, b.image_offset) == (0.0, None)
    assert (c.image_scale, c.image_offset) == (None, None)


def test_floor_plan_carries_the_map_transform():
    row = load("v1_floor_plans.json")["floor_plans"][1]
    data = load("v1_project.json")["data"]
    plan = floor_plan_from_api(row, unit="metric", image_map=_map_of(data, PLAN_B))
    assert (plan.image_scale, plan.image_offset) == (1.784, (12.5, -7.5))
    bare = floor_plan_from_api(row, unit="metric")
    assert (bare.image_scale, bare.image_offset) == (None, None)


def test_ap_and_switch_flag_a_missing_scale():
    ap_raw = load("v1_access_points.json")["access_points"][0]
    sw_raw = load("v1_switches.json")["switches"][0]
    assert access_point_from_api(ap_raw, ppm=100.0, unit="metric").scale_missing is False
    assert switch_from_api(sw_raw, ppm=100.0, unit="metric").scale_missing is False
    for ppm in (None, 0.0, -5.0):
        ap = access_point_from_api(ap_raw, ppm=ppm, unit="metric")
        sw = switch_from_api(sw_raw, ppm=ppm, unit="metric")
        assert (ap.x, ap.y, ap.scale_missing, ap.height) == (None, None, True, 2.7)
        assert (sw.x, sw.y, sw.scale_missing) == (None, None, True)


@pytest.mark.parametrize("raw", ["00:00:5E:00:53:0A", "00005e00530a", "00-00-5e-00-53-0a"])
def test_macs_are_lowercase_colon_form(geometry, raw):
    expected = "00:00:5e:00:53:0a"
    assert access_point_from_api({"mac": raw}, ppm=100.0, unit="metric").mac == expected
    assert switch_from_api({"mac": raw}, ppm=100.0, unit="metric").mac == expected
    assert inventory_device_from_api({"mac": raw}).mac == expected
    data, plan = _with("device", meta={"mac": raw})
    page = placed_devices_from_api(data, plan, geometry=geo(geometry, plan), unit="metric", limit=5)
    assert page.devices[0].mac == expected


def test_unreadable_mac_is_none():
    assert inventory_device_from_api({"mac": "not-a-mac"}).mac is None


def test_floor_and_ordering_keep_fractions(geometry):
    row = dict(load("v1_floor_plans.json")["floor_plans"][0], floor_number=1.5)
    assert floor_plan_from_api(row, unit="metric").floor_number == 1.5
    assert floor_plan_from_api(dict(row, floor_number=2.0), unit="metric").floor_number == 2
    assert floor_plan_from_api(dict(row, floor_number="x"), unit="metric").floor_number is None
    data = load("v1_project.json")["data"]
    data["plans"][0]["ordering"] = 0.5
    plans = project_summary_from_api(data, geometry=geometry, unit="metric", include_shapes=False).plans
    assert plans[0].ordering == 0.5


# ---------------------------------------------------------------------------
# One frame: the documented API's plan frame
# ---------------------------------------------------------------------------


def test_scaled_plan_returns_the_vendor_frame_and_exposes_the_transform(project, geometry):
    """Plan B's map has image scale 1.784 and an offset; positions ignore both, as the vendor's do."""
    page = walls_from_api(project, PLAN_B, geometry=geo(geometry, PLAN_B), unit="metric", limit=500)
    first = page.walls[0]
    # (-200, 150) -> (200, 150) plan units on an 800 x 600 plan at 50 ppm.
    assert (first.x1, first.y1, first.x2, first.y2, first.length) == (4.0, 3.0, 12.0, 3.0, 8.0)
    plan_b = project_summary_from_api(project, geometry=geometry, unit="metric", include_shapes=False).plans[1]
    assert (plan_b.id, plan_b.image_scale, plan_b.image_offset) == (PLAN_B, 1.784, (12.5, -7.5))
    assert plan_b.scale_per_unit == 50.0


def test_access_point_and_placed_device_share_one_frame(geometry):
    """An AP row and the device shape with the same id land on the same point."""
    ap_raw = load("v1_access_points.json")["access_points"][0]
    data, plan = _with("device", id=ap_raw["id"], position=[{"x": -2.5, "y": 2.7, "z": -1.0}])
    assert plan == ap_raw["floor_plan_id"] == PLAN_A
    device = placed_devices_from_api(data, plan, geometry=geo(geometry, plan), unit="metric", limit=5).devices[0]
    ap = access_point_from_api(ap_raw, ppm=geo(geometry, plan).ppm, unit="metric")
    assert device.id == ap.id
    assert (device.x, device.y) == (ap.x, ap.y) == (2.5, 3.0)


def test_a_non_uniform_image_scale_is_not_reported_as_one_scale():
    """image_scale is one number: an x scale that differs from y would skew every y placed with it."""
    row = load("v1_floor_plans.json")["floor_plans"][1]
    data = load("v1_project.json")["data"]
    image_map = _map_of(data, PLAN_B)
    image_map["imageScale"]["y"] = 2.5
    plan = floor_plan_from_api(row, unit="metric", image_map=image_map)
    assert (plan.image_scale, plan.image_offset) == (None, (12.5, -7.5))
    del image_map["imageScale"]["y"]
    assert floor_plan_from_api(row, unit="metric", image_map=image_map).image_scale == 1.784


def test_an_image_scale_that_differs_only_by_float_noise_is_one_scale():
    row = load("v1_floor_plans.json")["floor_plans"][1]
    image_map = _map_of(load("v1_project.json")["data"], PLAN_B)
    image_map["imageScale"]["y"] = image_map["imageScale"]["x"] * (1 + 1e-12)
    assert floor_plan_from_api(row, unit="metric", image_map=image_map).image_scale == image_map["imageScale"]["x"]


def test_every_unit_field_states_the_feet_factor():
    from unifi_core.innerspace.models.floor_plans import FloorPlan
    from unifi_core.innerspace.units import FEET_PER_METRE

    assert str(FEET_PER_METRE) in FloorPlan.model_json_schema()["properties"]["unit"]["description"]
