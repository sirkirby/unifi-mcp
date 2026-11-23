"""Contracts for the controller operation gate: FIFO writes, capped reads, progress timeouts."""

from __future__ import annotations

import asyncio
import contextvars
import logging
import random

import pytest
from unifi_core.operation_gate import (
    ControllerBusyError,
    GateKey,
    GateReentryError,
    GateRegistry,
    GateSettings,
    OperationGate,
    WriteRequestTimeout,
    WriteTicketCancelled,
    create_ungated_task,
    gate_registry,
    held_write_remaining_seconds,
    observing_operations,
    reset_gate_registry_for_tests,
    signal_admitted,
    write_request_bound,
)


class FakeClock:
    """A gate clock that only moves when the test advances it."""

    def __init__(self) -> None:
        self.value = 1_000.0
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

    def move(self, seconds: float) -> None:
        """Advance time and wake due sleepers, without yielding to them."""
        self.value += seconds
        for deadline, future in list(self._sleepers):
            if deadline <= self.value and not future.done():
                future.set_result(None)

    async def advance(self, seconds: float) -> None:
        self.move(seconds)
        await settle()


async def settle(rounds: int = 30) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


def make_gate(**settings) -> tuple[OperationGate, FakeClock]:
    clock = FakeClock()
    return OperationGate(GateSettings(**settings), name="network", clock=clock), clock


class Holder:
    """Hold a gate's write turn in a background task until released."""

    def __init__(self, gate: OperationGate, label: str = "holder") -> None:
        self.release = asyncio.Event()
        self.entered = asyncio.Event()
        self.gate = gate
        self.label = label
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        async with self.gate.write(label=self.label):
            self.entered.set()
            await self.release.wait()

    async def finish(self) -> None:
        self.release.set()
        await self.task


# ---------------------------------------------------------------------------
# Concurrency correctness
# ---------------------------------------------------------------------------


async def test_concurrent_writes_never_overlap_and_run_in_request_order() -> None:
    gate, _clock = make_gate()
    active = 0
    order: list[int] = []

    async def write(index: int) -> None:
        nonlocal active
        async with gate.write(label=f"w{index}"):
            active += 1
            assert active == 1
            order.append(index)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            active -= 1

    await asyncio.gather(*(write(index) for index in range(25)))

    assert order == list(range(25))
    assert gate.snapshot()["counters"]["writes_granted"] == 25
    assert not gate.write_held


async def test_reads_run_concurrently_up_to_the_cap() -> None:
    gate, _clock = make_gate(read_cap=3)
    release = asyncio.Event()
    inside = 0
    peak = 0

    async def read() -> None:
        nonlocal inside, peak
        async with gate.read():
            inside += 1
            peak = max(peak, inside)
            await release.wait()
            inside -= 1

    tasks = [asyncio.create_task(read()) for _ in range(5)]
    await settle()
    snapshot = gate.snapshot()
    assert inside == 3
    assert snapshot["reads_in_use"] == 3
    assert snapshot["reads_waiting"] == 2

    release.set()
    await asyncio.gather(*tasks)
    assert peak == 3
    assert gate.snapshot()["reads_in_use"] == 0


async def test_reads_never_wait_behind_writes() -> None:
    gate, _clock = make_gate()
    holder = Holder(gate)
    await holder.entered.wait()
    queued = asyncio.create_task(holder_write(gate))
    await settle()
    assert gate.queue_depth == 1

    async def read() -> str:
        async with gate.read():
            return "read"

    assert await asyncio.wait_for(read(), timeout=1) == "read"
    await holder.finish()
    await queued


async def holder_write(gate: OperationGate) -> None:
    async with gate.write(label="queued"):
        pass


