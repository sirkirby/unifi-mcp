"""The shared InnerSpace write layer: app checks, write lock, no replay, read-back outcome, ids."""

import asyncio
import logging
import uuid

import aiohttp
import pytest
from unifi_core.exceptions import UniFiPermissionError
from unifi_core.innerspace.managers import connection_manager as cm_module
from unifi_core.innerspace.managers._writes import (
    locked_write,
    plan_path,
    read_internal_project,
    send_write,
    write_ids,
)
from unifi_core.innerspace.managers.connection_manager import (
    ATTENUATION_OBJECT_TYPE_PATH,
    INTEGRATION_PREFIX,
    INTERNAL_PROJECT_PATH,
    PLAN_ORDER_PATH,
    PLAN_PATH_PREFIX,
    SHAPE_CHANGE_PATH,
    SYSTEM_PATH,
    WALL_TYPE_PATH,
    InnerSpaceUnavailableError,
    InnerSpaceWriteNotSent,
    InnerSpaceWriteOutcomeUnknown,
)

from tests.innerspace.helpers import PLAN_A, PLAN_B, floor_plan_rows, internal_state, new_wall, stored_shape

OP = "create InnerSpace walls"
WALL_1 = "00000000-0000-4000-8000-0000000000a1"
WALL_2 = "00000000-0000-4000-8000-0000000000a2"
EXISTING_WALL = "00000000-0000-4000-8000-000000000008"
FLOOR_PLANS = f"{INTEGRATION_PREFIX}/floor_plans"


def _matches(stored, wanted):
    if stored is None:
        return False
    return stored["position"] == wanted["position"] and stored["variant"] == wanted["variant"]


async def _create(cm, walls):
    """A minimal write built from the shared layer: one shape/change, read back by id."""
    body = {"create": walls, "update": [], "remove": [], "mode": "2D"}

    async def read_back():
        stored = {s["id"]: s for s in (await read_internal_project(cm, operation=OP))["shapes"]}
        return {w["id"]: _matches(stored.get(w["id"]), w) for w in walls}

    metadata = {"created_ids": [w["id"] for w in walls]}
    return await send_write(cm, "POST", SHAPE_CHANGE_PATH, body, operation=OP, read_back=read_back, metadata=metadata)


async def _apply(cm, walls):
    async with locked_write(cm, operation=OP):
        return await _create(cm, walls)


def _since(console, start):
    return [(r.method, r.path) for r in console.requests[start:]]


# ---------------------------------------------------------------------------
# Outcome of a write: exactly one request, then the read-back decides
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case, walls, applied, success",
    [
        ("accepted", [WALL_1], True, True),
        ("applied_then_timed_out", [WALL_1], True, True),
        ("dropped_before_applying", [WALL_1], None, False),
        ("rejected_400", [WALL_1], False, False),
        ("duplicate_already_applied", [EXISTING_WALL], True, True),
        ("mixed", [WALL_1, WALL_2], None, False),
        ("read_back_failed", [WALL_1], None, False),
    ],
)
async def test_write_outcome_matrix(manager, console, case, walls, applied, success):
    state = internal_state()
    shapes = [new_wall(shape_id, x=10.0 * index) for index, shape_id in enumerate(walls)]
    if case == "duplicate_already_applied":
        state["shapes"] = [s for s in state["shapes"] if s["id"] != EXISTING_WALL] + [dict(shapes[0])]
    if case == "rejected_400":
        del shapes[0]["position"]
    console.load_project(state)
    if case == "applied_then_timed_out":
        manager._timeout = aiohttp.ClientTimeout(total=0.05)
        console.apply_then_hang("POST", SHAPE_CHANGE_PATH)
    elif case == "dropped_before_applying":
        console.drop_connection("POST", SHAPE_CHANGE_PATH, apply=False)
    elif case == "mixed":
        console.mixed_batch(1)
    elif case == "read_back_failed":
        console.drop_connection("POST", SHAPE_CHANGE_PATH, apply=True)
        console.reply("GET", INTERNAL_PROJECT_PATH, {"error": {"code": "errors.unhandled"}}, status=500)
    assert await manager.initialize() is True

    result = await _create(manager, shapes)

    assert len(console.calls("POST", SHAPE_CHANGE_PATH)) == 1
    assert result.mutation_applied is applied
    assert result.success is success
    assert result.metadata["created_ids"] == walls
    if applied is None:
        assert "read before retrying" in result.error.lower()
    if case == "mixed":
        # A partial read-back names an edit made at the same time as a likely cause.
        assert "at the same time" in result.error
    if case == "read_back_failed":
        assert result.metadata["missing"] is None
    elif applied is not True:
        assert result.metadata["missing"]
    if case in ("applied_then_timed_out", "duplicate_already_applied"):
        (warning,) = result.metadata["warnings"]
        assert "already applied" not in warning
        if case == "applied_then_timed_out":
            assert warning == (
                "The read-back shows every change in place: applied, although the console's answer was lost"
            )
        else:
            assert warning == (
                "The read-back shows every change in place: applied, although the console answered HTTP 500 "
                "(errors.unhandled)"
            )
    if case == "accepted":
        assert result.metadata["warnings"] == []
        assert result.error is None


