"""Bounded-retention contracts for the shared background job store."""

from __future__ import annotations

import asyncio
import gc

import pytest
from unifi_core.jobs import JOBS, JobStore, cancel_job, current_job_id, get_job_status, start_async_tool
from unifi_core.operation_gate import GateSettings, OperationGate


class _Clock:
    def __init__(self, value: float = 1_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


async def _wait_for_terminal(store: JobStore, job_id: str) -> dict:
    for _ in range(20):
        status = await store.status(job_id)
        if status["status"] not in {"running", "queued"}:
            return status
        await asyncio.sleep(0)
    raise AssertionError(f"job {job_id} did not finish")


@pytest.mark.asyncio
async def test_completed_and_failed_jobs_expire_after_retention_window() -> None:
    clock = _Clock()
    store = JobStore(retention_seconds=60, max_completed_jobs=10, clock=clock)

    async def succeed() -> str:
        return "ok"

    async def fail() -> None:
        raise RuntimeError("expected")

    done_id = await store.start(succeed())
    error_id = await store.start(fail())
    assert (await _wait_for_terminal(store, done_id))["status"] == "done"
    assert (await _wait_for_terminal(store, error_id))["status"] == "error"

    clock.advance(60)

    assert await store.status(done_id) == {"status": "unknown"}
    assert await store.status(error_id) == {"status": "unknown"}


@pytest.mark.asyncio
async def test_completed_job_limit_evicts_oldest_terminal_jobs() -> None:
    clock = _Clock()
    store = JobStore(retention_seconds=3_600, max_completed_jobs=2, clock=clock)
    job_ids: list[str] = []

    for index in range(3):

        async def complete(value: int = index) -> int:
            return value

        job_id = await store.start(complete())
        job_ids.append(job_id)
        assert (await _wait_for_terminal(store, job_id))["status"] == "done"
        clock.advance(1)

    assert await store.status(job_ids[0]) == {"status": "unknown"}
    assert (await store.status(job_ids[1]))["status"] == "done"
    assert (await store.status(job_ids[2]))["status"] == "done"


@pytest.mark.asyncio
async def test_running_jobs_are_never_evicted_by_ttl_or_completed_limit() -> None:
    clock = _Clock()
    store = JobStore(retention_seconds=10, max_completed_jobs=1, clock=clock)
    release = asyncio.Event()

    async def remain_running() -> str:
        await release.wait()
        return "released"

    running_id = await store.start(remain_running())

    for value in range(3):

        async def complete(result: int = value) -> int:
            return result

        completed_id = await store.start(complete())
        await _wait_for_terminal(store, completed_id)
        clock.advance(20)

    assert (await store.status(running_id))["status"] == "running"

    release.set()
    assert (await _wait_for_terminal(store, running_id))["status"] == "done"


@pytest.mark.asyncio
async def test_concurrent_completions_keep_store_bounded() -> None:
    clock = _Clock()
    store = JobStore(retention_seconds=3_600, max_completed_jobs=5, clock=clock)

    async def complete(value: int) -> int:
        await asyncio.sleep(0)
        return value

    await asyncio.gather(*(store.start(complete(index)) for index in range(40)))
    for _ in range(20):
        if not any(job["status"] == "running" for job in store._jobs.values()):
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("concurrent jobs did not finish")

    terminal_jobs = [job for job in store._jobs.values() if job["status"] != "running"]
    assert len(terminal_jobs) <= 5


def test_retention_policy_rejects_unbounded_or_invalid_values() -> None:
    with pytest.raises(ValueError, match="retention_seconds"):
        JobStore(retention_seconds=-1)
    with pytest.raises(ValueError, match="retention_seconds"):
        JobStore(retention_seconds=float("inf"))
    with pytest.raises(ValueError, match="max_completed_jobs"):
        JobStore(max_completed_jobs=-1)
    with pytest.raises(ValueError, match="max_completed_jobs"):
        JobStore(max_completed_jobs=1.5)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Task references, queued and cancelled states, admission ordering
# ---------------------------------------------------------------------------


async def _settle(rounds: int = 30) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


async def _wait_for_terminal_slowly(store: JobStore, job_id: str) -> dict:
    for _ in range(500):
        status = await store.status(job_id)
        if status["status"] not in {"running", "queued"}:
            return status
        await asyncio.sleep(0)
    raise AssertionError(f"job {job_id} did not finish")


def _gate() -> OperationGate:
    return OperationGate(GateSettings(), name="network")


async def _hold(gate: OperationGate, release: asyncio.Event) -> str:
    async with gate.write(label="holder"):
        await release.wait()
    return "held"


async def test_the_store_keeps_each_task_until_it_finishes() -> None:
    store = JobStore()
    release = asyncio.Event()

    async def wait() -> str:
        await release.wait()
        return "ok"

    job_id = await store.start(wait())
    assert len(store._tasks) == 1
    task = next(iter(store._tasks))
    assert task.get_name() == f"unifi-job-{job_id}"
    gc.collect()
    await _settle()
    assert (await store.status(job_id))["status"] == "running"

    release.set()
    assert (await _wait_for_terminal(store, job_id))["status"] == "done"
    await _settle()
    assert store._tasks == set()
    assert store._runs == {}


async def test_a_job_shows_queued_with_its_position_until_its_write_is_granted() -> None:
    store = JobStore()
    gate = _gate()
    release = asyncio.Event()
    holder_id = await store.start(_hold(gate, release))
    await _settle()

    async def change(value: int) -> int:
        async with gate.write(label="change"):
            return value

    first = await store.start(change(1))
    second = await store.start(change(2))
    await _settle()

    holder_status = await store.status(holder_id)
    assert holder_status["status"] == "running"
    assert "position" not in holder_status
    first_status = await store.status(first)
    assert first_status["status"] == "queued"
    assert first_status["position"] == 1
    assert first_status["result"] is None and first_status["error"] is None
    assert (await store.status(second))["position"] == 2

    release.set()
    assert (await _wait_for_terminal(store, first))["result"] == 1
    assert (await _wait_for_terminal(store, second))["result"] == 2
    assert (await store.status(holder_id))["status"] == "done"


async def test_cancelling_a_queued_job_withdraws_it_before_anything_is_sent() -> None:
    store = JobStore()
    gate = _gate()
    release = asyncio.Event()
    await store.start(_hold(gate, release))
    await _settle()
    sent: list[int] = []

    async def change(value: int) -> int:
        async with gate.write():
            sent.append(value)
            return value

    first = await store.start(change(1))
    second = await store.start(change(2))
    await _settle()

    outcome = await store.cancel(first)
    assert outcome == {"jobId": first, "cancelled": True, "status": "cancelled"}
    status = await store.status(first)
    assert status["status"] == "cancelled"
    assert "completed" in status
    await _settle()
    assert gate.queue_depth == 1
    assert (await store.status(second))["position"] == 1

    release.set()
    assert (await _wait_for_terminal(store, second))["status"] == "done"
    assert sent == [2]
    assert (await store.status(first))["status"] == "cancelled"


async def test_cancel_refuses_running_jobs_and_reports_finished_or_unknown_ones() -> None:
    store = JobStore()
    release = asyncio.Event()

    async def wait() -> str:
        await release.wait()
        return "ok"

    running = await store.start(wait())
    await _settle()
    refused = await store.cancel(running)
    assert refused["cancelled"] is False
    assert refused["status"] == "running"
    assert "cannot be recalled" in refused["reason"]

    release.set()
    await _wait_for_terminal(store, running)
    finished = await store.cancel(running)
    assert finished["cancelled"] is False and finished["status"] == "done"
    assert (await store.status(running))["status"] == "done"

    unknown = await store.cancel("missing")
    assert unknown["cancelled"] is False and unknown["status"] == "unknown"


async def test_a_job_granted_but_not_yet_resumed_can_still_be_cancelled() -> None:
    store = JobStore()
    gate = _gate()
    release = asyncio.Event()
    holder = await store.start(_hold(gate, release))
    await _settle()
    sent: list[str] = []

    async def change(name: str) -> str:
        async with gate.write():
            sent.append(name)
            return name

    second = await store.start(change("second"))
    third = await store.start(change("third"))
    await _settle()

    release.set()
    await asyncio.sleep(0)  # the holder releases and hands its turn to "second"
    assert gate.write_held
    assert (await store.status(second))["status"] == "queued"
    assert (await store.cancel(second))["cancelled"] is True

    assert (await _wait_for_terminal(store, third))["status"] == "done"
    assert (await store.status(holder))["status"] == "done"
    assert (await store.status(second))["status"] == "cancelled"
    assert sent == ["third"]


async def test_a_job_cancelled_after_its_write_ran_is_reported_as_an_error() -> None:
    store = JobStore()
    gate = _gate()
    inside = asyncio.Event()

    async def change() -> None:
        async with gate.write():
            inside.set()
            await asyncio.Event().wait()

    job_id = await store.start(change())
    await inside.wait()
    next(iter(store._tasks)).cancel()
    status = await _wait_for_terminal(store, job_id)
    assert status["status"] == "error"
    assert "may have reached the controller" in status["error"]
    assert not gate.write_held


async def test_chained_job_waits_queued_and_cancelling_it_lets_the_chain_continue() -> None:
    store = JobStore()
    gate = _gate()
    release = asyncio.Event()
    started: list[str] = []
    pre_gate = asyncio.Event()

    async def slow_to_reach_the_gate() -> str:
        started.append("first")
        await pre_gate.wait()
        async with gate.write():
            return "first"

    async def quick(name: str) -> str:
        started.append(name)
        async with gate.write():
            return name

    holder = await store.start(_hold(gate, release))
    first = await store.start(slow_to_reach_the_gate())
    second = await store.start(quick("second"), after=first)
    third = await store.start(quick("third"), after=second)
    await _settle()

    assert started == ["first"]
    second_status = await store.status(second)
    assert second_status["status"] == "queued"
    assert second_status["position"] is None
    assert (await store.cancel(second))["cancelled"] is True
    await _settle()
    # Cancelling "second" admits it, so "third" may start; "first" has not
    # reached the gate, so nothing else moved.
    assert started == ["first", "third"]
    assert (await store.status(third))["position"] == 1

    pre_gate.set()
    release.set()
    assert (await _wait_for_terminal_slowly(store, third))["result"] == "third"
    assert (await _wait_for_terminal_slowly(store, first))["result"] == "first"
    assert (await store.status(holder))["status"] == "done"
    assert (await store.status(second))["status"] == "cancelled"


@pytest.mark.parametrize("chained", [True, False])
async def test_twenty_jobs_reach_the_write_queue_in_submission_order(chained: bool) -> None:
    store = JobStore()
    gate = _gate()
    release = asyncio.Event()
    granted: list[int] = []
    await store.start(_hold(gate, release))
    await _settle()

    async def change(index: int) -> int:
        # Earlier jobs await longer before reaching the gate, as a lazily
        # loaded tool or a reconnect would; only the chain keeps them in order.
        for _ in range(40 - 2 * index):
            await asyncio.sleep(0)
        if index % 5 == 0:
            async with gate.read():
                return index
        async with gate.write():
            granted.append(index)
            return index

    job_ids: list[str] = []
    previous = None
    for index in range(20):
        job_id = await store.start(change(index), after=previous if chained else None)
        job_ids.append(job_id)
        previous = job_id

    await _settle(200)
    release.set()
    for job_id in job_ids:
        await _wait_for_terminal_slowly(store, job_id)

    writes = [index for index in range(20) if index % 5]
    if chained:
        assert granted == writes
    else:
        # The control: without the chain, the jobs that reach the gate first win.
        assert granted != writes


async def test_wait_admitted_orders_jobs_started_one_after_another() -> None:
    store = JobStore()
    gate = _gate()
    release = asyncio.Event()
    granted: list[int] = []
    await store.start(_hold(gate, release))
    await _settle()

    async def change(index: int) -> None:
        for _ in range(20 - index):
            await asyncio.sleep(0)
        async with gate.write():
            granted.append(index)

    async def never_gated() -> str:
        return "no gate"

    job_ids = []
    for index in range(10):
        job_id = await store.start(change(index) if index != 4 else never_gated())
        await store.wait_admitted(job_id)
        job_ids.append(job_id)

    assert gate.queue_depth == 9
    release.set()
    for job_id in job_ids:
        await _wait_for_terminal_slowly(store, job_id)
    assert granted == [0, 1, 2, 3, 5, 6, 7, 8, 9]
    # Unknown and finished jobs never block.
    await asyncio.wait_for(store.wait_admitted("missing"), timeout=1)
    await asyncio.wait_for(store.wait_admitted(job_ids[0]), timeout=1)


async def test_a_job_that_fails_before_the_gate_still_releases_its_chain() -> None:
    store = JobStore()

    async def fail() -> None:
        raise RuntimeError("lazy load failed")

    async def after() -> str:
        return "ran"

    first = await store.start(fail())
    second = await store.start(after(), after=first)
    assert (await _wait_for_terminal_slowly(store, second))["result"] == "ran"
    assert (await store.status(first))["status"] == "error"


async def test_current_job_id_is_visible_inside_the_job() -> None:
    store = JobStore()

    async def report() -> str | None:
        return current_job_id()

    job_id = await store.start(report())
    assert (await _wait_for_terminal(store, job_id))["result"] == job_id
    assert current_job_id() is None


async def test_module_helpers_chain_and_cancel_through_the_global_store() -> None:
    gate = _gate()
    release = asyncio.Event()
    holder = await start_async_tool(_hold, {"gate": gate, "release": release})
    await _settle()

    async def change() -> str:
        async with gate.write():
            return "changed"

    first = await start_async_tool(change, {})
    chained = await start_async_tool(change, {}, after=first["jobId"])
    await _settle()
    assert (await get_job_status(first["jobId"]))["status"] == "queued"
    assert (await cancel_job(chained["jobId"]))["cancelled"] is True
    release.set()
    assert (await _wait_for_terminal(JOBS, first["jobId"]))["result"] == "changed"
    assert (await _wait_for_terminal(JOBS, holder["jobId"]))["status"] == "done"
    assert (await get_job_status(chained["jobId"]))["status"] == "cancelled"
