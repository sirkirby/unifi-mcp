"""Project unit: the body recorded live on 1.4.3, preview, no-op and read-back."""

import pytest
from pydantic import ValidationError
from unifi_core.innerspace.managers.connection_manager import INTERNAL_PROJECT_PATH
from unifi_core.innerspace.managers.project_settings_manager import InnerSpaceProjectSettingsManager

from tests.innerspace.helpers import floor_plan_rows, internal_state, ready, script_preview


async def test_set_unit_sends_the_unit_only(connected, console):
    ready(console)
    shapes = internal_state()["shapes"]

    result = await InnerSpaceProjectSettingsManager(connected).apply_set_project_unit("imperial")

    assert [(r.method, r.path, r.body) for r in console.writes()] == [
        ("PATCH", INTERNAL_PROJECT_PATH, {"unit": "imperial"})
    ]
    assert result.success is True and result.mutation_applied is True
    assert console.project["project"]["unit"] == "imperial"
    assert console.project["shapes"] == shapes
    console.assert_csrf()


async def test_set_unit_preview_and_no_op(connected, console):
    console.load_project(internal_state("metric"))
    script_preview(console)
    manager = InnerSpaceProjectSettingsManager(connected)

    preview = await manager.preview_set_project_unit("imperial")
    assert (preview["current"], preview["proposed"], preview["no_op"]) == (
        {"unit": "metric"},
        {"unit": "imperial"},
        False,
    )
    assert preview["warnings"]
    assert console.writes() == []

    console.script_write(floor_plans=floor_plan_rows())
    result = await manager.apply_set_project_unit("metric")
    assert (result.success, result.mutation_applied) == (True, False)
    assert console.writes() == []


async def test_set_unit_not_applied_when_the_read_back_shows_the_old_unit(connected, console):
    ready(console)
    console.reply("GET", INTERNAL_PROJECT_PATH, {"data": internal_state()})
    console.refuse("PATCH", INTERNAL_PROJECT_PATH, "errors.invalid.data")

    result = await InnerSpaceProjectSettingsManager(connected).apply_set_project_unit("imperial")

    assert (result.success, result.mutation_applied) == (False, False)


@pytest.mark.parametrize("unit", ["metres", None, 1])
async def test_unit_is_closed(connected, console, unit):
    with pytest.raises(ValidationError):
        await InnerSpaceProjectSettingsManager(connected).apply_set_project_unit(unit)

    assert console.writes() == []
