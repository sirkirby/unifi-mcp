"""The stub's stateful mode reproduces what InnerSpace 1.4.3 did with each write in the live run."""

from copy import deepcopy

import aiohttp
import pytest
from unifi_core.innerspace.managers.connection_manager import (
    ATTENUATION_OBJECT_TYPE_PATH,
    INTERNAL_PROJECT_PATH,
    PLAN_ORDER_PATH,
    PLAN_PATH_PREFIX,
    SHAPE_CHANGE_PATH,
    SYSTEM_PATH,
    WALL_TYPE_PATH,
    InnerSpaceHttpError,
)

from tests.innerspace.helpers import (
    PLAN_A,
    PLAN_B,
    PROJECT_ID,
    WALL_TYPE,
    internal_state,
    new_wall,
    stored_shape,
)

OP = "stub check"
WALL = "00000000-0000-4000-8000-000000000008"
CUSTOM_WALL = "00000000-0000-4000-8000-000000000017"
NEW = "00000000-0000-4000-8000-0000000000b1"
SCALE = "00000000-0000-4000-8000-000000000013"


@pytest.fixture
async def state(connected, console):
    console.load_project(internal_state())
    return console


async def _post(cm, path, body, method="POST"):
    return await cm.request(method, path, operation=OP, json=body)


async def _refused(cm, path, body, status, code, method="POST"):
    with pytest.raises(InnerSpaceHttpError) as caught:
        await _post(cm, path, body, method)
    assert (caught.value.status, caught.value.code) == (status, code)


def _change(**batches):
    return {"create": [], "update": [], "remove": [], "mode": "2D", **batches}


# ---------------------------------------------------------------------------
# shape/change
# ---------------------------------------------------------------------------


async def test_wall_create_update_remove(connected, state):
    await _post(connected, SHAPE_CHANGE_PATH, _change(create=[new_wall(NEW)]))
    stored = stored_shape(state, NEW)
    assert stored["originalPosition"] is None and stored["wallTypeId"] is None

    await _post(connected, SHAPE_CHANGE_PATH, _change(update=[{**stored, "variant": "glass"}]))
    assert stored_shape(state, NEW)["variant"] == "glass"

    await _post(connected, SHAPE_CHANGE_PATH, _change(remove=[stored_shape(state, NEW)]))
    assert stored_shape(state, NEW) is None
    assert state.shape_changes()[0]["create"][0]["id"] == NEW
    state.assert_csrf()


@pytest.mark.parametrize(
    "batches",
    [
        {"update": [{"id": WALL, "variant": "glass"}]},
        {"remove": [WALL]},
        {"remove": [{"id": WALL}]},
        {"create": [new_wall(NEW), {**new_wall(WALL_TYPE), "type": "attenuationObject"}]},
    ],
    ids=["partial-update", "bare-id-remove", "id-only-remove", "open-polygon"],
)
async def test_rejected_batches_change_nothing(connected, state, batches):
    before = deepcopy(state.project)

    # A valid create rides along: the whole batch is rejected.
    body = _change(**{"create": [new_wall(NEW)], **batches})
    await _refused(connected, SHAPE_CHANGE_PATH, body, 400, "errors.invalid.data")

    assert state.project == before


async def test_duplicate_id_create_fails_500_and_keeps_the_stored_shape(connected, state):
    before = deepcopy(state.project)

    await _refused(connected, SHAPE_CHANGE_PATH, _change(create=[new_wall(WALL, x=999.0)]), 500, "errors.unhandled")

    assert state.project == before


async def test_custom_wall_sent_without_its_type_becomes_built_in(connected, state):
    stored = {k: v for k, v in stored_shape(state, CUSTOM_WALL).items() if k != "wallTypeId"}

    await _post(connected, SHAPE_CHANGE_PATH, _change(update=[{**stored, "variant": "drywall"}]))

    assert stored_shape(state, CUSTOM_WALL)["wallTypeId"] is None


async def test_closed_attenuation_object_is_stored_with_a_null_type(connected, state):
    points = [{"x": 0, "y": 0, "z": 0}, {"x": 10, "y": 0, "z": 0}, {"x": 10, "y": 10, "z": 0}]
    shape = {**new_wall(NEW), "type": "attenuationObject", "variant": "car", "position": [*points, points[0]]}

    await _post(connected, SHAPE_CHANGE_PATH, _change(create=[shape]))

    assert stored_shape(state, NEW)["attenuationObjectTypeId"] is None


async def test_scale_replace_needs_computed_scale_and_updates_plan_scales(connected, state):
    old = stored_shape(state, SCALE)
    new = {**old, "id": NEW, "scale": 4.0, "position": [{"x": 0, "y": 0, "z": 0}, {"x": 500, "y": 0, "z": 0}]}
    del new["computedScale"]
    await _refused(connected, SHAPE_CHANGE_PATH, _change(create=[new], remove=[old]), 400, "errors.invalid.data")

    await _post(connected, SHAPE_CHANGE_PATH, _change(create=[{**new, "computedScale": None}], remove=[old]))

    assert state.project["planScales"][PLAN_A]["scale"] == 125.0
    assert stored_shape(state, SCALE) is None


# ---------------------------------------------------------------------------
# Type routes
# ---------------------------------------------------------------------------