async def test_a_writes_own_read_back_takes_no_read_slot() -> None:
    gate, _clock = make_gate(read_cap=1)
    outside_release = asyncio.Event()

    async def outside_read() -> None:
        async with gate.read():
            await outside_release.wait()

    reader = asyncio.create_task(outside_read())
    await settle()
    assert gate.snapshot()["reads_in_use"] == 1

    async def write_with_read_back() -> str:
        async with gate.write():
            async with gate.read():
                # Tasks the write starts share its hold too.
                async def child() -> str:
                    async with gate.read():
                        return "child"

                child_result = await asyncio.gather(child(), child())
            return f"read back ({len(child_result)} children)"

    assert await asyncio.wait_for(write_with_read_back(), timeout=1) == "read back (2 children)"
    assert gate.snapshot()["reads_in_use"] == 1
    assert gate.snapshot()["counters"]["reads_nested"] == 3
    outside_release.set()
    await reader


async def test_nested_write_on_the_same_gate_raises_instead_of_deadlocking() -> None:
    gate, _clock = make_gate()

    async with gate.write():
        with pytest.raises(GateReentryError, match="already held"):
            async with gate.write():
                pass

        async def child_write() -> None:
            async with gate.write():
                pass

        with pytest.raises(GateReentryError):
            await asyncio.gather(child_write())

    assert not gate.write_held


async def test_writes_on_other_gates_are_independent_inside_a_held_write() -> None:
    network, _ = make_gate()
    protect, _ = make_gate()

    async with network.write():
        async with protect.write():
            assert network.holds_write() and protect.holds_write()


async def test_ungated_task_queues_on_its_own_and_stale_marks_are_ignored() -> None:
    gate, _clock = make_gate()
    order: list[str] = []

    async def background() -> None:
        async with gate.write(label="background"):
            order.append("background")

    async def inherited() -> None:
        # Started normally inside the write: shares the hold while it lasts,
        # and queues like anyone else once the hold has ended.
        await asyncio.sleep(0)
        async with gate.write(label="inherited"):
            order.append("inherited")

    async with gate.write(label="outer"):
        ungated = create_ungated_task(background())
        await settle()
        assert gate.queue_depth == 1
        assert gate.holds_write()
        order.append("outer")
        late = asyncio.create_task(inherited())

    await asyncio.gather(ungated, late)
    assert order == ["outer", "background", "inherited"]


# ---------------------------------------------------------------------------
# Timeouts
# ---------------------------------------------------------------------------


async def test_waiters_fail_busy_only_once_the_holder_is_over_budget(caplog) -> None:
    gate, clock = make_gate(hold_budget_seconds=10)
    holder = Holder(gate)
    await holder.entered.wait()
    waiter = asyncio.create_task(holder_write(gate))
    await settle()

    await clock.advance(9)
    assert not waiter.done()
    await clock.advance(1.5)  # past the budget, within the release grace
    assert not waiter.done()

    with caplog.at_level(logging.WARNING, logger="unifi_core.operation_gate"):
        await clock.advance(1)
    with pytest.raises(ControllerBusyError) as busy:
        await waiter
    assert busy.value.reason == "holder_over_budget"
    assert busy.value.retry_after >= 1
    assert gate.queue_depth == 0
    assert gate.write_held
    assert any("over its" in record.getMessage() for record in caplog.records)

    with caplog.at_level(logging.WARNING, logger="unifi_core.operation_gate"):
        await holder.finish()
    assert any("held the write turn" in record.getMessage() for record in caplog.records)
    assert gate.snapshot()["counters"]["holds_over_budget"] == 1
    # The gate is usable again straight away.
    await asyncio.wait_for(holder_write(gate), timeout=1)


async def test_a_long_queue_that_keeps_moving_never_fails() -> None:
    gate, clock = make_gate(hold_budget_seconds=10)
    finished: list[int] = []

    async def write(index: int) -> None:
        async with gate.write():
            await clock.sleep(8)
            finished.append(index)

    tasks = [asyncio.create_task(write(index)) for index in range(6)]
    await settle()
    for _ in range(60):
        await clock.advance(1)
    await asyncio.gather(*tasks)
    assert finished == list(range(6))
    assert gate.snapshot()["counters"]["writes_busy"] == 0


