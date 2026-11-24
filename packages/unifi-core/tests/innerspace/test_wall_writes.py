"""Wall create, update and remove: literal bodies from the 1.4.3 probe, previews, no-ops, refusals, read-back."""

import re
from copy import deepcopy

import pytest
from pydantic import ValidationError
from unifi_core.exceptions import UniFiNotFoundError, UniFiValidationError
from unifi_core.innerspace.managers._layout import POSITION_TOLERANCE, shape_change_body
from unifi_core.innerspace.managers._writes import InnerSpaceWriteRefusedError
from unifi_core.innerspace.managers.connection_manager import (
    INTERNAL_PROJECT_PATH,
    SHAPE_CHANGE_PATH,
    SYSTEM_PATH,
    InnerSpaceUnavailableError,
)
from unifi_core.innerspace.managers.wall_manager import InnerSpaceWallManager
from unifi_core.write_verification import READBACK_SETTLE_DELAYS_SECONDS

from tests.innerspace.helpers import (
    PLAN_A,
    PLAN_B,
    PLAN_C,
    PROJECT_ID,
    UUID_SHAPED,
    WALL_TYPE,
    floor_plan_rows,
    internal_state,
    ready,
    script_preview,
    stored_copy,
    stored_shape,
)

WALL_08 = "00000000-0000-4000-8000-000000000008"
WALL_09 = "00000000-0000-4000-8000-000000000009"
WALL_15 = "00000000-0000-4000-8000-000000000015"
WALL_17 = "00000000-0000-4000-8000-000000000017"
DEVICE_11 = "00000000-0000-4000-8000-000000000011"
# Plan A: 1000 x 800 px, 100 plan units per metre, plain map. Frame (1, 1)-(3, 1) m is (-400, 300)-(-200, 300).
FRAME_WALL = {"x1": 1.0, "y1": 1.0, "x2": 3.0, "y2": 1.0, "variant": "drywall"}


def _created(console, shape_id):
    return stored_shape(console, shape_id)


async def test_create_walls_sends_the_probe_body(connected, console):
    ready(console)

    result = await InnerSpaceWallManager(connected).apply_create_walls(PLAN_A, [FRAME_WALL], unit="metric")

    assert result.success is True and result.mutation_applied is True
    (new_id,) = result.metadata["created_ids"]
    assert console.shape_changes() == [
        {
            "create": [
                {
                    "id": new_id,
                    "type": "wall",
                    "projectId": PROJECT_ID,
                    "planId": PLAN_A,
                    "position": [{"x": -400.0, "y": 300.0, "z": 0}, {"x": -200.0, "y": 300.0, "z": 0}],
                    "variant": "drywall",
                    "status": 0,
                }
            ],
            "update": [],
            "remove": [],
            "mode": "2D",
        }
    ]
    assert _created(console, new_id)["wallTypeId"] is None
    console.assert_csrf()


async def test_imperial_wall_create(connected, console):
    ready(console)
    # 3.2808 ft is 1 m and 6.5616 ft is 2 m on Plan A (W 1000, H 800, 100 per metre).
    wall = {"x1": 3.2808, "y1": 3.2808, "x2": 6.5616, "y2": 3.2808, "variant": "custom", "wall_type_id": WALL_TYPE}

    result = await InnerSpaceWallManager(connected).apply_create_walls(PLAN_A, [wall], unit="imperial")

    (sent,) = console.shape_changes()[0]["create"]
    assert sent["position"] == [
        {"x": pytest.approx(-400.0), "y": pytest.approx(300.0), "z": 0},
        {"x": pytest.approx(-300.0), "y": pytest.approx(300.0), "z": 0},
    ]
    assert (sent["variant"], sent["wallTypeId"]) == ("custom", WALL_TYPE)
    assert result.success is True


async def test_create_refuses_an_unknown_wall_type_before_sending(connected, console):
    ready(console)
    wall = {**FRAME_WALL, "variant": "custom", "wall_type_id": "00000000-0000-4000-8000-0000000000ee"}

    with pytest.raises(UniFiNotFoundError):
        await InnerSpaceWallManager(connected).apply_create_walls(PLAN_A, [wall], unit="metric")

    assert console.writes() == []


