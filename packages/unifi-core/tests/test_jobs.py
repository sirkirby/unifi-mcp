"""Bounded-retention contracts for the shared background job store."""

from __future__ import annotations

import asyncio
import gc
import logging
import random

import pytest
from unifi_core.jobs import (
    JOBS,
    TERMINAL_JOB_STATUSES,
    JobStore,
    cancel_job,
    current_job_id,
    get_job_status,
    start_async_tool,
)
from unifi_core.operation_gate import GateSettings, OperationGate, signal_admitted


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
    granted_not_resumed = await store.status(second)
    assert granted_not_resumed["status"] == "queued"
    assert granted_not_resumed["position"] == 0
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


@pytest.mark.parametrize("how", ["cancel", "task_cancel"])
async def test_cancelling_a_middle_chained_job_keeps_the_rest_in_order(how: str) -> None:
    store = JobStore()
    gate = _gate()
    release = asyncio.Event()
    started: list[str] = []
    granted: list[str] = []
    pre_gate = asyncio.Event()

    async def slow_to_reach_the_gate() -> str:
        started.append("first")
        await pre_gate.wait()  # a lazy tool load or a reconnect
        async with gate.write():
            granted.append("first")
            return "first"

    async def quick(name: str) -> str:
        started.append(name)
        async with gate.write():
            granted.append(name)
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
    if how == "cancel":
        assert (await store.cancel(second))["cancelled"] is True
    else:
        # The runner itself cancelled (a shutdown) while it waits for "first".
        store._runs[second].task.cancel()
    await _settle()
    # "second" held no place at the gate, and "first" has not reached it yet:
    # "third" must keep waiting behind "first".
    assert started == ["first"]
    assert (await store.status(second))["status"] == "cancelled"
    assert (await store.status(third))["status"] == "queued"
    waiting_on_second = asyncio.create_task(store.wait_admitted(second))
    await _settle()
    assert not waiting_on_second.done()

    pre_gate.set()
    await _settle()
    assert started == ["first", "third"]
    assert waiting_on_second.done()
    release.set()
    assert (await _wait_for_terminal_slowly(store, third))["result"] == "third"
    assert (await _wait_for_terminal_slowly(store, first))["result"] == "first"
    assert granted == ["first", "third"]
    assert (await store.status(holder))["status"] == "done"
    assert (await store.status(second))["status"] == "cancelled"
    await _settle()
    assert store._runs == {}
    assert store._tasks == set()


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


# ---------------------------------------------------------------------------
# Regressions: terminal states, jobs started inside a write, early cancellation
# ---------------------------------------------------------------------------


async def test_a_cancelled_job_stays_cancelled_even_if_its_coroutine_swallows_the_cancel() -> None:
    store = JobStore()
    gate = _gate()
    release = asyncio.Event()
    await store.start(_hold(gate, release))
    await _settle()

    async def tolerant() -> dict:
        try:
            async with gate.write():
                return {"success": True}
        except asyncio.CancelledError:
            return {"success": False, "error": "cancelled"}

    job_id = await store.start(tolerant())
    await _settle()
    assert (await store.cancel(job_id))["cancelled"] is True
    await _settle()
    status = await store.status(job_id)
    assert status["status"] == "cancelled"
    assert status["result"] is None
    release.set()
    await _settle()
    assert (await store.status(job_id))["status"] == "cancelled"
    assert store._runs == {}


async def test_a_job_started_inside_a_held_write_queues_for_the_gate() -> None:
    store = JobStore()
    gate = _gate()

    async def change() -> str:
        async with gate.write():
            return "job wrote"

    async with gate.write():
        job_id = await store.start(change())
        await _settle()
        status = await store.status(job_id)
        assert status["status"] == "queued"
        assert status["position"] == 1

    assert (await _wait_for_terminal(store, job_id))["result"] == "job wrote"


async def test_a_runner_cancelled_before_its_first_step_finishes_cancelled_and_passes_admission_on() -> None:
    store = JobStore()
    gate = _gate()
    release = asyncio.Event()
    await store.start(_hold(gate, release))
    await _settle()
    granted: list[str] = []
    pre_gate = asyncio.Event()

    async def change(name: str, wait: asyncio.Event | None = None) -> str:
        if wait is not None:
            await wait.wait()
        async with gate.write():
            granted.append(name)
            return name

    first = await store.start(change("first", pre_gate))
    second = await store.start(change("second"), after=first)
    third = await store.start(change("third"), after=second)
    # Cancel "second" before its runner has taken a single step.
    store._runs[second].task.cancel()
    await _settle()

    assert (await store.status(second))["status"] == "cancelled"
    assert (await store.status(third))["status"] == "queued"
    assert (await store.status(third))["position"] is None
    pre_gate.set()
    release.set()
    assert (await _wait_for_terminal_slowly(store, third))["result"] == "third"
    assert granted == ["first", "third"]
    await _settle()
    assert store._runs == {} and store._tasks == set()