async def test_wait_budget_is_honoured_and_none_waits_while_progress_continues() -> None:
    gate, clock = make_gate(hold_budget_seconds=100)
    holder = Holder(gate)
    await holder.entered.wait()

    async def budgeted() -> None:
        async with gate.write(wait_budget=3, label="direct"):
            pass

    direct = asyncio.create_task(budgeted())
    unlimited = asyncio.create_task(holder_write(gate))
    await settle()
    assert gate.queue_depth == 2

    await clock.advance(2.5)
    assert not direct.done()
    await clock.advance(0.5)
    with pytest.raises(ControllerBusyError) as busy:
        await direct
    assert busy.value.reason == "wait_budget"
    assert busy.value.position == 1
    assert "not sent" in str(busy.value)

    await clock.advance(90)
    assert not unlimited.done()
    await holder.finish()
    await unlimited


async def test_read_wait_budget_fails_busy_when_slots_stay_full() -> None:
    gate, clock = make_gate(read_cap=1)
    release = asyncio.Event()

    async def hold_read() -> None:
        async with gate.read():
            await release.wait()

    reader = asyncio.create_task(hold_read())
    await settle()

    async def budgeted_read() -> None:
        async with gate.read(wait_budget=2):
            pass

    waiting = asyncio.create_task(budgeted_read())
    await settle()
    await clock.advance(2)
    with pytest.raises(ControllerBusyError):
        await waiting
    assert gate.snapshot()["reads_waiting"] == 0
    release.set()
    await reader
    assert gate.snapshot()["reads_in_use"] == 0


@pytest.mark.parametrize("bad", [0, -1, float("inf"), float("nan"), True, "5"])
def test_wait_budget_must_be_a_positive_finite_number(bad) -> None:
    gate, _clock = make_gate()
    with pytest.raises(ValueError):
        asyncio.run(_enter(gate.write(wait_budget=bad)))


async def _enter(context) -> None:
    async with context:
        pass


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


async def test_a_cancelled_waiter_leaves_the_queue_and_positions_update() -> None:
    gate, _clock = make_gate()
    holder = Holder(gate)
    await holder.entered.wait()
    tickets = {}

    async def write(name: str) -> None:
        async with gate.write(label=name) as ticket:
            tickets[name] = ticket

    class Recorder:
        def __init__(self, name: str) -> None:
            self.name = name

        def admitted(self) -> None:
            pass

        def queued(self, ticket) -> None:
            tickets[self.name] = ticket

        def granted(self, ticket) -> None:
            pass

    async def observed(name: str) -> None:
        async with observing_operations(Recorder(name)):
            await write(name)

    tasks = {name: asyncio.create_task(observed(name)) for name in ("a", "b", "c")}
    await settle()
    assert [tickets[name].position for name in ("a", "b", "c")] == [1, 2, 3]

    tasks["b"].cancel()
    await settle()
    assert tasks["b"].cancelled()
    assert gate.queue_depth == 2
    assert [tickets[name].position for name in ("a", "c")] == [1, 2]

    await holder.finish()
    await asyncio.gather(tasks["a"], tasks["c"])
    assert gate.snapshot()["counters"]["writes_withdrawn"] == 1


async def test_a_waiter_cancelled_after_being_granted_passes_the_turn_on() -> None:
    gate, _clock = make_gate()
    holder = Holder(gate)
    await holder.entered.wait()
    ran: list[str] = []

    async def write(name: str) -> None:
        async with gate.write(label=name):
            ran.append(name)

    second = asyncio.create_task(write("second"))
    third = asyncio.create_task(write("third"))
    await settle()

    # Release the holder and cancel the next waiter in the same step: its
    # turn is granted, but it never resumes to use it.
    holder.release.set()
    await asyncio.sleep(0)  # the holder resumes, releases, and hands over
    assert gate.write_held
    second.cancel()
    await asyncio.gather(holder.task, third)
    assert second.cancelled()
    assert ran == ["third"]
    assert not gate.write_held


