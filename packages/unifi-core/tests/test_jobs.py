"""Bounded-retention contracts for the shared background job store."""

from __future__ import annotations

import asyncio

import pytest
from unifi_core.jobs import JobStore


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
        if status["status"] != "running":
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
