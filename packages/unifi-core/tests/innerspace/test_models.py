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
    first = page.walls[0]
    assert (first.x1, first.y1, first.x2, first.y2, first.length) == (4.0, 3.0, 8.0, 3.0, 4.0)
    assert first.variant == "drywall"
    assert first.wall_type_id is None


def test_walls_imperial(project, geometry):
    page = walls_from_api(project, PLAN_A, geometry=geo(geometry, PLAN_A), unit="imperial", limit=500)
    first = page.walls[0]
    assert first.x1 == pytest.approx(13.1232, abs=1e-3)
    assert first.length == pytest.approx(13.1232, abs=1e-3)


def test_walls_limit_truncates(project, geometry):
    page = walls_from_api(project, PLAN_A, geometry=geo(geometry, PLAN_A), unit="metric", limit=2)
    assert (len(page.walls), page.total, page.truncated) == (2, 3, True)


def test_walls_without_scale_have_no_coordinates(project):
    page = walls_from_api(project, PLAN_C, geometry=PlanGeometry(None, None, None), unit="metric", limit=500)
    assert page.scale_missing is True
    assert page.walls
    assert all(w.x1 is None and w.y2 is None and w.length is None for w in page.walls)


def test_devices_plan_a(project, geometry):
    page = placed_devices_from_api(project, PLAN_A, geometry=geo(geometry, PLAN_A), unit="metric", limit=500)
    assert len(page.devices) == 2
    first = page.devices[0]
    assert (first.x, first.y, first.height) == (1.5, 2.0, 2.7)
    assert first.mac == "00:00:5e:00:53:01"
    assert first.mount == "ceiling"
    assert first.title == "Device 1"
    assert first.plan_id == PLAN_A


def test_devices_without_scale_keep_height(project):
    page = placed_devices_from_api(project, PLAN_C, geometry=PlanGeometry(None, None, None), unit="metric", limit=500)
    assert page.scale_missing is True
    assert all(d.x is None and d.y is None and d.height == 2.7 for d in page.devices)


def test_summary(project, geometry):
    summary = project_summary_from_api(project, geometry=geometry, unit="metric", include_shapes=False)
    assert summary.unit == "metric"
    assert summary.shapes is None
    assert [p.title for p in summary.plans] == ["Plan A", "Plan B", "Plan C"]
    a, b, c = summary.plans
    assert (a.scale_per_unit, a.scale_missing) == (100.0, False)
    assert b.image_scale == 1.784
    assert b.image_offset == (12.5, -7.5)
    assert (c.scale_per_unit, c.scale_missing) == (None, True)
    assert a.shape_counts == {"wall": 3, "device": 2, "scale": 1, "map": 1}
    assert summary.wall_types[0].attenuation_db == 10
    assert summary.wall_types[0].name == "Wall Type 1"


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