async def test_an_exception_in_the_holder_releases_the_gate() -> None:
    gate, _clock = make_gate()

    async def failing() -> None:
        async with gate.write():
            raise RuntimeError("controller said no")

    waiter_started = asyncio.Event()

    async def waiter() -> str:
        waiter_started.set()
        async with gate.write():
            return "next"

    first = asyncio.create_task(failing())
    second = asyncio.create_task(waiter())
    with pytest.raises(RuntimeError):
        await first
    assert await second == "next"
    assert not gate.write_held
    assert gate.snapshot()["counters"]["writes_completed"] == 2


async def test_an_external_handle_withdraws_a_queued_ticket() -> None:
    gate, _clock = make_gate()
    holder = Holder(gate)
    await holder.entered.wait()
    captured = {}

    class Capture:
        def admitted(self) -> None:
            pass

        def queued(self, ticket) -> None:
            captured["ticket"] = ticket

        def granted(self, ticket) -> None:
            pass

    async def queued_write() -> None:
        async with observing_operations(Capture()):
            async with gate.write():
                raise AssertionError("a withdrawn ticket must never run")

    task = asyncio.create_task(queued_write())
    await settle()
    assert captured["ticket"].cancel() is True
    with pytest.raises(WriteTicketCancelled):
        await task
    assert gate.queue_depth == 0
    assert captured["ticket"].cancel() is False
    await holder.finish()


# ---------------------------------------------------------------------------
# Admission observer
# ---------------------------------------------------------------------------


class EventLog:
    def __init__(self) -> None:
        self.events: list[str] = []

    def admitted(self) -> None:
        self.events.append("admitted")

    def queued(self, ticket) -> None:
        self.events.append(f"queued:{ticket.position}")

    def granted(self, ticket) -> None:
        self.events.append("granted")


async def test_observer_hears_queue_admission_and_grant_in_order() -> None:
    gate, _clock = make_gate()
    holder = Holder(gate)
    await holder.entered.wait()
    log = EventLog()

    async def observed() -> None:
        async with observing_operations(log):
            async with gate.write():
                log.events.append("body")

    task = asyncio.create_task(observed())
    await settle()
    assert log.events == ["queued:1", "admitted"]
    await holder.finish()
    await task
    assert log.events == ["queued:1", "admitted", "granted", "body"]


async def test_an_uncontended_write_is_granted_without_waiting() -> None:
    gate, _clock = make_gate()
    log = EventLog()
    async with observing_operations(log):
        async with gate.write():
            pass
    assert log.events == ["queued:0", "admitted", "granted"]


async def test_reads_and_explicit_signals_admit_without_queueing() -> None:
    gate, _clock = make_gate()
    log = EventLog()
    async with observing_operations(log):
        async with gate.read():
            pass
        signal_admitted()
    assert log.events == ["admitted", "admitted"]
    # With no observer installed the signal is a no-op.
    signal_admitted()


async def test_a_failing_observer_never_breaks_the_operation(caplog) -> None:
    gate, _clock = make_gate()

    class Broken:
        def admitted(self) -> None:
            raise RuntimeError("observer bug")

        def queued(self, ticket) -> None:
            raise RuntimeError("observer bug")

        def granted(self, ticket) -> None:
            raise RuntimeError("observer bug")

    async with observing_operations(Broken()):
        async with gate.write():
            pass
    assert "observer failed" in caplog.text


# ---------------------------------------------------------------------------
# Write request bound
# ---------------------------------------------------------------------------


async def test_write_request_bound_is_a_no_op_outside_a_held_write() -> None:
    assert held_write_remaining_seconds() is None
    async with write_request_bound():
        await asyncio.sleep(0.002)