@pytest.mark.parametrize("status", [401, 403])
async def test_no_replay_on_refused_session(connected, console, status):
    console.load_project(internal_state())
    console.expire_session(status)
    start = len(console.requests)

    result = await _create(connected, [new_wall(WALL_1)])

    assert len(console.calls("POST", SHAPE_CHANGE_PATH)) == 1
    assert console.logins == 2
    assert result.success is False
    assert result.mutation_applied is False
    assert "not sent" in result.error
    assert stored_shape(console, WALL_1) is None
    # Nothing was sent, so nothing is read back either.
    assert ("GET", INTERNAL_PROJECT_PATH) not in _since(console, start)


@pytest.mark.parametrize("status", [401, 403])
async def test_a_second_refused_write_is_a_permission_error(connected, console, status):
    """An account that can read but not write: the second refusal in a row stops, without another login."""
    console.load_project(internal_state())
    console.expire_session(status)
    first = await _create(connected, [new_wall(WALL_1)])
    console.expire_session(status)

    with pytest.raises(UniFiPermissionError, match="cannot make this change"):
        await _create(connected, [new_wall(WALL_1)])

    assert first.mutation_applied is False
    assert len(console.calls("POST", SHAPE_CHANGE_PATH)) == 2
    assert console.logins == 2
    assert stored_shape(console, WALL_1) is None


async def test_a_unifi_os_403_on_a_write_reads_back_and_renews_the_session(connected, console):
    """A 403 without an ``errors.*`` code (UniFi OS, e.g. a stale CSRF token): read back, new session, no replay."""
    console.load_project(internal_state())
    console.reply("POST", SHAPE_CHANGE_PATH, status=403, body_bytes=b"Forbidden")
    start = len(console.requests)

    result = await _create(connected, [new_wall(WALL_1)])

    assert len(console.calls("POST", SHAPE_CHANGE_PATH)) == 1
    assert (result.success, result.mutation_applied) == (False, False)
    assert "HTTP 403" in result.error
    assert console.logins == 2
    assert ("GET", INTERNAL_PROJECT_PATH) in _since(console, start)
    assert console.requests[-1].headers["X-CSRF-Token"] == "csrf-2"


async def test_a_second_unifi_os_403_on_a_write_reads_back_without_logging_in_again(connected, console):
    """Two code-less 403 writes in a row: one renewal in all. The second was sent, so the read-back decides;
    it never claims nothing changed on its own."""
    console.load_project(internal_state())
    for _ in range(2):
        console.reply("POST", SHAPE_CHANGE_PATH, status=403, body_bytes=b"Forbidden")
    first = await _create(connected, [new_wall(WALL_1)])
    start = len(console.requests)

    second = await _create(connected, [new_wall(WALL_1)])

    assert first.mutation_applied is False
    assert (second.success, second.mutation_applied) == (False, False)
    assert "cannot make this change" in second.error
    assert ("GET", INTERNAL_PROJECT_PATH) in _since(console, start)
    assert len(console.calls("POST", SHAPE_CHANGE_PATH)) == 2
    assert console.logins == 2
    assert stored_shape(console, WALL_1) is None


async def test_replay_false_raises_not_sent_after_renewing_the_session(connected, console):
    console.load_project(internal_state())
    console.expire_session()

    with pytest.raises(InnerSpaceWriteNotSent) as caught:
        await connected.request(
            "POST", SHAPE_CHANGE_PATH, operation=OP, json={"create": [new_wall(WALL_1)], "mode": "2D"}, replay=False
        )

    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert connected.is_connected
    assert len(console.calls("POST", SHAPE_CHANGE_PATH)) == 1