# ---------------------------------------------------------------------------
# Randomised job chains (fixed seeds)
# ---------------------------------------------------------------------------


async def _random_job_run(seed: int) -> None:
    rng = random.Random(seed)
    store = JobStore(retention_seconds=10_000, max_completed_jobs=rng.choice([0, 3, 1000]))
    gate = OperationGate(GateSettings(read_cap=rng.randint(1, 3)), name="stress")
    gate_order: list[int] = []
    ran: set[int] = set()
    hang = asyncio.Event()

    def make(index: int, kind: str):
        async def operation():
            for _ in range(rng.randint(0, 3)):
                await asyncio.sleep(0)
            if kind == "raise_early":
                raise ValueError("before the gate")
            if kind == "no_gate":
                if rng.random() < 0.5:
                    signal_admitted()
                ran.add(index)
                return index
            if kind == "read":
                async with gate.read():
                    gate_order.append(index)
                    ran.add(index)
                    for _ in range(rng.randint(0, 4)):
                        await asyncio.sleep(0)
                return index
            if kind == "hang_pre_gate":
                await hang.wait()
                return index
            async with gate.write(label=str(index)):
                gate_order.append(index)
                ran.add(index)
                for _ in range(rng.randint(0, 6)):
                    await asyncio.sleep(0)
                if rng.random() < 0.2:
                    raise RuntimeError("body")
            return index

        return operation

    ids: list[str] = []
    kinds: dict[int, str] = {}
    chained: dict[int, bool] = {}
    cancelled: set[int] = set()
    previous = None
    for index in range(rng.randint(3, 15)):
        kinds[index] = rng.choices(["write", "read", "raise_early", "no_gate", "hang_pre_gate"], [6, 2, 1, 1, 0.5])[0]
        chained[index] = rng.random() < 0.9
        job_id = await store.start(make(index, kinds[index])(), after=previous if chained[index] else None)
        ids.append(job_id)
        previous = job_id
        for _ in range(rng.randint(0, 2)):
            await asyncio.sleep(0)
        if rng.random() < 0.3:
            victim = rng.randrange(len(ids))
            if (await store.cancel(ids[victim]))["cancelled"]:
                cancelled.add(victim)
        if rng.random() < 0.05:
            run = store._runs.get(ids[rng.randrange(len(ids))])
            if run is not None and run.task is not None:
                run.task.cancel()

    for step in range(400):
        await asyncio.sleep(0)
        if all(store._jobs.get(job_id, {"status": "done"})["status"] in TERMINAL_JOB_STATUSES for job_id in ids):
            break
        if step > 100:
            hang.set()
    else:
        raise AssertionError(f"seed {seed}: jobs never finished; kinds={kinds}")
    for _ in range(5):
        await asyncio.sleep(0)

    assert not store._runs, f"seed {seed}: runs leaked"
    assert not store._tasks, f"seed {seed}: tasks leaked"
    for index in cancelled:
        assert index not in ran, f"seed {seed}: job {index} reported cancelled but ran"
        job = store._jobs.get(ids[index])
        assert job is None or job["status"] == "cancelled", f"seed {seed}: job {index} left cancelled"
    # Along an unbroken chain, writes reach the gate in submission order,
    # whatever was cancelled in between.
    writes = [index for index in gate_order if kinds[index] == "write"]
    place = {index: order for order, index in enumerate(writes)}
    for earlier in writes:
        for later in writes:
            if earlier < later and all(chained[x] for x in range(earlier + 1, later + 1)):
                assert place[earlier] < place[later], f"seed {seed}: writes {writes}, chained {chained}"
    snapshot = gate.snapshot()
    assert not (snapshot["write_held"] or snapshot["queue_depth"] or snapshot["reads_in_use"]), f"seed {seed}"


async def test_random_job_chains_keep_submission_order_through_cancellations() -> None:
    logging.disable(logging.CRITICAL)
    try:
        for seed in range(300):
            await _random_job_run(seed)
    finally:
        logging.disable(logging.NOTSET)