async def test_create_preview_is_a_summary_without_new_ids(connected, console):
    console.load_project(internal_state())
    script_preview(console, times=2)
    walls = [{**FRAME_WALL, "x2": 3.0 + index} for index in range(7)]
    manager = InnerSpaceWallManager(connected)

    preview = await manager.preview_create_walls(PLAN_A, walls, unit="metric")
    again = await manager.preview_create_walls(PLAN_A, walls, unit="metric")

    assert preview == again
    assert console.writes() == []
    assert preview["count"] == 7 and len(preview["items"]) == 5
    assert preview["items"][0] == {
        "index": 0,
        "proposed": {**FRAME_WALL, "wall_type_id": None},
    }
    assert preview["bounding_box"] == {"x_min": 1.0, "y_min": 1.0, "x_max": 9.0, "y_max": 1.0}
    assert (preview["plan_title"], preview["unit"], preview["coordinates"]) == ("Plan A", "metric", "frame")
    assert preview["no_op"] is False
    assert set(re.findall(UUID_SHAPED, repr(preview))) == {PLAN_A}

    ready(console)
    result = await manager.apply_create_walls(PLAN_A, walls, unit="metric")
    assert not set(result.metadata["created_ids"]) & set(re.findall(UUID_SHAPED, repr(preview)))


async def test_the_same_create_on_the_same_state_reuses_its_ids(connected, console):
    manager = InnerSpaceWallManager(connected)
    ready(console)
    first = await manager.apply_create_walls(PLAN_A, [FRAME_WALL], unit="metric")
    ready(console)
    second = await manager.apply_create_walls(PLAN_A, [FRAME_WALL], unit="metric")
    ready(console)
    other = await manager.apply_create_walls(PLAN_A, [{**FRAME_WALL, "variant": "glass"}], unit="metric")

    assert first.metadata["created_ids"] == second.metadata["created_ids"]
    assert other.metadata["created_ids"] != first.metadata["created_ids"]


async def test_shifted_map_rules(connected, console):
    """Plan B's map is shifted: frame points are refused, plan units and variant-only edits are not."""
    manager = InnerSpaceWallManager(connected)
    ready(console, writes=4)

    with pytest.raises(UniFiValidationError, match="plan_units"):
        await manager.apply_create_walls(PLAN_B, [FRAME_WALL], unit="metric")
    assert console.writes() == []

    by_units = {"x1": -10.0, "y1": 5.0, "x2": 10.0, "y2": 5.0, "variant": "brick"}
    created = await manager.apply_create_walls(PLAN_B, [by_units], unit="metric", coordinates="plan_units")
    assert created.success is True
    assert console.shape_changes()[-1]["create"][0]["position"] == [
        {"x": -10.0, "y": 5.0, "z": 0},
        {"x": 10.0, "y": 5.0, "z": 0},
    ]

    material = await manager.apply_update_walls(PLAN_B, [{"id": WALL_15, "variant": "glass"}], unit="metric")
    assert material.success is True
    assert stored_shape(console, WALL_15)["variant"] == "glass"

    moved = {"id": WALL_15, "x1": 1.0, "y1": 1.0, "x2": 2.0, "y2": 1.0}
    with pytest.raises(UniFiValidationError, match="plan_units"):
        await manager.apply_update_walls(PLAN_B, [moved], unit="metric")
    assert len(console.shape_changes()) == 2


async def test_frame_points_outside_the_image_are_refused(connected, console):
    ready(console)

    with pytest.raises(UniFiValidationError, match="outside"):
        await InnerSpaceWallManager(connected).apply_create_walls(PLAN_A, [{**FRAME_WALL, "x2": 10.5}], unit="metric")

    assert console.writes() == []


async def test_frame_points_need_a_plan_with_geometry(connected, console):
    ready(console)

    with pytest.raises(UniFiValidationError):
        await InnerSpaceWallManager(connected).apply_create_walls(PLAN_C, [FRAME_WALL], unit="metric")

    assert console.writes() == []


async def test_update_sends_the_full_stored_wall(connected, console):
    ready(console)

    result = await InnerSpaceWallManager(connected).apply_update_walls(
        PLAN_A, [{"id": WALL_08, "variant": "glass"}], unit="metric"
    )

    expected = {**stored_copy(WALL_08), "variant": "glass"}
    assert console.shape_changes() == [{"create": [], "update": [expected], "remove": [], "mode": "2D"}]
    assert result.success is True and result.mutation_applied is True
    assert result.metadata["created_ids"] == []


