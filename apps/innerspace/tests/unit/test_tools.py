"""The nine read tools: one manager call each, fixed error text, no value echoed, redaction policy."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from unifi_core.exceptions import UniFiMalformedResponseError, UniFiNotFoundError
from unifi_core.innerspace.managers.connection_manager import InnerSpaceHttpError
from unifi_core.innerspace.managers.floor_plan_manager import InnerSpaceFloorPlanManager
from unifi_core.innerspace.managers.inventory_manager import InnerSpaceInventoryManager
from unifi_core.innerspace.managers.project_manager import InnerSpaceProjectManager
from unifi_core.innerspace.models.devices import AccessPoint, InventoryDevice, Switch
from unifi_core.innerspace.models.floor_plans import FloorPlan
from unifi_core.innerspace.models.project import PlacedDevice, PlacedDevicePage, Wall, WallPage
from unifi_core.innerspace.models.status import InnerSpaceAppStatus
from unifi_innerspace_mcp import runtime
from unifi_innerspace_mcp.tools import devices, floor_plans, project, status

PLAN = "00000000-0000-4000-8000-000000000003"
SITE = "00000000-0000-4000-8000-000000000001"
MARKER = "rejected marker value"


def _manager(**methods):
    return SimpleNamespace(**{name: AsyncMock(return_value=value) for name, value in methods.items()})


@pytest.fixture
def serve(monkeypatch):
    """Point a tool module's manager alias at a fake for one test."""

    def _serve(module, alias, manager):
        monkeypatch.setattr(module, alias, manager)
        return manager

    return _serve


async def test_get_status(serve):
    app = InnerSpaceAppStatus(installed=True, running=True, version="1.2.3")
    manager = serve(status, "system_manager", _manager(get_status=app))

    assert await status.innerspace_get_status() == {
        "success": True,
        "data": {"installed": True, "running": True, "version": "1.2.3", "update_available": None},
    }
    manager.get_status.assert_awaited_once_with()


async def test_get_project(serve):
    summary = SimpleNamespace(model_dump=lambda: {"title": "Home", "unit": "metric"})
    manager = serve(project, "project_manager", _manager(get_project=summary))

    result = await project.innerspace_get_project(include_shapes=True, unit="imperial")

    assert result == {"success": True, "data": {"title": "Home", "unit": "metric"}}
    manager.get_project.assert_awaited_once_with(include_shapes=True, unit="imperial")


async def test_list_floor_plans(serve):
    manager = serve(
        floor_plans, "floor_plan_manager", _manager(list_floor_plans=[FloorPlan(id=PLAN, name="Ground", unit="metric")])
    )

    result = await floor_plans.innerspace_list_floor_plans(site_id=SITE)

    assert result["success"] is True
    assert result["data"]["count"] == 1
    assert (result["data"]["floor_plans"][0]["id"], result["data"]["floor_plans"][0]["name"]) == (PLAN, "Ground")
    manager.list_floor_plans.assert_awaited_once_with(site_id=SITE)


async def test_list_walls(serve):
    page = WallPage(
        unit="metric",
        plan_id=PLAN,
        walls=[Wall(id="w1", x1=0.0, y1=0.0, x2=3.0, y2=0.0)],
        total=1,
        truncated=False,
        scale_missing=False,
        unreadable=0,
    )
    manager = serve(project, "project_manager", _manager(list_walls=page))

    result = await project.innerspace_list_walls(PLAN, limit=10, unit="imperial")

    assert result["success"] is True
    assert (result["data"]["total"], result["data"]["truncated"], result["data"]["walls"][0]["x2"]) == (1, False, 3.0)
    manager.list_walls.assert_awaited_once_with(PLAN, limit=10, unit="imperial")


async def test_list_placed_devices(serve):
    page = PlacedDevicePage(
        unit="metric",
        plan_id=PLAN,
        devices=[PlacedDevice(id="d1", title="AP 1", mac="00:00:5e:00:53:01")],
        total=1,
        truncated=False,
        scale_missing=False,
    )
    manager = serve(devices, "project_manager", _manager(list_placed_devices=page))

    result = await devices.innerspace_list_placed_devices(PLAN, limit=5)

    assert result["success"] is True
    assert result["data"]["devices"][0]["title"] == "AP 1"
    manager.list_placed_devices.assert_awaited_once_with(PLAN, limit=5, unit=None)


