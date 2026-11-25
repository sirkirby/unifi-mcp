"""The write tools: preview without confirm, apply with it, and a result whose success follows the read-back.

Each tool calls one core method pair. ``success`` is false whenever the read-back did not show the change
(``mutation_applied`` false) or could not tell (``None``, "read before retrying"). Invalid arguments name the
field and the rule, never the value.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from unifi_core.innerspace.managers._writes import InnerSpaceWriteRefusedError
from unifi_core.innerspace.managers.wall_manager import InnerSpaceWallManager
from unifi_core.write_verification import WriteVerificationResult, failed_write, noop_write
from unifi_innerspace_mcp import runtime
from unifi_innerspace_mcp.tools import attenuation, floor_plans, project, wall_types, walls

PLAN = "00000000-0000-4000-8000-000000000003"
PLAN_B = "00000000-0000-4000-8000-000000000004"
ITEM = "00000000-0000-4000-8000-000000000008"
TYPE = "00000000-0000-4000-8000-000000000028"
MARKER = "rejected marker value"
WALL = {"x1": 1.0, "y1": 1.0, "x2": 3.0, "y2": 1.0, "variant": "drywall"}
POLYGON = {"points": [{"x": 1, "y": 1}, {"x": 2, "y": 1}, {"x": 2, "y": 2}, {"x": 1, "y": 1}], "variant": "car"}
FRAME = {"unit": "metric", "coordinates": "frame"}

# module, alias, tool, method suffix, tool kwargs, manager args, manager kwargs
SPECS = [
    (walls, "wall_manager", "innerspace_create_walls", "create_walls",
     dict(plan_id=PLAN, walls=[WALL], unit="metric"), (PLAN, [WALL]), FRAME),
    (walls, "wall_manager", "innerspace_update_walls", "update_walls",
     dict(plan_id=PLAN, walls=[{"id": ITEM, "variant": "glass"}], unit="imperial", coordinates="plan_units"),
     (PLAN, [{"id": ITEM, "variant": "glass"}]), {"unit": "imperial", "coordinates": "plan_units"}),
    (walls, "wall_manager", "innerspace_remove_walls", "remove_walls",
     dict(plan_id=PLAN, wall_ids=[ITEM]), (PLAN, [ITEM]), {}),
    (wall_types, "wall_type_manager", "innerspace_create_wall_type", "create_wall_type",
     dict(name="Brick", attenuation_db=12.0, color="#aa5500", transparent=True),
     ("Brick", 12.0, "#aa5500"), {"transparent": True}),
    (wall_types, "wall_type_manager", "innerspace_update_wall_type", "update_wall_type",
     dict(wall_type_id=TYPE, color="#000000"), (TYPE,),
     {"name": None, "attenuation_db": None, "color": "#000000", "transparent": None}),
    (attenuation, "attenuation_manager", "innerspace_create_attenuation_objects", "create_attenuation_objects",
     dict(plan_id=PLAN, objects=[POLYGON], unit="metric"), (PLAN, [POLYGON]), FRAME),
    (attenuation, "attenuation_manager", "innerspace_update_attenuation_objects", "update_attenuation_objects",
     dict(plan_id=PLAN, objects=[{"id": ITEM, "variant": "truck"}], unit="metric"),
     (PLAN, [{"id": ITEM, "variant": "truck"}]), FRAME),
    (attenuation, "attenuation_manager", "innerspace_remove_attenuation_objects", "remove_attenuation_objects",
     dict(plan_id=PLAN, object_ids=[ITEM]), (PLAN, [ITEM]), {}),
    (attenuation, "attenuation_manager", "innerspace_create_attenuation_object_type",
     "create_attenuation_object_type", dict(name="Rack", attenuation_db=8.0, color="#112233"),
     ("Rack", 8.0, "#112233"), {}),
    (attenuation, "attenuation_manager", "innerspace_update_attenuation_object_type",
     "update_attenuation_object_type", dict(attenuation_object_type_id=TYPE, attenuation_db=9.5), (TYPE,),
     {"name": None, "attenuation_db": 9.5, "color": None}),
    (floor_plans, "floor_plan_manager", "innerspace_rename_floor_plan", "rename_floor_plan",
     dict(plan_id=PLAN, title="Upstairs"), (PLAN, "Upstairs"), {}),
    (floor_plans, "floor_plan_manager", "innerspace_set_floor_attenuation", "set_floor_attenuation",
     dict(plan_id=PLAN, attenuation_db=None), (PLAN, None), {}),
    (floor_plans, "floor_plan_manager", "innerspace_reorder_floor_plans", "reorder_floor_plans",
     dict(plan_ids=[PLAN_B, PLAN]), ([PLAN_B, PLAN],), {}),
    (floor_plans, "floor_plan_manager", "innerspace_set_plan_scale", "set_plan_scale",
     dict(plan_id=PLAN, x1=0.0, y1=0.0, x2=5.0, y2=0.0, length=5.0, unit="metric"), (PLAN,),
     dict(x1=0.0, y1=0.0, x2=5.0, y2=0.0, length=5.0, unit="metric", coordinates="frame")),
    (project, "project_settings_manager", "innerspace_set_project_unit", "set_project_unit",
     dict(unit="imperial"), ("imperial",), {}),
]  # fmt: skip
IDS = [spec[2] for spec in SPECS]
PREVIEW = {"operation": "x", "no_op": False, "effects": {"walls_using_type": {"total": 2}}, "warnings": ["w"]}


def _applied(operation: str = "create InnerSpace walls") -> WriteVerificationResult:
    metadata = {"effects": {}, "created_ids": [ITEM], "warnings": [], "missing": []}
    return WriteVerificationResult(success=True, mutation_applied=True, operation=operation, metadata=metadata)


def _fake(preview=None, applied=None):
    """A manager with every preview/apply pair of the write tools, returning ``preview`` and ``applied``."""
    methods = {}
    for *_, suffix, _kwargs, _args, _mkwargs in SPECS:
        methods[f"preview_{suffix}"] = AsyncMock(return_value=dict(PREVIEW) if preview is None else preview)
        methods[f"apply_{suffix}"] = AsyncMock(return_value=_applied() if applied is None else applied)
    return SimpleNamespace(**methods)


@pytest.mark.parametrize(("module", "alias", "name", "suffix", "kwargs", "args", "mkwargs"), SPECS, ids=IDS)
async def test_without_confirm_only_the_preview_runs(monkeypatch, module, alias, name, suffix, kwargs, args, mkwargs):
    manager = _fake()
    monkeypatch.setattr(module, alias, manager)

    result = await getattr(module, name)(**kwargs)

    assert result == {
        "success": True,
        "requires_confirmation": True,
        "preview": PREVIEW,
        "message": "Review the preview, then call again with the same arguments and confirm=true to apply.",
    }
    getattr(manager, f"preview_{suffix}").assert_awaited_once_with(*args, **mkwargs)
    getattr(manager, f"apply_{suffix}").assert_not_awaited()


@pytest.mark.parametrize(("module", "alias", "name", "suffix", "kwargs", "args", "mkwargs"), SPECS, ids=IDS)
async def test_with_confirm_only_the_apply_runs(monkeypatch, module, alias, name, suffix, kwargs, args, mkwargs):
    manager = _fake()
    monkeypatch.setattr(module, alias, manager)

    result = await getattr(module, name)(**kwargs, confirm=True)

    assert result["success"] is True and result["mutation_applied"] is True
    assert result["created_ids"] == [ITEM] and result["missing"] == []
    assert result["message"].endswith("read back.")
    assert "site" not in result and "error" not in result
    getattr(manager, f"apply_{suffix}").assert_awaited_once_with(*args, **mkwargs)
    getattr(manager, f"preview_{suffix}").assert_not_awaited()


async def test_a_preview_that_changes_nothing_says_so(monkeypatch):
    monkeypatch.setattr(walls, "wall_manager", _fake(preview={**PREVIEW, "no_op": True}))

    result = await walls.innerspace_update_walls(PLAN, [{"id": ITEM, "variant": "glass"}], "metric")

    assert result["requires_confirmation"] is True
    assert result["message"] == "Nothing to change: confirming sends nothing."


# ---------------------------------------------------------------------------
# Failure shows as failure (the MCP half)
# ---------------------------------------------------------------------------

OPERATION = "create InnerSpace walls"
NOT_APPLIED = f"{OPERATION}: the console answered HTTP 500, and the read-back shows no change; nothing was applied."
UNKNOWN = f"{OPERATION}: the console did not answer, and the read-back failed, so whether the change was applied is unknown. Read before retrying."  # noqa: E501


@pytest.mark.parametrize(("applied", "error", "missing"), [(False, NOT_APPLIED, ["a"]), (None, UNKNOWN, None)])
async def test_failed_write_is_failure_mcp(monkeypatch, applied, error, missing):
    outcome = failed_write(error, operation=OPERATION, mutation_applied=applied, metadata={"missing": missing})
    monkeypatch.setattr(walls, "wall_manager", _fake(applied=outcome))

    result = await walls.innerspace_create_walls(PLAN, [WALL], "metric", confirm=True)

    assert result["success"] is False
    assert result["mutation_applied"] is applied
    assert result["error"] == f"Failed to {error}"


async def test_unknown_outcome_without_guidance_gets_it(monkeypatch):
    outcome = failed_write(f"{OPERATION}: something odd.", operation=OPERATION, mutation_applied=None)
    monkeypatch.setattr(walls, "wall_manager", _fake(applied=outcome))

    result = await walls.innerspace_create_walls(PLAN, [WALL], "metric", confirm=True)

    assert result["success"] is False and result["mutation_applied"] is None
    assert result["error"] == (
        f"Failed to {OPERATION}: something odd. Whether it was applied is unknown; read before retrying."
    )


def test_an_unknown_outcome_is_never_a_success_mcp():
    result = WriteVerificationResult(success=True, mutation_applied=None, operation=OPERATION)

    payload = runtime.write_result(result, applied="Walls created and read back.")

    assert payload["success"] is False and payload["mutation_applied"] is None
    assert "read before retrying" in payload["error"].lower()


async def test_nothing_sent_because_the_values_are_already_there(monkeypatch):
    outcome = noop_write(operation="update InnerSpace walls", metadata={"effects": {}, "warnings": []})
    monkeypatch.setattr(walls, "wall_manager", _fake(applied=outcome))

    result = await walls.innerspace_update_walls(PLAN, [{"id": ITEM, "variant": "glass"}], "metric", confirm=True)

    assert result["success"] is True and result["mutation_applied"] is False
    assert result["message"] == runtime.NO_CHANGE


async def test_already_applied_create_says_already_applied(monkeypatch):
    metadata = {"effects": {}, "created_ids": [ITEM], "noop": "already_applied", "warnings": []}
    monkeypatch.setattr(walls, "wall_manager", _fake(applied=noop_write(operation=OPERATION, metadata=metadata)))

    result = await walls.innerspace_create_walls(PLAN, [WALL], "metric", confirm=True)

    assert result["success"] is True and result["mutation_applied"] is False
    assert result["noop"] == "already_applied" and result["created_ids"] == [ITEM]
    assert result["message"].startswith("Already applied:")
    assert "already applied" in result["message"].lower()


async def test_a_remove_that_found_none_of_the_ids_does_not_claim_the_values_are_there(monkeypatch):
    metadata = {"effects": {}, "noop": "none_found", "warnings": []}
    monkeypatch.setattr(walls, "wall_manager", _fake(applied=noop_write(operation=OPERATION, metadata=metadata)))

    result = await walls.innerspace_remove_walls(PLAN, [ITEM], confirm=True)

    assert result["success"] is True and result["mutation_applied"] is False
    assert result["message"] == runtime.NONE_FOUND
    assert "already holds" not in result["message"]


async def test_a_refusal_returns_its_fixed_text(monkeypatch, caplog):
    text = f"{OPERATION}: some objects of an earlier identical call exist and some do not"
    manager = _fake()
    manager.apply_create_walls = AsyncMock(side_effect=InnerSpaceWriteRefusedError(text))
    monkeypatch.setattr(walls, "wall_manager", manager)

    with caplog.at_level(logging.ERROR):
        result = await walls.innerspace_create_walls(PLAN, [WALL], "metric", confirm=True)

    assert result == {"success": False, "error": f"Failed to {text}"}
    assert "Failed to create InnerSpace walls: InnerSpaceWriteRefusedError" in caplog.text


async def test_an_unexpected_error_returns_its_class_only(monkeypatch):
    manager = _fake()
    manager.preview_remove_walls = AsyncMock(side_effect=RuntimeError(MARKER))
    monkeypatch.setattr(walls, "wall_manager", manager)

    result = await walls.innerspace_remove_walls(PLAN, [ITEM])

    assert result == {"success": False, "error": "Failed to remove InnerSpace walls: unexpected RuntimeError"}


# ---------------------------------------------------------------------------
# Invalid arguments: the field and the rule, never the value
# ---------------------------------------------------------------------------


@pytest.fixture
def real_walls(monkeypatch):
    cm = MagicMock(request=AsyncMock(), ensure_app_running=AsyncMock())
    monkeypatch.setattr(walls, "wall_manager", InnerSpaceWallManager(cm))
    return cm


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        ([{**WALL, "variant": MARKER}], "walls.0.variant: Input should be 'concrete'"),
        ([{**WALL, MARKER: 1}], "walls.0: Extra inputs are not permitted"),
        ([{**WALL, "x1": MARKER}], "walls.0.x1: Input should be a valid number"),
        ([{**WALL, "variant": "custom"}], 'walls.0: Value error, A wall type id goes with variant "custom"'),
    ],
    ids=["literal", "unknown-key", "type", "rule"],
)
async def test_invalid_arguments_name_the_field_never_the_value(real_walls, caplog, items, expected):
    for confirm in (False, True):
        with caplog.at_level(logging.DEBUG):
            result = await walls.innerspace_create_walls(PLAN, items, "metric", confirm=confirm)

        assert result["success"] is False
        assert result["error"].startswith(f"Failed to create InnerSpace walls: invalid arguments: {expected}")
        assert MARKER not in result["error"] and MARKER not in caplog.text
    real_walls.ensure_app_running.assert_not_awaited()
    real_walls.request.assert_not_awaited()


async def test_a_wrong_unit_is_refused_before_any_request(real_walls):
    result = await walls.innerspace_create_walls(PLAN, [WALL], MARKER)

    assert result["error"].startswith("Failed to create InnerSpace walls: invalid arguments: unit: Input should be")
    assert MARKER not in result["error"]
    real_walls.request.assert_not_awaited()


async def test_at_most_three_errors_are_reported(real_walls):
    result = await walls.innerspace_create_walls(PLAN, [{"variant": "drywall"}], "metric")

    assert result["error"].count("Field required") == 3


def test_reorder_says_it_renumbers_the_plans_and_loses_ties():
    """The write numbers the plans 1, 2, 3 ...: plans that share an order value cannot be put back."""
    manifest = json.loads((Path(floor_plans.__file__).parents[1] / "tools_manifest.json").read_text())
    (tool,) = [t for t in manifest["tools"] if t["name"] == "innerspace_reorder_floor_plans"]
    description = tool["description"]
    assert "1, 2, 3" in description
    assert "lose the tie" in description