async def test_update_moves_the_ends_in_the_frame(connected, console):
    ready(console)
    # Wall 08 runs (4, 3)-(8, 3) m in Plan A's frame; move its second end to (8, 4) m, plan units (300, 0).
    update = {"id": WALL_08, "x1": 4.0, "y1": 3.0, "x2": 8.0, "y2": 4.0}

    result = await InnerSpaceWallManager(connected).apply_update_walls(PLAN_A, [update], unit="metric")

    (sent,) = console.shape_changes()[0]["update"]
    assert sent["position"] == [{"x": -100.0, "y": 100.0, "z": 0}, {"x": 300.0, "y": 0.0, "z": 0}]
    assert {key: sent[key] for key in sent if key != "position"} == {
        key: value for key, value in stored_copy(WALL_08).items() if key != "position"
    }
    assert result.success is True


async def test_custom_to_built_in_shows_the_type_as_cleared(connected, console):
    console.load_project(internal_state())
    script_preview(console)
    manager = InnerSpaceWallManager(connected)

    preview = await manager.preview_update_walls(PLAN_B, [{"id": WALL_17, "variant": "drywall"}], unit="metric")

    assert preview["items"] == [
        {
            "id": WALL_17,
            "current": {"variant": "custom", "wall_type_id": WALL_TYPE},
            "proposed": {"variant": "drywall"},
            "cleared": ["wall_type_id"],
        }
    ]
    ready(console)
    result = await manager.apply_update_walls(PLAN_B, [{"id": WALL_17, "variant": "drywall"}], unit="metric")
    (sent,) = console.shape_changes()[0]["update"]
    assert "wallTypeId" not in sent
    assert result.success is True
    assert stored_shape(console, WALL_17)["wallTypeId"] is None


async def test_update_preview_shows_current_and_proposed_in_the_frame(connected, console):
    console.load_project(internal_state())
    script_preview(console)
    update = {"id": WALL_08, "x1": 4.0, "y1": 3.0, "x2": 8.0, "y2": 4.0, "variant": "brick"}

    preview = await InnerSpaceWallManager(connected).preview_update_walls(PLAN_A, [update], unit="metric")

    assert preview["items"] == [
        {
            "id": WALL_08,
            "current": {"y2": 3.0, "variant": "drywall"},
            "proposed": {"y2": 4.0, "variant": "brick"},
            "cleared": [],
        }
    ]
    assert (preview["count"], preview["unchanged"]) == (1, 0)
    assert console.writes() == []


async def test_update_equal_to_the_stored_wall_sends_nothing(connected, console):
    ready(console)
    same = {"id": WALL_08, "x1": 4.0, "y1": 3.0, "x2": 8.0, "y2": 3.0, "variant": "drywall"}

    result = await InnerSpaceWallManager(connected).apply_update_walls(PLAN_A, [same], unit="metric")

    assert (result.success, result.mutation_applied) == (True, False)
    assert console.writes() == []


async def test_update_sends_only_the_walls_that_change(connected, console):
    ready(console)
    walls = [{"id": WALL_08, "variant": "drywall"}, {"id": WALL_09, "variant": "metal"}]

    result = await InnerSpaceWallManager(connected).apply_update_walls(PLAN_A, walls, unit="metric")

    assert [w["id"] for w in console.shape_changes()[0]["update"]] == [WALL_09]
    assert result.success is True


@pytest.mark.parametrize("change", ["vanished", "other_type", "other_plan"])
async def test_apply_rereads_and_refuses_changed_shape(connected, console, change):
    """Focus 1: a browser edit between preview and confirm is refused and nothing is sent."""
    console.load_project(internal_state())
    script_preview(console)
    manager = InnerSpaceWallManager(connected)
    walls = [{"id": WALL_09, "variant": "metal"}, {"id": WALL_08, "variant": "glass"}]
    assert (await manager.preview_update_walls(PLAN_A, walls, unit="metric"))["count"] == 2

    shapes = console.project["shapes"]
    index = next(i for i, s in enumerate(shapes) if s["id"] == WALL_08)
    if change == "vanished":
        del shapes[index]
    elif change == "other_type":
        shapes[index]["type"] = "attenuationObject"
    else:
        shapes[index]["planId"] = PLAN_B
    console.script_write(floor_plans=floor_plan_rows())
    script_preview(console)

    with pytest.raises(UniFiNotFoundError, match="item 1"):
        await manager.apply_update_walls(PLAN_A, walls, unit="metric")
    if change == "vanished":
        # Gone from the whole project: a retried remove, so a no-op rather than a refusal.
        assert (await manager.preview_remove_walls(PLAN_A, [WALL_08]))["no_op"] is True
    else:
        with pytest.raises(UniFiNotFoundError):
            await manager.preview_remove_walls(PLAN_A, [WALL_08])
    assert console.writes() == []