async def test_write_request_bound_times_out_at_the_remaining_hold_budget() -> None:
    gate, clock = make_gate(hold_budget_seconds=10)
    async with gate.write() as ticket:
        await clock.advance(9.995)
        remaining = held_write_remaining_seconds()
        assert remaining is not None and remaining == pytest.approx(0.005)
        with pytest.raises(WriteRequestTimeout, match="may or may not have been applied") as timeout:
            async with write_request_bound():
                await asyncio.sleep(1)
        assert isinstance(timeout.value, TimeoutError)
        assert timeout.value.request_sent is True
        assert ticket.cut_off is timeout.value

        await clock.advance(1)
        # This request is refused unsent, but the one before it went out.
        with pytest.raises(WriteRequestTimeout, match="may or may not have been applied") as refused:
            async with write_request_bound():
                raise AssertionError("no request may be sent once the budget is spent")
        assert refused.value.request_sent is True
        assert ticket.cut_off is timeout.value


async def test_a_refusal_before_any_request_of_the_write_says_nothing_was_sent() -> None:
    gate, clock = make_gate(hold_budget_seconds=10)
    async with gate.write() as ticket:
        assert ticket.request_sent is False and ticket.cut_off is None
        await clock.advance(11)
        with pytest.raises(WriteRequestTimeout, match="not sent") as refused:
            async with write_request_bound():
                raise AssertionError("no request may be sent once the budget is spent")
    assert refused.value.request_sent is False
    assert ticket.request_sent is False
    assert ticket.cut_off is refused.value


async def test_a_request_inside_the_hold_marks_the_ticket_sent_and_leaves_no_cut_off() -> None:
    gate, _clock = make_gate(hold_budget_seconds=10)
    async with gate.write() as ticket:
        async with write_request_bound():
            pass
    assert ticket.request_sent is True
    assert ticket.cut_off is None


async def test_write_request_bound_leaves_other_timeouts_alone() -> None:
    gate, _clock = make_gate(hold_budget_seconds=10)
    async with gate.write():
        with pytest.raises(TimeoutError) as raised:
            async with write_request_bound():
                raise TimeoutError("aiohttp's own")
        assert not isinstance(raised.value, WriteRequestTimeout)


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------


async def test_snapshot_reports_queue_holder_reads_and_per_label_hold_times(caplog) -> None:
    gate, clock = make_gate(hold_budget_seconds=30, read_cap=4)
    holder = Holder(gate, label="unifi_update_network")
    await holder.entered.wait()
    queued = asyncio.create_task(holder_write(gate))
    await settle()
    await clock.advance(7)

    snapshot = gate.snapshot()
    assert snapshot["write_held"] is True
    assert snapshot["holder_label"] == "unifi_update_network"
    assert snapshot["holder_age_seconds"] == pytest.approx(7)
    assert snapshot["holder_over_budget"] is False
    assert snapshot["queue_depth"] == 1
    assert snapshot["oldest_wait_seconds"] == pytest.approx(7)
    assert snapshot["read_cap"] == 4
    assert snapshot["hold_budget_seconds"] == 30

    with caplog.at_level(logging.DEBUG, logger="unifi_core.operation_gate"):
        await holder.finish()
        await queued
    assert "granted queued after 7.000s" in caplog.text
    assert "released by unifi_update_network after 7.000s" in caplog.text

    after = gate.snapshot()
    assert after["hold_times"]["unifi_update_network"] == {"count": 1, "total_seconds": 7.0, "max_seconds": 7.0}
    assert after["counters"]["writes_requested"] == 2
    assert after["counters"]["writes_completed"] == 2
    assert after["holder_age_seconds"] is None


# ---------------------------------------------------------------------------
# Settings and registry
# ---------------------------------------------------------------------------


