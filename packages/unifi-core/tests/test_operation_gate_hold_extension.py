"""A long, declared operation extends its write hold; the support bundle summarises the gate."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from unifi_core.operation_gate import (
    ControllerBusyError,
    GateSettings,
    OperationGate,
    extend_write_hold,
    held_write_remaining_seconds,
)
from unifi_core.support_bundle import (
    AttemptStatus,
    ConnectionSection,
    CountBucket,
    NetworkCapabilities,
    OperationGateSummary,
    SafeConnectionAttempt,
    operation_gate_summary,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self._sleepers: list[tuple[float, asyncio.Future[None]]] = []

    def now(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        entry = (self.value + seconds, future)
        self._sleepers.append(entry)
        try:
            await future
        finally:
            self._sleepers.remove(entry)

    async def advance(self, seconds: float) -> None:
        self.value += seconds
        for deadline, future in list(self._sleepers):
            if deadline <= self.value and not future.done():
                future.set_result(None)
        for _ in range(30):
            await asyncio.sleep(0)


async def _settle() -> None:
    for _ in range(30):
        await asyncio.sleep(0)


def test_extending_outside_a_held_write_changes_nothing() -> None:
    assert extend_write_hold(60) is False
    with pytest.raises(ValueError):
        extend_write_hold(0)


async def test_an_extended_hold_keeps_waiters_waiting_until_its_own_budget_runs_out(caplog) -> None:
    clock = FakeClock()
    gate = OperationGate(GateSettings(hold_budget_seconds=10), name="network", clock=clock)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def long_restore() -> None:
        async with gate.write(label="restore"):
            await clock.advance(5)
            assert extend_write_hold(30) is True
            # Never shortens: a smaller extension leaves the budget alone.
            assert extend_write_hold(1) is True
            assert held_write_remaining_seconds() == pytest.approx(30)
            entered.set()
            await release.wait()

    holder = asyncio.create_task(long_restore())
    await entered.wait()

    async def queued() -> str:
        async with gate.write(label="queued"):
            return "ran"

    waiter = asyncio.create_task(queued())
    await _settle()
    await clock.advance(20)  # 25s into the hold: past the gate's 10s, within the extension
    assert not waiter.done()
    assert gate.snapshot()["holder_over_budget"] is False

    await clock.advance(11.5)  # past 5 + 30 + the release grace
    with pytest.raises(ControllerBusyError, match="past its 35s budget"):
        await waiter
    release.set()
    await holder


async def test_an_extended_hold_released_within_its_budget_is_not_logged_over_budget(caplog) -> None:
    clock = FakeClock()
    gate = OperationGate(GateSettings(hold_budget_seconds=10), name="network", clock=clock)
    async with gate.write(label="restore"):
        extend_write_hold(60)
        await clock.advance(40)
    assert gate.snapshot()["counters"]["holds_over_budget"] == 0
    assert "over its" not in caplog.text


async def test_restore_has_its_own_limit_and_extends_the_held_write() -> None:
    from unifi_core.network.managers.system_manager import RESTORE_TIMEOUT_SECONDS, SystemManager

    seen: dict = {}
    response = MagicMock()
    response.status = 200
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)

    def post(url, *, data, timeout):
        seen["timeout"] = timeout
        seen["remaining"] = held_write_remaining_seconds()
        return response

    connection = MagicMock()
    connection.ensure_connected = AsyncMock(return_value=True)
    connection.controller.session.post = post
    connection.url_base = "https://controller.example"
    connection.site = "default"
    manager = SystemManager(connection)

    gate = OperationGate(GateSettings(hold_budget_seconds=120), name="network")
    async with gate.write(label="restore"):
        assert await manager.restore_backup(b"backup") is True

    assert RESTORE_TIMEOUT_SECONDS > 120
    assert seen["timeout"] == aiohttp.ClientTimeout(total=RESTORE_TIMEOUT_SECONDS)
    # The restore's own limit fits inside the extended hold.
    assert seen["remaining"] > RESTORE_TIMEOUT_SECONDS


async def test_the_support_summary_holds_only_flags_and_bucketed_counts() -> None:
    gate = OperationGate(GateSettings(read_cap=4), name="network (controller-identity)")
    for _ in range(3):
        async with gate.write(label="unifi_update_secret_named_thing"):
            pass
    async with gate.read():
        summary = operation_gate_summary(gate.snapshot())

    assert summary == OperationGateSummary(
        write_held=False,
        holder_over_budget=False,
        queue_depth=CountBucket.ZERO,
        reads_in_use=1,
        read_cap=4,
        hold_budget_seconds=120,
        writes_completed=CountBucket.TWO_TO_FIVE,
        writes_refused_busy=CountBucket.ZERO,
        writes_withdrawn=CountBucket.ZERO,
        holds_over_budget=CountBucket.ZERO,
        reads_refused_busy=CountBucket.ZERO,
    )
    dumped = json.dumps(summary.model_dump(mode="json"))
    assert "controller-identity" not in dumped and "secret_named" not in dumped

    section = ConnectionSection(
        initialized=True,
        connected=True,
        tls_verification_enabled=True,
        last_attempt=SafeConnectionAttempt(status=AttemptStatus.SUCCEEDED),
        capabilities=NetworkCapabilities(
            session_available=True,
            integration_api_key_configured=False,
            controller_type="direct",
            reconnect_circuit="closed",
        ),
        operation_gate=summary,
    )
    assert section.operation_gate == summary
    with pytest.raises(ValueError):
        OperationGateSummary.model_validate({**summary.model_dump(), "holder_label": "unifi_update_wlan"})


def test_a_malformed_snapshot_is_clamped_not_trusted() -> None:
    summary = operation_gate_summary({"write_held": "yes", "reads_in_use": 10_000, "read_cap": 0, "counters": None})
    assert summary.write_held is False
    assert summary.reads_in_use == 256
    assert summary.read_cap == 1
    assert summary.writes_completed is CountBucket.ZERO
