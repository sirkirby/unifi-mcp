"""Wall type create and update: literal bodies from the 1.4.3 probe, project-wide effects, no-ops, refusals."""

import re

import pytest
from pydantic import ValidationError
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.innerspace.managers.connection_manager import WALL_TYPE_PATH
from unifi_core.innerspace.managers.wall_type_manager import InnerSpaceWallTypeManager

from tests.innerspace.helpers import (
    PLAN_B,
    PROJECT_ID,
    UUID_SHAPED,
    WALL_TYPE,
    internal_state,
    ready,
    script_preview,
)


def _type_writes(console):
    return [r.body for r in console.calls("POST", WALL_TYPE_PATH)]


def _stored_type(console, type_id):
    return next((t for t in console.project["wallTypes"] if t["id"] == type_id), None)


async def test_create_wall_type_sends_the_probe_body(connected, console):
    ready(console)

    result = await InnerSpaceWallTypeManager(connected).apply_create_wall_type("Brick wall", 12, "#aa5500")

    (new_id,) = result.metadata["created_ids"]
    assert _type_writes(console) == [
        {
            "create": [
                {
                    "id": new_id,
                    "projectId": PROJECT_ID,
                    "name": "Brick wall",
                    "attenuation": 12.0,
                    "color": "#aa5500",
                    "isDeleted": False,
                    "overridesVariant": None,
                    "bottomHeight": None,
                    "topHeight": None,
                    "transparent": False,
                    "autoFillEnabled": False,
                }
            ],
            "update": [],
            "remove": [],
        }
    ]
    assert result.success is True and result.mutation_applied is True
    assert _stored_type(console, new_id)["name"] == "Brick wall"
    console.assert_csrf()


async def test_create_preview_warns_about_a_name_in_use_and_holds_no_ids(connected, console):
    console.load_project(internal_state())
    script_preview(console, times=2)
    manager = InnerSpaceWallTypeManager(connected)

    preview = await manager.preview_create_wall_type(" Wall Type 1 ", 8, "#112233", transparent=True)
    again = await manager.preview_create_wall_type(" Wall Type 1 ", 8, "#112233", transparent=True)

    assert preview == again
    assert preview["proposed"] == {
        "name": "Wall Type 1",
        "attenuation_db": 8.0,
        "color": "#112233",
        "transparent": True,
    }
    assert preview["warnings"] == ["Another wall type already has this name"]
    assert re.findall(UUID_SHAPED, repr(preview)) == []
    assert console.writes() == []


async def test_create_result_repeats_the_warnings(connected, console):
    ready(console)

    result = await InnerSpaceWallTypeManager(connected).apply_create_wall_type("wall type 1", 8, "#112233")

    assert "Another wall type already has this name" in result.metadata["warnings"]


async def test_update_sends_the_full_stored_type_and_counts_the_walls_using_it(connected, console):
    ready(console)
    stored = dict(_stored_type(console, WALL_TYPE))

    result = await InnerSpaceWallTypeManager(connected).apply_update_wall_type(WALL_TYPE, attenuation_db=14)

    assert _type_writes(console) == [{"create": [], "update": [{**stored, "attenuation": 14.0}], "remove": []}]
    assert result.success is True and result.mutation_applied is True
    assert result.metadata["effects"] == {"walls_using_type": {"total": 1, "by_plan": {PLAN_B: 1}}}
    assert result.metadata["warnings"] == ["This type is project-wide: the change applies to 1 wall"]
    assert _stored_type(console, WALL_TYPE)["attenuation"] == 14.0


async def test_update_preview_shows_current_and_proposed(connected, console):
    console.load_project(internal_state())
    script_preview(console)

    preview = await InnerSpaceWallTypeManager(connected).preview_update_wall_type(
        WALL_TYPE, name="Wall Type 1", color="#000000"
    )

    assert (preview["current"], preview["proposed"]) == ({"color": "#808080"}, {"color": "#000000"})
    assert preview["effects"]["walls_using_type"]["total"] == 1
    assert preview["no_op"] is False
    assert console.writes() == []


async def test_update_equal_to_the_stored_type_sends_nothing(connected, console):
    ready(console)

    result = await InnerSpaceWallTypeManager(connected).apply_update_wall_type(
        WALL_TYPE, name="Wall Type 1", attenuation_db=10, transparent=False
    )

    assert (result.success, result.mutation_applied) == (True, False)
    assert console.writes() == []


async def test_a_colour_that_differs_only_in_case_is_the_same_colour(connected, console):
    """#RRGGBB is hex: the console may store either case, and a read-back or retry compares the colour."""
    state = internal_state()
    state["wallTypes"][0]["color"] = "#aa5500"
    ready(console, state)

    result = await InnerSpaceWallTypeManager(connected).apply_update_wall_type(WALL_TYPE, color="#AA5500")

    assert (result.success, result.mutation_applied) == (True, False)
    assert console.writes() == []


@pytest.mark.parametrize("change", ["vanished", "deleted"])
async def test_update_refuses_a_type_gone_since_the_preview(connected, console, change):
    state = internal_state()
    if change == "vanished":
        state["wallTypes"] = []
    else:
        state["wallTypes"][0]["isDeleted"] = True
    ready(console, state)

    with pytest.raises(UniFiNotFoundError):
        await InnerSpaceWallTypeManager(connected).apply_update_wall_type(WALL_TYPE, attenuation_db=14)

    assert console.writes() == []


async def test_inputs_are_closed_before_any_request(connected, console):
    ready(console)
    manager = InnerSpaceWallTypeManager(connected)
    start = len(console.requests)

    with pytest.raises(ValidationError):
        await manager.apply_create_wall_type("x" * 33, 5, "#112233")
    with pytest.raises(ValidationError):
        await manager.apply_update_wall_type(WALL_TYPE)
    with pytest.raises(ValidationError):
        await manager.apply_update_wall_type("../x", attenuation_db=3)

    assert console.requests[start:] == []


def test_wall_type_remove_is_not_built():
    assert not [name for name in dir(InnerSpaceWallTypeManager) if "remove" in name or "delete" in name]


async def test_a_retried_type_create_finds_its_type_and_sends_nothing(connected, console):
    ready(console, writes=2)
    manager = InnerSpaceWallTypeManager(connected)

    first = await manager.apply_create_wall_type("Brick wall", 12, "#aa5500")
    retry = await manager.apply_create_wall_type("Brick wall", 12, "#aa5500")

    assert len(_type_writes(console)) == 1
    assert retry.metadata["noop"] == "already_applied"
    assert retry.metadata["created_ids"] == first.metadata["created_ids"]