def test_settings_defaults_and_validation() -> None:
    settings = GateSettings()
    assert (settings.hold_budget_seconds, settings.direct_call_wait_seconds, settings.read_cap) == (120.0, 25.0, 8)
    for bad in (
        {"hold_budget_seconds": 0},
        {"hold_budget_seconds": float("inf")},
        {"hold_budget_seconds": 10_000},
        {"direct_call_wait_seconds": -1},
        {"read_cap": 0},
        {"read_cap": 1.5},
        {"read_cap": True},
        {"read_cap": 10_000},
    ):
        with pytest.raises(ValueError):
            GateSettings(**bad)
    with pytest.raises(AttributeError):
        settings.read_cap = 2  # type: ignore[misc]


def test_host_keys_compare_like_the_credential_host_rule() -> None:
    assert GateKey.for_host("Console.Local", None, "Network") == GateKey.for_host("console.local", 443, "network")
    assert GateKey.for_host("console", "0443", "network") == GateKey.for_host("console", "443", "network")
    assert GateKey.for_host("console", "", "network") == GateKey.for_host("console", 443, "network")
    assert GateKey.for_host("console", 8443, "network") != GateKey.for_host("console", 443, "network")
    assert GateKey.for_host("console", 443, "network") != GateKey.for_host("console", 443, "protect")
    # Surrounding whitespace never splits one console into two gates.
    assert GateKey.for_host(" console ", " 443 ", "network") == GateKey.for_host("console", 443, "network")
    # Otherwise the host as written: no other normalisation, and non-ASCII case is kept.
    assert GateKey.for_host("console/", 443, "network") != GateKey.for_host("console", 443, "network")
    assert GateKey.for_host("CÖNSOLE", 443, "network").identity == "CÖNSOLE:443"
    for bad_host in ("", "  "):
        with pytest.raises(ValueError):
            GateKey.for_host(bad_host, 443, "network")
    with pytest.raises(ValueError):
        GateKey.for_host("console", 443, " ")


def test_registry_returns_one_gate_per_controller_application() -> None:
    registry = GateRegistry()
    key = registry.for_host("Console", None, "network")
    gate = registry.get(key, GateSettings(read_cap=2))
    assert registry.get(GateRegistry.for_host("console", "443", "NETWORK")) is gate
    # Settings passed after creation do not replace the gate's.
    assert registry.get(key, GateSettings(read_cap=5)).settings.read_cap == 2
    assert registry.get(registry.for_host("console", 443, "protect")) is not gate

    controller = registry.get(registry.for_controller("ctrl-1", "network"))
    assert registry.get(GateKey.for_controller(" ctrl-1 ", "Network")) is controller
    assert controller is not registry.get(registry.for_controller("ctrl-2", "network"))
    # Logs and errors name the product, never the host.
    assert gate.name == "network"
    assert controller.name == "network (ctrl-1)"

    assert len(registry.gates()) == 4
    registry.reset()
    assert registry.get(key) is not gate


def test_default_registry_and_reset_helper() -> None:
    key = GateKey.for_host("console", 443, "network")
    gate = gate_registry().get(key)
    assert gate_registry().get(key) is gate
    reset_gate_registry_for_tests()
    assert gate_registry().get(key) is not gate
    reset_gate_registry_for_tests()


# ---------------------------------------------------------------------------
# Regressions: exits, hand-overs, coinciding deadlines, observers
# ---------------------------------------------------------------------------


async def test_a_write_exited_in_another_context_is_still_released() -> None:
    gate, _clock = make_gate()
    entered = gate.write()
    await entered.__aenter__()
    assert gate.write_held

    async def exit_elsewhere() -> None:
        await entered.__aexit__(None, None, None)

    # A framework may run a dependency's teardown in another context, where
    # the ownership mark cannot be reset. The turn must be released anyway.
    await asyncio.get_running_loop().create_task(exit_elsewhere(), context=contextvars.Context())
    assert not gate.write_held
    await asyncio.wait_for(holder_write(gate), timeout=1)