async def test_replay_false_raises_outcome_unknown_without_chaining(connected, console):
    console.load_project(internal_state())
    console.drop_connection("POST", SHAPE_CHANGE_PATH, apply=False)

    with pytest.raises(InnerSpaceWriteOutcomeUnknown) as caught:
        await connected.request(
            "POST", SHAPE_CHANGE_PATH, operation=OP, json={"create": [new_wall(WALL_1)], "mode": "2D"}, replay=False
        )

    assert str(caught.value).startswith(f"{OP}: ")
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert len(console.calls("POST", SHAPE_CHANGE_PATH)) == 1


async def test_read_back_failure_logs_the_class_only(connected, console, caplog):
    console.load_project(internal_state())
    console.reply("GET", INTERNAL_PROJECT_PATH, {"error": {"code": "errors.unhandled"}}, status=500)

    with caplog.at_level(logging.DEBUG):
        result = await _create(connected, [new_wall(WALL_1)])

    assert result.mutation_applied is None
    assert "InnerSpaceHttpError" in caplog.text
    assert WALL_1 not in caplog.text
    assert SHAPE_CHANGE_PATH in caplog.text


async def test_a_read_back_with_no_changes_in_it_is_unknown(connected, console):
    """An empty read-back proves nothing either way, so it is never counted as applied."""
    console.load_project(internal_state())

    async def read_back():
        return {}

    result = await send_write(
        connected, "POST", SHAPE_CHANGE_PATH, {"create": [], "mode": "2D"}, operation=OP, read_back=read_back
    )

    assert (result.success, result.mutation_applied) == (False, None)
    assert result.metadata["missing"] is None
    assert "nothing to compare" in result.error and "Read before retrying" in result.error


async def _settled(connected, console, reads, *, status=None, body=b"{}", drop=False, held_remaining=None):
    """send_write with a scripted read-back sequence and a recorded, instant sleep on the manager."""
    from unittest.mock import patch

    from unifi_core.write_verification import READBACK_SETTLE_DELAYS_SECONDS

    console.load_project(internal_state())
    if drop:
        console.drop_connection("POST", SHAPE_CHANGE_PATH, apply=False)
    elif status is not None:
        console.reply("POST", SHAPE_CHANGE_PATH, status=status, body_bytes=body)
    remaining, slept = list(reads), []

    async def read_back():
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    async def sleep(seconds):
        slept.append(seconds)

    connected.readback_sleep = sleep
    with patch("unifi_core.write_verification.held_write_remaining_seconds", return_value=held_remaining):
        result = await send_write(
            connected, "POST", SHAPE_CHANGE_PATH, {"create": [], "mode": "2D"}, operation=OP, read_back=read_back
        )
    return result, slept, READBACK_SETTLE_DELAYS_SECONDS


async def test_a_stale_first_read_back_settles_to_applied(connected, console):
    """Like Network's client writes: a read made just after the write can show the old state."""
    result, slept, delays = await _settled(connected, console, [{"x": False}, {"x": True}])

    assert (result.success, result.mutation_applied) == (True, True)
    assert slept == [delays[0]]


async def test_an_unreadable_answer_the_console_accepted_settles_too(connected, console):
    """A 2xx whose body is not JSON was accepted: it gets the same settle waits as a readable one."""
    result, slept, delays = await _settled(connected, console, [{"x": False}, {"x": True}], status=200, body=b"")

    assert (result.success, result.mutation_applied) == (True, True)
    assert slept == [delays[0]]


async def test_an_accepted_write_that_never_shows_is_unknown_not_unapplied(connected, console):
    """The console said yes and the reads still show the old state: the change may yet appear, so unknown."""
    result, slept, delays = await _settled(connected, console, [{"x": False}])

    assert (result.success, result.mutation_applied) == (False, None)
    assert slept == list(delays)
    assert "Read before retrying" in result.error


async def test_a_lost_answer_that_never_shows_is_unknown(connected, console):
    result, _slept, _delays = await _settled(connected, console, [{"x": False}], drop=True)

    assert (result.success, result.mutation_applied) == (False, None)


async def test_a_lost_answer_whose_waits_the_hold_budget_cut_short_is_unknown(connected, console):
    result, slept, _delays = await _settled(connected, console, [{"x": False}], drop=True, held_remaining=1.0)

    assert (result.success, result.mutation_applied) == (False, None)
    assert slept == []