async def test_update_refuses_a_device_id(connected, console):
    ready(console)

    with pytest.raises(UniFiNotFoundError):
        await InnerSpaceWallManager(connected).apply_update_walls(
            PLAN_A, [{"id": DEVICE_11, "variant": "glass"}], unit="metric"
        )

    assert console.writes() == []


async def test_remove_sends_the_stored_walls(connected, console):
    ready(console)

    result = await InnerSpaceWallManager(connected).apply_remove_walls(PLAN_A, [WALL_08, WALL_09])

    assert console.shape_changes() == [
        {"create": [], "update": [], "remove": [stored_copy(WALL_08), stored_copy(WALL_09)], "mode": "2D"}
    ]
    assert result.success is True and result.mutation_applied is True
    assert stored_shape(console, WALL_08) is None and stored_shape(console, WALL_09) is None


@pytest.mark.parametrize("read_back", ["no_plans_no_shapes", "plan_without_shapes", "plan_still_full"])
async def test_a_remove_counts_as_applied_only_on_a_plausible_read_back(connected, console, read_back):
    """Absence alone is not proof: an empty or truncated read-back is unknown, not applied."""
    ready(console)
    console.reply("POST", SHAPE_CHANGE_PATH, {"error": {"code": "errors.unhandled"}}, status=500)
    after = internal_state()
    if read_back == "no_plans_no_shapes":
        after["plans"], after["shapes"] = [], []
    elif read_back == "plan_without_shapes":
        after["shapes"] = [s for s in after["shapes"] if s.get("planId") != PLAN_A]
    else:
        # Removed as asked; every other shape of the plan is still there.
        after["shapes"] = [s for s in after["shapes"] if s["id"] not in (WALL_08, WALL_09)]
    # The first read is the one apply builds from; the second is the read-back.
    console.reply("GET", INTERNAL_PROJECT_PATH, {"data": internal_state()})
    console.reply("GET", INTERNAL_PROJECT_PATH, {"data": after})

    result = await InnerSpaceWallManager(connected).apply_remove_walls(PLAN_A, [WALL_08, WALL_09])

    assert len(console.shape_changes()) == 1
    if read_back == "plan_still_full":
        assert (result.success, result.mutation_applied) == (True, True)
    else:
        assert (result.success, result.mutation_applied) == (False, None)


async def test_a_retried_remove_finds_nothing_left_and_sends_nothing(connected, console):
    ready(console, writes=2)
    manager = InnerSpaceWallManager(connected)
    first = await manager.apply_remove_walls(PLAN_A, [WALL_08, WALL_09])
    script_preview(console)

    preview = await manager.preview_remove_walls(PLAN_A, [WALL_08, WALL_09])
    retry = await manager.apply_remove_walls(PLAN_A, [WALL_08, WALL_09])

    assert first.mutation_applied is True
    assert preview["no_op"] is True and preview["count"] == 0
    assert (retry.success, retry.mutation_applied) == (True, False)
    # The ids are absent: removed earlier, or never there. The reply cannot tell which, and says so.
    assert retry.metadata["noop"] == "none_found"
    # The reason travels once, as the code; the server turns it into its one message.
    assert retry.metadata["warnings"] == []
    assert len(console.shape_changes()) == 1


async def test_a_remove_naming_some_absent_ids_is_refused(connected, console):
    ready(console, writes=2)
    manager = InnerSpaceWallManager(connected)
    await manager.apply_remove_walls(PLAN_A, [WALL_08])

    with pytest.raises(UniFiNotFoundError):
        await manager.apply_remove_walls(PLAN_A, [WALL_08, WALL_09])

    assert len(console.shape_changes()) == 1