async def test_a_read_exited_in_another_context_still_frees_its_slot() -> None:
    gate, _clock = make_gate(read_cap=1)
    entered = gate.read()
    await entered.__aenter__()
    assert gate.snapshot()["reads_in_use"] == 1

    async def exit_elsewhere() -> None:
        await entered.__aexit__(None, None, None)

    await asyncio.get_running_loop().create_task(exit_elsewhere(), context=contextvars.Context())
    assert gate.snapshot()["reads_in_use"] == 0


async def test_a_read_slot_handed_to_a_waiter_that_is_then_cancelled_is_passed_on() -> None:
    gate, _clock = make_gate(read_cap=1)
    release = asyncio.Event()
    ran: list[str] = []

    async def read(name: str, wait: asyncio.Event | None = None) -> None:
        async with gate.read():
            ran.append(name)
            if wait is not None:
                await wait.wait()

    first = asyncio.create_task(read("first", release))
    await settle()
    second = asyncio.create_task(read("second"))
    third = asyncio.create_task(read("third"))
    await settle()
    assert gate.snapshot()["reads_waiting"] == 2

    release.set()
    await asyncio.sleep(0)  # "first" leaves and hands its slot to "second"
    assert gate.snapshot()["reads_waiting"] == 1
    second.cancel()
    await asyncio.gather(first, third)
    assert second.cancelled()
    assert ran == ["first", "third"]
    assert gate.snapshot()["reads_in_use"] == 0
    assert gate.snapshot()["reads_waiting"] == 0


async def test_a_wait_budget_and_an_over_budget_holder_at_the_same_deadline_fail_once() -> None:
    gate, clock = make_gate(hold_budget_seconds=10)
    holder = Holder(gate)
    await holder.entered.wait()

    # The holder falls due at its budget plus the release grace: the same instant.
    async def budgeted() -> None:
        async with gate.write(wait_budget=10 + 1.0):
            pass

    waiter = asyncio.create_task(budgeted())
    await settle()
    await clock.advance(11)
    with pytest.raises(ControllerBusyError) as busy:
        await waiter
    assert busy.value.reason == "wait_budget"
    assert gate.queue_depth == 0
    assert gate.snapshot()["counters"]["writes_busy"] == 1
    assert gate.write_held
    await holder.finish()
    assert not gate.write_held


class _Boom(BaseException):
    pass


@pytest.mark.parametrize("failing", ["queued", "admitted", "granted"])
@pytest.mark.parametrize("contended", [True, False])
async def test_an_observer_raising_a_base_exception_never_leaks_the_gate(failing: str, contended: bool) -> None:
    gate, _clock = make_gate()
    holder = Holder(gate) if contended else None
    if holder is not None:
        await holder.entered.wait()

    class Raising:
        def admitted(self) -> None:
            if failing == "admitted":
                raise _Boom()

        def queued(self, ticket) -> None:
            if failing == "queued":
                raise _Boom()

        def granted(self, ticket) -> None:
            if failing == "granted":
                raise _Boom()

    async def observed() -> None:
        async with observing_operations(Raising()):
            async with gate.write():
                raise AssertionError("the body must not run")

    task = asyncio.create_task(observed())
    await settle()
    if holder is not None:
        assert gate.queue_depth == (1 if failing == "granted" else 0)
        await holder.finish()
    with pytest.raises(_Boom):
        await task
    assert not gate.write_held
    assert gate.queue_depth == 0


# ---------------------------------------------------------------------------
# Randomised schedules (fixed seeds)
# ---------------------------------------------------------------------------


class _Violation(AssertionError):
    pass


async def _yields(count: int) -> None:
    for _ in range(count):
        await asyncio.sleep(0)