async def test_a_server_error_with_an_unchanged_read_back_is_unknown(connected, console):
    """A 504 from the UniFi OS proxy says nothing about whether InnerSpace applied the write."""
    result, slept, _delays = await _settled(connected, console, [{"x": False}], status=504)

    assert (result.success, result.mutation_applied) == (False, None)
    assert slept == []


async def test_a_write_the_console_refused_is_not_waited_on(connected, console):
    """A 4xx refusal is the console's own verdict: one read-back decides, with no settle wait."""
    result, slept, _delays = await _settled(connected, console, [{"x": False}], status=400)

    assert (result.success, result.mutation_applied) == (False, False)
    assert slept == []


async def test_a_read_back_that_raises_after_the_write_was_sent_is_unknown(connected, console, caplog):
    """Any error from the read-back, not only a UniFi one, leaves the outcome unknown: the write went out."""
    console.load_project(internal_state())

    async def read_back():
        raise TypeError("detail that must not be logged")

    with caplog.at_level(logging.DEBUG):
        result = await send_write(
            connected, "POST", SHAPE_CHANGE_PATH, {"create": [], "mode": "2D"}, operation=OP, read_back=read_back
        )

    assert (result.success, result.mutation_applied) == (False, None)
    assert result.metadata["missing"] is None
    assert "detail that must not be logged" not in caplog.text
    assert "TypeError" in caplog.text


# ---------------------------------------------------------------------------
# App checks: installed and running; nothing else refuses a write
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", [{"isInstalled": False}, {"isRunning": False}], ids=["not-installed", "not-running"])
async def test_a_write_is_refused_when_innerspace_is_not_installed_or_not_running(connected, console, entry):
    console.load_project(internal_state())
    app = {"name": "innerspace", "isInstalled": True, "isRunning": True, "version": "1.4.3", **entry}
    console.reply("GET", SYSTEM_PATH, {"apps": {"controllers": [app]}})
    start = len(console.requests)

    with pytest.raises(InnerSpaceUnavailableError, match="not installed" if "isInstalled" in entry else "not running"):
        await _apply(connected, [new_wall(WALL_1)])

    assert _since(console, start) == [("GET", SYSTEM_PATH)]
    assert console.writes() == []
    assert not connected.write_lock.locked()


@pytest.mark.parametrize("version", ["1.5.0", None], ids=["other-version", "no-version"])
async def test_a_write_runs_on_any_version_with_read_back(connected, console, version):
    console.load_project(internal_state())
    console.script_write(version=version, floor_plans=floor_plan_rows())

    result = await _apply(connected, [new_wall(WALL_1)])

    assert (result.success, result.mutation_applied) == (True, True)
    assert len(console.calls("POST", SHAPE_CHANGE_PATH)) == 1
    assert stored_shape(console, WALL_1) is not None


async def test_a_write_runs_when_the_plans_name_two_sites(connected, console):
    rows = floor_plan_rows()
    rows[1]["site_id"] = "00000000-0000-4000-8000-0000000000ff"
    console.load_project(internal_state())
    console.script_write(floor_plans=rows)

    result = await _apply(connected, [new_wall(WALL_1)])

    assert (result.success, result.mutation_applied) == (True, True)
    assert stored_shape(console, WALL_1) is not None


async def test_version_is_read_uncached_on_every_write(connected, console):
    console.load_project(internal_state())
    for _ in range(2):
        console.script_write(floor_plans=floor_plan_rows())

    first = await _apply(connected, [new_wall(WALL_1)])
    second = await _apply(connected, [new_wall(WALL_2, x=50.0)])

    assert first.success and second.success
    assert len(console.calls("GET", SYSTEM_PATH)) == 2
    console.assert_csrf()


# ---------------------------------------------------------------------------
# Write lock
# ---------------------------------------------------------------------------