async def test_remove_preview_lists_the_walls_in_the_project_unit(connected, console):
    console.load_project(internal_state("imperial"))
    script_preview(console)

    preview = await InnerSpaceWallManager(connected).preview_remove_walls(PLAN_A, [WALL_08])

    assert preview["items"] == [
        {
            "id": WALL_08,
            "current": {
                "x1": 13.1232,
                "y1": 9.8424,
                "x2": 26.2464,
                "y2": 9.8424,
                "variant": "drywall",
                "wall_type_id": None,
            },
        }
    ]
    assert (preview["count"], preview["unit"]) == (1, "imperial")
    assert console.writes() == []


async def test_caps_are_enforced_before_any_request(connected, console):
    ready(console)
    manager = InnerSpaceWallManager(connected)
    start = len(console.requests)
    ids = [f"00000000-0000-4000-8000-{n:012d}" for n in range(101)]

    with pytest.raises(ValidationError):
        await manager.apply_create_walls(PLAN_A, [FRAME_WALL] * 101, unit="metric")
    with pytest.raises(ValidationError):
        await manager.apply_update_walls(PLAN_A, [{"id": i, "variant": "glass"} for i in ids], unit="metric")
    with pytest.raises(ValidationError):
        await manager.apply_remove_walls(PLAN_A, ids[:51])
    assert console.requests[start:] == []

    result = await manager.apply_create_walls(PLAN_A, [FRAME_WALL] * 100, unit="metric")
    assert result.success is True
    assert len(console.shape_changes()[0]["create"]) == 100


async def test_wall_bodies_never_carry_a_map_shape(connected, console):
    ready(console, writes=3)
    manager = InnerSpaceWallManager(connected)
    await manager.apply_create_walls(PLAN_A, [FRAME_WALL], unit="metric")
    await manager.apply_update_walls(PLAN_A, [{"id": WALL_08, "variant": "glass"}], unit="metric")
    await manager.apply_remove_walls(PLAN_A, [WALL_09])

    sent = [item for body in console.shape_changes() for kind in ("create", "update", "remove") for item in body[kind]]
    assert len(sent) == 3
    assert {item["type"] for item in sent} == {"wall"}


@pytest.mark.parametrize("kind", ["map", "scale"])
def test_shape_change_body_refuses_map_and_stray_scale(kind):
    with pytest.raises(InnerSpaceWriteRefusedError):
        shape_change_body(remove=[{"id": "x", "type": kind}])

    assert shape_change_body(create=[{"id": "y", "type": "scale"}], scale=True)["create"]


@pytest.mark.parametrize("offset, applied", [(0.005, True), (0.02, None)])
async def test_read_back_tolerance(connected, console, offset, applied):
    """A stored position within the tolerance counts as in place; beyond it the outcome is unknown."""
    state = internal_state()
    ready(console, state)
    after = deepcopy(state)
    wall = next(s for s in after["shapes"] if s["id"] == WALL_08)
    wall["position"] = [{"x": -100.0, "y": 100.0, "z": 0}, {"x": 300.0 + offset, "y": 0.0 - offset, "z": 0}]
    console.reply("GET", INTERNAL_PROJECT_PATH, {"data": state})
    # The same stored state for every read the settle waits may make.
    console.reply("GET", INTERNAL_PROJECT_PATH, {"data": after}, times=1 + len(READBACK_SETTLE_DELAYS_SECONDS))
    update = {"id": WALL_08, "x1": 4.0, "y1": 3.0, "x2": 8.0, "y2": 4.0}

    result = await InnerSpaceWallManager(connected).apply_update_walls(PLAN_A, [update], unit="metric")

    assert result.mutation_applied is applied
    assert POSITION_TOLERANCE == 0.01


# ---------------------------------------------------------------------------
# Retries: ids depend only on the call, so a retry finds its own objects
# ---------------------------------------------------------------------------


async def test_retry_after_a_lost_answer_sends_nothing(connected, console):
    ready(console, writes=2)
    console.drop_connection("POST", SHAPE_CHANGE_PATH, apply=True)
    manager = InnerSpaceWallManager(connected)

    first = await manager.apply_create_walls(PLAN_A, [FRAME_WALL], unit="metric")
    retry = await manager.apply_create_walls(PLAN_A, [FRAME_WALL], unit="metric")

    assert first.success is True and first.mutation_applied is True
    assert len(console.shape_changes()) == 1
    assert (retry.success, retry.mutation_applied) == (True, False)
    assert retry.metadata["noop"] == "already_applied"
    assert retry.metadata["created_ids"] == first.metadata["created_ids"]
    assert retry.metadata["warnings"] == []
    assert len([s for s in console.project["shapes"] if s["type"] == "wall" and s["planId"] == PLAN_A]) == 4