@pytest.mark.parametrize(
    ("tool", "method", "key", "model"),
    [
        (
            devices.innerspace_list_access_points,
            "list_access_points",
            "access_points",
            AccessPoint(id="a1", name="AP", scale_missing=False, unit="metric"),
        ),
        (
            devices.innerspace_list_switches,
            "list_switches",
            "switches",
            Switch(id="s1", name="SW", scale_missing=False, unit="metric"),
        ),
    ],
    ids=["access-points", "switches"],
)
async def test_placed_device_lists(serve, tool, method, key, model):
    manager = serve(devices, "inventory_manager", _manager(**{method: [model]}))

    result = await tool(site_id=SITE, unit="imperial")

    assert result["success"] is True and result["data"]["count"] == 1
    assert result["data"][key][0]["id"] == model.id
    getattr(manager, method).assert_awaited_once_with(site_id=SITE, unit="imperial")


async def test_list_inventory(serve):
    manager = serve(devices, "inventory_manager", _manager(list_inventory=[InventoryDevice(id="i1", name="New AP")]))

    result = await devices.innerspace_list_inventory(site_id=SITE)

    assert result["success"] is True and result["data"]["count"] == 1
    assert result["data"]["devices"][0]["name"] == "New AP"
    manager.list_inventory.assert_awaited_once_with(site_id=SITE)


async def test_plan_asset_png_points_at_the_png_resource(serve):
    metadata = {"filename": "f.png", "content_type": "image/png", "width_px": 1000.0, "height_px": 800.0}
    manager = serve(floor_plans, "floor_plan_manager", _manager(get_plan_asset=metadata))

    result = await floor_plans.innerspace_get_plan_asset(PLAN)

    assert result == {"success": True, "data": {**metadata, "resource_uri": f"innerspace://plans/{PLAN}/image"}}
    manager.get_plan_asset.assert_awaited_once_with(PLAN)


async def test_plan_asset_jpeg_points_at_the_jpeg_resource(serve):
    metadata = {"filename": "f.jpg", "content_type": "image/jpeg", "width_px": 1000.0, "height_px": 800.0}
    serve(floor_plans, "floor_plan_manager", _manager(get_plan_asset=metadata))

    result = await floor_plans.innerspace_get_plan_asset(PLAN)

    assert result == {"success": True, "data": {**metadata, "resource_uri": f"innerspace://plans/{PLAN}/image.jpg"}}


def test_plan_asset_never_returns_the_image_inline():
    """The image is served by the resources only, never as base64 in a tool result."""
    import inspect

    assert "include_image" not in inspect.signature(floor_plans.innerspace_get_plan_asset).parameters


