"""One controller connection attempt at a time, with bounded waits for callers."""

from __future__ import annotations

import asyncio
import time

import pytest
from unifi_core.connect_attempt import ConnectAttempt


@pytest.mark.asyncio
async def test_callers_share_the_running_attempt():
    gate = asyncio.Event()
    runs = 0

    async def connect() -> bool:
        nonlocal runs
        runs += 1
        await gate.wait()
        return True

    attempt = ConnectAttempt(wait_seconds=5)
    first = attempt.start(connect, name="test-connect")
    second = attempt.start(connect, name="test-connect")
    assert first is second
    assert attempt.in_progress
    waiters = [asyncio.create_task(attempt.wait()) for _ in range(3)]
    await asyncio.sleep(0)
    gate.set()
    assert await asyncio.gather(*waiters) == [True, True, True]
    assert await attempt.join() is True
    assert runs == 1
    assert not attempt.in_progress


@pytest.mark.asyncio
async def test_the_wait_window_counts_from_the_start_of_the_attempt():
    gate = asyncio.Event()

    async def connect() -> bool:
        await gate.wait()
        return True

    attempt = ConnectAttempt(wait_seconds=0.2)
    attempt.start(connect, name="test-connect")
    started = time.monotonic()
    assert await attempt.wait() is None
    assert 0.15 < time.monotonic() - started < 1.0
    # A later caller does not wait again for an attempt already past its window.
    started = time.monotonic()
    assert await attempt.wait() is None
    assert time.monotonic() - started < 0.05
    assert attempt.in_progress, "the attempt carries on after its waiters give up"
    gate.set()
    assert await attempt.join() is True


@pytest.mark.asyncio
async def test_a_failing_attempt_reports_false_and_a_new_one_can_start():
    async def boom() -> bool:
        raise RuntimeError("controller text must not be logged")

    async def ok() -> bool:
        return True

    attempt = ConnectAttempt()
    attempt.start(boom, name="test-connect")
    assert await attempt.join() is False
    attempt.start(ok, name="test-connect")
    assert await attempt.join() is True


@pytest.mark.asyncio
async def test_cancel_stops_the_attempt_and_waiters_see_a_failure():
    async def forever() -> bool:
        await asyncio.Event().wait()
        return True

    attempt = ConnectAttempt(wait_seconds=5)
    attempt.start(forever, name="test-connect")
    waiter = asyncio.create_task(attempt.wait())
    joiner = asyncio.create_task(attempt.join())
    await asyncio.sleep(0)
    await attempt.cancel()
    assert await waiter is False
    assert await joiner is False
    assert not attempt.in_progress
