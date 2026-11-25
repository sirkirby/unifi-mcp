"""Policy gates for the write tools: the manifest's gates, the startup scan, and the call-time checks.

Read-only mode and a category gate block a write tool before its manager runs, previews included.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.unit.harness import fresh_registrations, run_main  # noqa: F401
from tests.unit.test_write_tools import SPECS
from unifi_core.innerspace.managers.connection_manager import InnerSpaceConnectionManager
from unifi_core.policy_gate import check_unknown_policy_env_vars
from unifi_innerspace_mcp import main, runtime
from unifi_innerspace_mcp.categories import INNERSPACE_CATEGORY_MAP, policy_gates
from unifi_innerspace_mcp.runtime import server

PLAN = "00000000-0000-4000-8000-000000000003"
WALL = {"x1": 1.0, "y1": 1.0, "x2": 3.0, "y2": 1.0, "variant": "drywall"}


@pytest.fixture(autouse=True)
def _clear_policy_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("UNIFI_POLICY_") or key.endswith("READ_ONLY"):
            monkeypatch.delenv(key)


def test_the_manifest_gates_every_write_category_and_action():
    assert {gate for gate in policy_gates() if gate[1] != "read"} == {
        ("walls", "create"),
        ("walls", "update"),
        ("walls", "delete"),
        ("wall_types", "create"),
        ("wall_types", "update"),
        ("attenuation", "create"),
        ("attenuation", "update"),
        ("attenuation", "delete"),
        ("floor_plans", "update"),
        ("floor_plans", "delete"),
        ("project", "update"),
    }


def test_an_unknown_innerspace_gate_is_reported_and_a_known_one_is_not(monkeypatch, caplog):
    monkeypatch.setenv("UNIFI_POLICY_INNERSPACE_WALLS_DELETE", "false")
    monkeypatch.setenv("UNIFI_POLICY_INNERSPACE_WALL_DELETE", "false")
    monkeypatch.setenv("UNIFI_POLICY_NETWORK_WALLS_DELETE", "false")
    monkeypatch.setenv("UNIFI_POLICY_DRIVE_WALLS_DELETE", "false")
    logger = logging.getLogger("test_innerspace_policy_gates")

    with caplog.at_level(logging.WARNING, logger="test_innerspace_policy_gates"):
        unknown = check_unknown_policy_env_vars("innerspace", logger, policy_gates(), INNERSPACE_CATEGORY_MAP)

    assert unknown == ["UNIFI_POLICY_INNERSPACE_WALL_DELETE"]
    assert "Did you mean UNIFI_POLICY_INNERSPACE_WALLS_DELETE" in caplog.text


def _walls_manager():
    preview = {"operation": "x", "no_op": False, "effects": {}, "warnings": []}
    return SimpleNamespace(
        preview_create_walls=AsyncMock(return_value=preview),
        apply_create_walls=AsyncMock(),
        preview_remove_walls=AsyncMock(return_value=preview),
        apply_remove_walls=AsyncMock(),
    )


async def _call_in_eager_mode(monkeypatch, calls):
    """Start in eager mode and make each ``(tool, arguments)`` call while serving; returns the JSON payloads."""
    monkeypatch.setattr(main, "UNIFI_TOOL_REGISTRATION_MODE", "eager")
    cm = InnerSpaceConnectionManager("", "synthetic-admin", "synthetic-password-0123456789")
    payloads = []

    async def serving() -> None:
        for tool, arguments in calls:
            result = await server.call_tool(tool, arguments)
            payloads.append(json.loads(result.content[0].text))

    try:
        await run_main(monkeypatch, cm, serving, real_registration=True)
    finally:
        await cm.close()
    return payloads


@pytest.mark.parametrize("confirm", [False, True])
async def test_read_only_mode_blocks_writes_and_their_previews(monkeypatch, fresh_registrations, confirm):  # noqa: F811
    manager = _walls_manager()
    monkeypatch.setattr(runtime, "wall_manager", manager)
    monkeypatch.setenv("UNIFI_INNERSPACE_READ_ONLY", "true")

    (payload,) = await _call_in_eager_mode(
        monkeypatch,
        [("innerspace_create_walls", {"plan_id": PLAN, "walls": [WALL], "unit": "metric", "confirm": confirm})],
    )

    assert payload["success"] is False
    assert payload["error"] == (
        "Create is disabled for walls: the innerspace server is in read-only mode, which no policy gate overrides."
    )
    manager.preview_create_walls.assert_not_awaited()
    manager.apply_create_walls.assert_not_awaited()


async def test_a_delete_gate_blocks_removal_but_not_creation(monkeypatch, fresh_registrations):  # noqa: F811
    manager = _walls_manager()
    monkeypatch.setattr(runtime, "wall_manager", manager)
    monkeypatch.setenv("UNIFI_POLICY_INNERSPACE_WALLS_DELETE", "false")

    removed, created = await _call_in_eager_mode(
        monkeypatch,
        [
            ("innerspace_remove_walls", {"plan_id": PLAN, "wall_ids": [PLAN]}),
            ("innerspace_create_walls", {"plan_id": PLAN, "walls": [WALL], "unit": "metric"}),
        ],
    )

    assert removed == {
        "success": False,
        "error": "Delete is disabled by policy for walls. Set UNIFI_POLICY_INNERSPACE_WALLS_DELETE=true to enable.",
    }
    manager.preview_remove_walls.assert_not_awaited()
    assert created["success"] is True and created["requires_confirmation"] is True
    manager.preview_create_walls.assert_awaited_once()


# ---------------------------------------------------------------------------
# Every write tool, every gate
# ---------------------------------------------------------------------------

# tool -> (permission category, permission action); set_plan_scale is destructive, so it sits under delete.
WRITE_GATES = {
    "innerspace_create_walls": ("walls", "create"),
    "innerspace_update_walls": ("walls", "update"),
    "innerspace_remove_walls": ("walls", "delete"),
    "innerspace_create_wall_type": ("wall_types", "create"),
    "innerspace_update_wall_type": ("wall_types", "update"),
    "innerspace_create_attenuation_objects": ("attenuation", "create"),
    "innerspace_update_attenuation_objects": ("attenuation", "update"),
    "innerspace_remove_attenuation_objects": ("attenuation", "delete"),
    "innerspace_create_attenuation_object_type": ("attenuation", "create"),
    "innerspace_update_attenuation_object_type": ("attenuation", "update"),
    "innerspace_rename_floor_plan": ("floor_plans", "update"),
    "innerspace_set_floor_attenuation": ("floor_plans", "update"),
    "innerspace_reorder_floor_plans": ("floor_plans", "update"),
    "innerspace_set_plan_scale": ("floor_plans", "delete"),
    "innerspace_set_project_unit": ("project", "update"),
}


def test_every_write_tool_has_its_category_and_action_in_the_manifest():
    manifest = json.loads((Path(main.__file__).parent / "tools_manifest.json").read_text())
    writes = {
        tool["name"]: (tool["permission_category"], tool["permission_action"])
        for tool in manifest["tools"]
        if "permission_category" in tool and not tool["annotations"]["readOnlyHint"]
    }

    assert writes == WRITE_GATES


def _every_manager():
    """One fake per manager alias, with every preview/apply pair of the write tools."""
    fakes = {}
    for module, alias, _tool, suffix, *_ in SPECS:
        fake = fakes.setdefault(alias, SimpleNamespace())
        setattr(fake, f"preview_{suffix}", AsyncMock(return_value={"operation": "x", "no_op": False}))
        setattr(fake, f"apply_{suffix}", AsyncMock())
    return fakes


@pytest.mark.parametrize("confirm", [False, True])
async def test_each_gate_blocks_its_write_tool_and_read_only_blocks_them_all(
    monkeypatch,
    fresh_registrations,  # noqa: F811
    confirm,
):
    fakes = _every_manager()
    for alias, fake in fakes.items():
        monkeypatch.setattr(runtime, alias, fake)
    calls = [(tool, {**kwargs, "confirm": confirm}) for _module, _alias, tool, _suffix, kwargs, *_ in SPECS]
    payloads: dict[str, list[dict]] = {}

    async def serving() -> None:
        for tool, arguments in calls:
            category, action = WRITE_GATES[tool]
            variable = f"UNIFI_POLICY_INNERSPACE_{category.upper()}_{action.upper()}"
            for env in ({variable: "false"}, {"UNIFI_INNERSPACE_READ_ONLY": "true"}):
                with monkeypatch.context() as scoped:
                    for key, value in env.items():
                        scoped.setenv(key, value)
                    result = await server.call_tool(tool, arguments)
                payloads.setdefault(tool, []).append(json.loads(result.content[0].text))

    monkeypatch.setattr(main, "UNIFI_TOOL_REGISTRATION_MODE", "eager")
    cm = InnerSpaceConnectionManager("", "synthetic-admin", "synthetic-password-0123456789")
    try:
        await run_main(monkeypatch, cm, serving, real_registration=True)
    finally:
        await cm.close()

    assert set(payloads) == set(WRITE_GATES)
    for tool, (gated, read_only) in payloads.items():
        category, action = WRITE_GATES[tool]
        assert gated == {
            "success": False,
            "error": f"{action.capitalize()} is disabled by policy for {category}. Set "
            f"UNIFI_POLICY_INNERSPACE_{category.upper()}_{action.upper()}=true to enable.",
        }, tool
        assert read_only["success"] is False and "read-only mode" in read_only["error"], tool
    for fake in fakes.values():
        for method in vars(fake).values():
            method.assert_not_awaited()


async def test_startup_reports_a_misspelled_innerspace_gate(monkeypatch, fresh_registrations, caplog):  # noqa: F811
    """As Access does: the server checks the UNIFI_POLICY_INNERSPACE_* names when it starts."""
    monkeypatch.setenv("UNIFI_POLICY_INNERSPACE_WALL_DELETE", "false")
    cm = InnerSpaceConnectionManager("", "synthetic-admin", "synthetic-password-0123456789")

    async def serving() -> None:
        return None

    try:
        with caplog.at_level(logging.WARNING):
            await run_main(monkeypatch, cm, serving)
    finally:
        await cm.close()

    assert "UNIFI_POLICY_INNERSPACE_WALL_DELETE" in caplog.text
    assert "Did you mean UNIFI_POLICY_INNERSPACE_WALLS_DELETE" in caplog.text