def _wall_type(type_id, **overrides):
    return {
        "id": type_id,
        "projectId": PROJECT_ID,
        "name": "Synthetic",
        "attenuation": 7,
        "color": "#123456",
        "isDeleted": False,
        "overridesVariant": None,
        "bottomHeight": None,
        "topHeight": None,
        "transparent": False,
        "autoFillEnabled": False,
        **overrides,
    }


async def test_wall_type_create_update_and_unused_remove(connected, state):
    reply = await _post(connected, WALL_TYPE_PATH, {"create": [_wall_type(NEW)], "update": [], "remove": []})
    assert reply == {"data": {}}

    await _post(connected, WALL_TYPE_PATH, {"update": [_wall_type(NEW, attenuation=9)]})
    await _refused(connected, WALL_TYPE_PATH, {"update": [{"id": NEW, "attenuation": 1}]}, 400, "errors.invalid.data")
    assert [t["attenuation"] for t in state.project["wallTypes"] if t["id"] == NEW] == [9]

    await _post(connected, WALL_TYPE_PATH, {"remove": [{"id": NEW}]})
    assert NEW not in {t["id"] for t in state.project["wallTypes"]}


@pytest.mark.parametrize("path, type_id", [(WALL_TYPE_PATH, WALL_TYPE), (ATTENUATION_OBJECT_TYPE_PATH, NEW)])
async def test_removing_a_type_in_use_fails_500_and_changes_nothing(connected, state, path, type_id):
    if path == ATTENUATION_OBJECT_TYPE_PATH:
        state.project["attenuationObjectTypes"] = [{"id": NEW, "name": "x"}]
        state.project["shapes"].append({"id": "z", "type": "attenuationObject", "attenuationObjectTypeId": NEW})
    before = deepcopy(state.project)

    await _refused(connected, path, {"remove": [{"id": type_id}]}, 500, "errors.unhandled")

    assert state.project == before


# ---------------------------------------------------------------------------
# Plan, order and project routes
# ---------------------------------------------------------------------------


async def test_plan_patch_answers_with_the_whole_project(connected, state):
    reply = await _post(connected, f"{PLAN_PATH_PREFIX}/{PLAN_A}", {"title": " Renamed "}, "PATCH")

    assert set(reply["data"]) == {"plan", "shapes", "products"}
    assert len(reply["data"]["shapes"]) == len(state.project["shapes"])
    assert next(p for p in state.project["plans"] if p["id"] == PLAN_A)["title"] == "Renamed"

    await _post(connected, f"{PLAN_PATH_PREFIX}/{PLAN_A}", {"attenuation": None}, "PATCH")
    await _refused(
        connected, f"{PLAN_PATH_PREFIX}/{PLAN_A}", {"title": "x", "attenuation": 3}, 400, "errors.invalid.data", "PATCH"
    )
    await _refused(connected, f"{PLAN_PATH_PREFIX}/unknown", {"title": "x"}, 404, "errors.route.notFound", "PATCH")


async def test_plan_order_and_project_unit(connected, state):
    reply = await _post(
        connected, PLAN_ORDER_PATH, [{"id": PLAN_A, "ordering": 5}, {"id": PLAN_B, "ordering": 4}], "PATCH"
    )
    assert {p["id"]: p["ordering"] for p in reply["data"]["plans"]}[PLAN_A] == 5

    assert await _post(connected, INTERNAL_PROJECT_PATH, {"unit": "imperial"}, "PATCH") == {}
    assert state.project["project"]["unit"] == "imperial"
    assert [w.method for w in state.writes()] == ["PATCH", "PATCH"]


# ---------------------------------------------------------------------------
# Session, CSRF and helpers
# ---------------------------------------------------------------------------


async def _raw(state, headers):
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{state.base_url}{SHAPE_CHANGE_PATH}", json=_change(create=[new_wall(NEW)]), headers=headers
        ) as response:
            return response.status, await response.text()


async def test_missing_csrf_gets_the_unifi_os_403_and_nothing_is_applied(connected, state):
    status, text = await _raw(state, {"Cookie": "TOKEN=session-1"})

    assert (status, text) == (403, "Forbidden")
    assert stored_shape(state, NEW) is None
    with pytest.raises(AssertionError):
        state.assert_csrf()


async def test_invalid_session_gets_errors_api_access_and_nothing_is_applied(connected, state):
    status, text = await _raw(state, {"Cookie": "TOKEN=forged", "X-CSRF-Token": "csrf-1"})

    assert status == 403 and "errors.api.access" in text
    assert stored_shape(state, NEW) is None


async def test_a_scripted_reply_wins_over_the_state(connected, state):
    state.reply("GET", INTERNAL_PROJECT_PATH, {"error": {"code": "errors.unhandled"}}, status=500)

    with pytest.raises(InnerSpaceHttpError):
        await connected.request("GET", INTERNAL_PROJECT_PATH, operation=OP)
    assert (await connected.request("GET", INTERNAL_PROJECT_PATH, operation=OP))["data"]["project"]["id"] == PROJECT_ID


async def test_script_write_without_a_version(connected, state):
    state.script_write(version=None)

    (entry,) = (await connected.request("GET", SYSTEM_PATH, operation=OP))["apps"]["controllers"]
    assert "version" not in entry and entry["isRunning"] is True