async def _random_gate_run(seed: int) -> None:
    rng = random.Random(seed)
    clock = FakeClock()
    cap = rng.randint(1, 4)
    budget = rng.choice([5.0, 20.0, 1000.0])
    gate = OperationGate(GateSettings(hold_budget_seconds=budget, read_cap=cap), name="stress", clock=clock)
    state = {"writers": 0}
    request_order: list[int] = []
    grant_order: list[int] = []
    tickets: dict[int, object] = {}

    class Recorder:
        def __init__(self, index: int) -> None:
            self.index = index

        def admitted(self) -> None:
            pass

        def queued(self, ticket) -> None:
            tickets[self.index] = ticket
            request_order.append(self.index)

        def granted(self, ticket) -> None:
            pass

    async def body() -> None:
        if state["writers"] > 1:
            raise _Violation(f"seed {seed}: two writers at once")
        if rng.random() < 0.3:
            before = gate.snapshot()["reads_in_use"]
            async with gate.read():
                if gate.snapshot()["reads_in_use"] != before:
                    raise _Violation(f"seed {seed}: a nested read took a slot")
                await _yields(rng.randint(0, 2))
        if rng.random() < 0.2:
            with pytest.raises(GateReentryError):
                async with gate.write():
                    pass
        await _yields(rng.randint(0, 4))

    async def writer(index: int) -> None:
        wait_budget = rng.choice([None, None, 3.0, 50.0])
        try:
            async with observing_operations(Recorder(index)):
                async with gate.write(wait_budget=wait_budget, label=f"w{index}"):
                    grant_order.append(index)
                    state["writers"] += 1
                    try:
                        await body()
                    finally:
                        state["writers"] -= 1
                    if rng.random() < 0.15:
                        raise RuntimeError("body failure")
        except (RuntimeError, ControllerBusyError, WriteTicketCancelled):
            pass

    async def reader() -> None:
        try:
            async with gate.read(wait_budget=rng.choice([None, 2.0])):
                if gate.snapshot()["reads_in_use"] > cap:
                    raise _Violation(f"seed {seed}: read cap exceeded")
                if rng.random() < 0.3:
                    async with gate.read():
                        await _yields(rng.randint(0, 2))
                await _yields(rng.randint(0, 5))
        except ControllerBusyError:
            pass

    tasks: list[asyncio.Task] = []
    for index in range(rng.randint(5, 25)):
        tasks.append(asyncio.create_task(writer(index) if rng.random() < 0.6 else reader()))
        await _yields(rng.randint(0, 2))
        for _ in range(rng.randint(0, 2)):
            action = rng.random()
            if action < 0.15:
                rng.choice(tasks).cancel()
            elif action < 0.25 and tickets:
                rng.choice(list(tickets.values())).cancel()
            elif action < 0.4:
                clock.move(rng.choice([0.5, 2.0, 10.0]))
            await _yields(rng.randint(0, 3))

    for _ in range(2000):
        if all(task.done() for task in tasks):
            break
        clock.move(1.0)
        await _yields(3)
    else:
        raise _Violation(f"seed {seed}: operations stuck; {gate.snapshot()}")
    for task in tasks:
        if not task.cancelled() and task.exception() is not None:
            raise task.exception()
    snapshot = gate.snapshot()
    if snapshot["write_held"] or snapshot["queue_depth"] or snapshot["reads_in_use"] or snapshot["reads_waiting"]:
        raise _Violation(f"seed {seed}: gate not idle; {snapshot}")
    position = {index: order for order, index in enumerate(request_order)}
    granted_positions = [position[index] for index in grant_order]
    if granted_positions != sorted(granted_positions):
        raise _Violation(f"seed {seed}: grants {grant_order} out of request order {request_order}")


async def test_random_schedules_keep_writes_exclusive_ordered_and_the_gate_idle_after() -> None:
    logging.disable(logging.CRITICAL)
    try:
        for seed in range(300):
            await _random_gate_run(seed)
    finally:
        logging.disable(logging.NOTSET)