async def test_second_write_waits_for_the_lock_and_previews_do_not(connected, console):
    console.load_project(internal_state())
    console.script_write(floor_plans=floor_plan_rows())
    console.script_write(floor_plans=floor_plan_rows())
    arrived, release = asyncio.Event(), asyncio.Event()
    console.reply("POST", SHAPE_CHANGE_PATH, {"data": {}}, gate=(arrived, release))

    first = asyncio.create_task(_apply(connected, [new_wall(WALL_1)]))
    await arrived.wait()
    second_waits = asyncio.Event()

    async def second_write():
        second_waits.set()
        return await _apply(connected, [new_wall(WALL_2, x=50.0)])

    second = asyncio.create_task(second_write())
    # The task runs from the set() into the lock without yielding to the loop, so it is waiting there now.
    await second_waits.wait()

    assert connected.write_lock.locked()
    assert len(console.calls("GET", SYSTEM_PATH)) == 1
    # A preview reads while the write holds the lock.
    preview = await asyncio.wait_for(read_internal_project(connected, operation="preview"), 5)
    assert preview["shapes"]

    release.set()
    await first
    assert (await second).success
    order = _since(console, 0)
    first_post = order.index(("POST", SHAPE_CHANGE_PATH))
    second_system = [i for i, call in enumerate(order) if call == ("GET", SYSTEM_PATH)][1]
    assert second_system > first_post


async def test_cancelled_write_releases_the_lock(connected, console):
    console.load_project(internal_state())
    console.script_write(floor_plans=floor_plan_rows())
    console.script_write(floor_plans=floor_plan_rows())
    arrived = asyncio.Event()
    console.reply("POST", SHAPE_CHANGE_PATH, {"data": {}}, gate=(arrived, asyncio.Event()))

    first = asyncio.create_task(_apply(connected, [new_wall(WALL_1)]))
    await arrived.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    assert not connected.write_lock.locked()
    assert (await asyncio.wait_for(_apply(connected, [new_wall(WALL_2, x=50.0)]), 5)).success


# ---------------------------------------------------------------------------
# Deterministic ids
# ---------------------------------------------------------------------------

ARGS = {"plan_id": PLAN_A, "unit": "metric", "walls": [{"x1": 1.0, "y1": 2.0, "x2": 3.0, "y2": 2.0}]}


def test_ids_repeat_for_the_same_call():
    first = write_ids("innerspace_create_walls", ARGS, 2)
    again = write_ids("innerspace_create_walls", dict(reversed(list(ARGS.items()))), 2)

    assert first == again
    assert len(set(first)) == 2
    assert all(uuid.UUID(value).version == 5 for value in first)
    # The index in the batch is part of the seed: the first id of a longer batch is the same.
    assert write_ids("innerspace_create_walls", ARGS, 3)[:2] == first


@pytest.mark.parametrize(
    "tool, args",
    [
        ("innerspace_create_walls", {**ARGS, "plan_id": PLAN_B}),
        ("innerspace_create_walls", {**ARGS, "unit": "imperial"}),
        ("innerspace_create_attenuation_objects", ARGS),
    ],
)
def test_ids_change_with_the_arguments_the_plan_or_the_tool(tool, args):
    assert write_ids(tool, args, 1) != write_ids("innerspace_create_walls", ARGS, 1)


# ---------------------------------------------------------------------------
# Log templates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path, template",
    [
        (SHAPE_CHANGE_PATH, SHAPE_CHANGE_PATH),
        (WALL_TYPE_PATH, WALL_TYPE_PATH),
        (ATTENUATION_OBJECT_TYPE_PATH, ATTENUATION_OBJECT_TYPE_PATH),
        (PLAN_ORDER_PATH, PLAN_ORDER_PATH),
        (f"{PLAN_PATH_PREFIX}/{PLAN_A}", f"{PLAN_PATH_PREFIX}/{{plan_id}}"),
        (INTERNAL_PROJECT_PATH, INTERNAL_PROJECT_PATH),
        (f"{PLAN_PATH_PREFIX}/{PLAN_A}/map", "/{unknown}"),
        ("/proxy/innerspace/api/project/plan/upload/x", "/{unknown}"),
    ],
)
def test_write_routes_log_as_templates(path, template):
    assert cm_module._log_route(path) == template


def test_plan_path_takes_one_segment_only():
    assert plan_path(PLAN_A) == f"{PLAN_PATH_PREFIX}/{PLAN_A}"
    with pytest.raises(ValueError):
        plan_path("order/../x")


@pytest.mark.parametrize("segment", ["order", "ORDER", "Order"])
def test_plan_path_refuses_the_reorder_route_segment(segment):
    """``order`` is the reorder route under the same prefix, never a plan, in any case."""
    from unifi_core.request_paths import InvalidRequestPathError

    with pytest.raises(InvalidRequestPathError):
        plan_path(segment)