async def test_a_second_identical_create_is_a_no_op(connected, console):
    ready(console, writes=2)
    manager = InnerSpaceWallManager(connected)

    await manager.apply_create_walls(PLAN_A, [FRAME_WALL], unit="metric")
    second = await manager.apply_create_walls(PLAN_A, [FRAME_WALL], unit="metric")

    assert len(console.shape_changes()) == 1
    assert second.metadata["noop"] == "already_applied"


async def test_an_identical_create_after_all_its_objects_were_removed_creates_them_again(connected, console):
    """Removed entirely, the objects are created again under the same ids (as on 1.4.3); nothing is refused."""
    ready(console, writes=3)
    walls = [FRAME_WALL, {**FRAME_WALL, "y1": 2.0, "y2": 2.0}]
    manager = InnerSpaceWallManager(connected)

    first = await manager.apply_create_walls(PLAN_A, walls, unit="metric")
    created = first.metadata["created_ids"]
    removed = await manager.apply_remove_walls(PLAN_A, created)
    again = await manager.apply_create_walls(PLAN_A, walls, unit="metric")

    assert removed.mutation_applied is True
    assert (again.success, again.mutation_applied) == (True, True)
    assert again.metadata["created_ids"] == created
    assert "noop" not in again.metadata
    assert len(console.shape_changes()) == 3
    assert all(stored_shape(console, shape_id) is not None for shape_id in created)


@pytest.mark.parametrize("earlier", ["partly_applied", "edited_since", "partly_removed"])
async def test_retry_is_refused_when_only_part_of_an_earlier_call_is_in_place(connected, console, earlier):
    ready(console, writes=2)
    walls = [FRAME_WALL, {**FRAME_WALL, "y1": 2.0, "y2": 2.0}]
    manager = InnerSpaceWallManager(connected)
    if earlier == "partly_applied":
        console.mixed_batch(1)
    first = await manager.apply_create_walls(PLAN_A, walls, unit="metric")
    if earlier == "edited_since":
        stored_shape(console, first.metadata["created_ids"][1])["variant"] = "glass"
    if earlier == "partly_removed":
        console.project["shapes"].remove(stored_shape(console, first.metadata["created_ids"][1]))

    with pytest.raises(
        InnerSpaceWriteRefusedError, match="change an argument or remove the existing object"
    ) as refused:
        await manager.apply_create_walls(PLAN_A, walls, unit="metric")

    assert len(console.shape_changes()) == 1
    # Removed entirely would be created again, so the text names only the partial case.
    assert "some of those objects were removed while others remain" in str(refused.value)


async def test_preview_reports_an_identical_object_already_there(connected, console):
    ready(console)
    manager = InnerSpaceWallManager(connected)
    created = await manager.apply_create_walls(PLAN_A, [FRAME_WALL], unit="metric")
    script_preview(console)

    preview = await manager.preview_create_walls(PLAN_A, [FRAME_WALL], unit="metric")

    assert preview["no_op"] is True
    assert "An identical object from an earlier call already exists; confirming sends nothing" in preview["warnings"]
    assert created.metadata["created_ids"][0] not in repr(preview)


# ---------------------------------------------------------------------------
# Previews run the same app checks as a write (without the lock)
# ---------------------------------------------------------------------------


async def test_preview_refuses_what_apply_refuses_with_the_same_text(connected, console):
    console.load_project(internal_state())
    app = {"name": "innerspace", "isInstalled": True, "isRunning": False, "version": "1.4.3"}
    for _ in range(2):
        console.reply("GET", SYSTEM_PATH, {"apps": {"controllers": [app]}})
    manager = InnerSpaceWallManager(connected)

    with pytest.raises(InnerSpaceUnavailableError) as previewed:
        await manager.preview_create_walls(PLAN_A, [FRAME_WALL], unit="metric")
    with pytest.raises(InnerSpaceUnavailableError) as applied:
        await manager.apply_create_walls(PLAN_A, [FRAME_WALL], unit="metric")

    assert str(previewed.value).replace("preview ", "") == str(applied.value)
    assert console.writes() == []