async def test_plan_asset_failure_returns_the_fixed_text(serve):
    text = "get InnerSpace plan asset: no such floor plan"
    manager = SimpleNamespace(get_plan_asset=AsyncMock(side_effect=UniFiMalformedResponseError(text)))
    serve(floor_plans, "floor_plan_manager", manager)

    result = await floor_plans.innerspace_get_plan_asset(PLAN)

    assert result == {"success": False, "error": f"Failed to {text}"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

_REAL = {
    "project": InnerSpaceProjectManager,
    "floor_plan": InnerSpaceFloorPlanManager,
    "inventory": InnerSpaceInventoryManager,
}

_INVALID = [
    (project, "project", lambda: project.innerspace_get_project(unit=MARKER), "get InnerSpace project"),
    (project, "project", lambda: project.innerspace_list_walls(MARKER), "list InnerSpace walls"),
    (project, "project", lambda: project.innerspace_list_walls(PLAN, limit=0), "list InnerSpace walls"),
    (devices, "project", lambda: devices.innerspace_list_placed_devices(MARKER), "list InnerSpace placed devices"),
    (
        devices,
        "project",
        lambda: devices.innerspace_list_placed_devices(PLAN, limit=100000),
        "list InnerSpace placed devices",
    ),
    (
        devices,
        "inventory",
        lambda: devices.innerspace_list_access_points(site_id=MARKER),
        "list InnerSpace access points",
    ),
    (devices, "inventory", lambda: devices.innerspace_list_switches(unit=MARKER), "list InnerSpace switches"),
    (devices, "inventory", lambda: devices.innerspace_list_inventory(site_id=MARKER), "list InnerSpace inventory"),
    (
        floor_plans,
        "floor_plan",
        lambda: floor_plans.innerspace_list_floor_plans(site_id=MARKER),
        "list InnerSpace floor plans",
    ),
    (floor_plans, "floor_plan", lambda: floor_plans.innerspace_get_plan_asset(MARKER), "get InnerSpace plan asset"),
]
_ALIASES = {"project": "project_manager", "floor_plan": "floor_plan_manager", "inventory": "inventory_manager"}


@pytest.mark.parametrize(("module", "manager", "call", "operation"), _INVALID)
async def test_invalid_arguments_fixed_text(monkeypatch, caplog, module, manager, call, operation):
    cm = MagicMock(request=AsyncMock(), request_bytes=AsyncMock(), ensure_app_running=AsyncMock())
    monkeypatch.setattr(module, _ALIASES[manager], _REAL[manager](cm))

    with caplog.at_level(logging.DEBUG):
        result = await call()

    assert result == {"success": False, "error": f"Failed to {operation}: invalid arguments"}
    assert MARKER not in caplog.text
    assert "ValidationError" in caplog.text
    # Rejected before anything reaches the console.
    cm.ensure_app_running.assert_not_awaited()
    cm.request.assert_not_awaited()
    cm.request_bytes.assert_not_awaited()


async def test_core_error_text_returned_class_logged(serve, caplog):
    text = "list InnerSpace floor plans: no such floor plan"
    error = UniFiNotFoundError("floor plan", "InnerSpace", text)
    serve(floor_plans, "floor_plan_manager", SimpleNamespace(list_floor_plans=AsyncMock(side_effect=error)))

    with caplog.at_level(logging.ERROR):
        result = await floor_plans.innerspace_list_floor_plans()

    assert result == {"success": False, "error": f"Failed to {text}"}
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == [
        "Failed to list InnerSpace floor plans: UniFiNotFoundError"
    ]


# Unavailable is not empty: a route the console no longer serves (404) or a reply without the expected
# list is an error that names the operation, never a successful empty result.
_LIST_READS = [
    (project, "project", lambda: project.innerspace_list_walls(PLAN), "list InnerSpace walls"),
    (devices, "project", lambda: devices.innerspace_list_placed_devices(PLAN), "list InnerSpace placed devices"),
    (devices, "inventory", lambda: devices.innerspace_list_access_points(), "list InnerSpace access points"),
    (devices, "inventory", lambda: devices.innerspace_list_switches(), "list InnerSpace switches"),
    (devices, "inventory", lambda: devices.innerspace_list_inventory(), "list InnerSpace inventory"),
    (floor_plans, "floor_plan", lambda: floor_plans.innerspace_list_floor_plans(), "list InnerSpace floor plans"),
]


@pytest.mark.parametrize("reply", ["not_served", "no_list"])
@pytest.mark.parametrize(("module", "manager", "call", "operation"), _LIST_READS)
async def test_unavailable_is_an_error_not_an_empty_list(monkeypatch, module, manager, call, operation, reply):
    async def request(_method, _path, *, operation, **_kwargs):
        if reply == "not_served":
            raise InnerSpaceHttpError(f"{operation}: the console answered HTTP 404", status=404)
        return {}

    cm = MagicMock(request=AsyncMock(side_effect=request), ensure_app_running=AsyncMock())
    monkeypatch.setattr(module, _ALIASES[manager], _REAL[manager](cm))

    result = await call()

    assert result["success"] is False
    assert result["error"].startswith(f"Failed to {operation}: ")
    assert "unexpected" not in result["error"]
    assert "data" not in result


async def test_unexpected_error_returns_class_only(serve):
    serve(status, "system_manager", SimpleNamespace(get_status=AsyncMock(side_effect=RuntimeError(MARKER))))

    result = await status.innerspace_get_status()

    assert result == {"success": False, "error": "Failed to get InnerSpace status: unexpected RuntimeError"}


# ---------------------------------------------------------------------------
# Redaction policy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("policy", "shown"), [(True, "***REDACTED***"), (False, "plain-value")])
def test_response_policy_applies_to_every_tool_result(monkeypatch, policy, shown):
    monkeypatch.setattr(runtime, "should_redact_sensitive_fields", lambda: policy)
    meta = dict(password="plain-value")

    result = runtime.tool_success({"devices": [{"mac": "00:00:5e:00:53:01", "meta": meta}]})

    assert result["data"]["devices"][0]["meta"]["password"] == shown
    assert result["data"]["devices"][0]["mac"] == "00:00:5e:00:53:01"
