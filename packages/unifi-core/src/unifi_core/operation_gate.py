"""One controller operation at a time for writes, a capped number at once for reads.

The controllers we wrap expose private APIs whose behaviour under concurrent
writes is unknown, and a write is often a read-modify-write that a second write
can silently undo. An :class:`OperationGate` guarantees how our own operations
reach one controller application:

- :meth:`OperationGate.write` is exclusive and strictly first-in-first-out.
  Each request takes a :class:`WriteTicket` that knows its place in the queue
  and can be withdrawn.
- :meth:`OperationGate.read` is shared, capped at ``GateSettings.read_cap``
  concurrent reads. Reads never wait behind writes.

The unit is a whole operation (a tool call, an API action), not a single HTTP
request. Gates are looked up in a :class:`GateRegistry` by controller identity
plus product, never by connection-manager instance, so a gate outlives the
managers that come and go beneath it.

**Ownership.** A context variable records the gates the current operation
holds, in the pattern of ``unifi_core.request_budget``. Inside a held write a
``read()`` on the same gate passes straight through (a write's own read-back
takes no read slot), and a second ``write()`` raises :class:`GateReentryError`
instead of deadlocking. Tasks started during the hold inherit it, so a write
that gathers its own reads is still one operation; the mark is honoured only
while the hold lasts. Start a task that must queue on its own with
:func:`create_ungated_task`.

**Timeouts measure lack of progress, not total wait.** A waiter fails with
:class:`ControllerBusyError` when the current holder has kept the gate past
its hold budget (``GateSettings.hold_budget_seconds``) or when the caller's own
optional ``wait_budget`` runs out. A waiter far back in a queue that keeps
moving never fails otherwise. Inside a held write, :func:`write_request_bound`
bounds each controller request by what is left of the hold budget. An
operation known to run long declares it in code with :func:`extend_write_hold`,
next to its own explicit time limit.

**Admission.** A job runner that must start operations in order installs a
:class:`GateObserver` with :func:`observing_operations`. The gate tells it
when the operation joins the gate (``admitted``: a write ticket is queued, or
a read starts), when a write ticket is queued, and when the write is granted.
An operation that never reaches a gate calls :func:`signal_admitted` itself;
the job runner also signals admission when a job ends.

**Lock order.** The gate is always outermost. Connect and login attempts run
in their own tasks and never enter it; per-resource, auth, connect and
collection-refresh locks sit inside it.

The guarantee is per server process.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import math
import time
from collections import deque
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from unifi_core.exceptions import UniFiConnectionError, UniFiError

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_HOLD_BUDGET_SECONDS = 120.0
DEFAULT_DIRECT_CALL_WAIT_SECONDS = 25.0
DEFAULT_READ_CAP = 8

# Sanity bounds for settings. The servers apply their own, documented bounds
# when they read the environment; these only refuse nonsense.
MAX_BUDGET_SECONDS = 3_600.0
MAX_READ_CAP = 256

# A holder's own write requests time out at its budget. Waiters give it this
# long beyond the budget to release before they call the controller busy, so a
# holder that is about to fail its request is not raced by its waiters.
HOLD_GRACE_SECONDS = 1.0

# The delay suggested to a caller refused as busy (an API's ``Retry-After``).
BUSY_RETRY_AFTER_SECONDS = 5

# Distinct labels kept in the per-label hold statistics; the rest are pooled.
_MAX_LABEL_STATS = 256
_OTHER_LABEL = "(other)"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ControllerBusyError(UniFiError):
    """The gate could not be entered in time; nothing was sent to the controller.

    ``reason`` is ``"holder_over_budget"`` when the operation holding the
    write gate has kept it past its hold budget, ``"wait_budget"`` when the
    caller's own wait budget ran out. ``retry_after`` is a suggested delay in
    whole seconds (an API maps it to ``Retry-After``).
    """

    def __init__(self, message: str, *, reason: str, retry_after: int, position: int | None = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.retry_after = retry_after
        self.position = position


class GateReentryError(RuntimeError):
    """A write was requested on a gate whose write the current operation already holds."""


class WriteTicketCancelled(UniFiError):
    """A queued write ticket was withdrawn by its external handle before it was granted."""


class WriteRequestTimeout(UniFiConnectionError, TimeoutError):
    """A controller request inside a held write ran past the write's hold budget.

    The request may already have reached the controller, so the change may or
    may not have been applied; read the resource back before retrying.
    """


# ---------------------------------------------------------------------------
# Settings, clock
# ---------------------------------------------------------------------------


def _check_seconds(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number of seconds")
    if not math.isfinite(value) or value <= 0 or value > MAX_BUDGET_SECONDS:
        raise ValueError(f"{name} must be greater than 0 and at most {MAX_BUDGET_SECONDS:.0f} seconds")


@dataclass(frozen=True)
class GateSettings:
    """Per-gate limits. Core never reads the environment for these; servers pass them in.

    ``direct_call_wait_seconds`` is not applied by the gate on its own: a
    caller that answers a direct tool call passes it as ``wait_budget``. Batch
    jobs pass no wait budget.
    """

    hold_budget_seconds: float = DEFAULT_HOLD_BUDGET_SECONDS
    direct_call_wait_seconds: float = DEFAULT_DIRECT_CALL_WAIT_SECONDS
    read_cap: int = DEFAULT_READ_CAP

    def __post_init__(self) -> None:
        _check_seconds("hold_budget_seconds", self.hold_budget_seconds)
        _check_seconds("direct_call_wait_seconds", self.direct_call_wait_seconds)
        if isinstance(self.read_cap, bool) or not isinstance(self.read_cap, int):
            raise ValueError("read_cap must be an integer")
        if not 1 <= self.read_cap <= MAX_READ_CAP:
            raise ValueError(f"read_cap must be between 1 and {MAX_READ_CAP}")


class GateClock(Protocol):
    """Time source for a gate: ``now`` in seconds and a ``sleep`` that honours it."""

    def now(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...


class MonotonicClock:
    """The default clock: ``time.monotonic`` and ``asyncio.sleep``."""

    def now(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


# ---------------------------------------------------------------------------
# Ownership and admission context
# ---------------------------------------------------------------------------


class _Hold:
    """One gate held by the current operation: a granted write ticket or a read slot."""

    gate: OperationGate

    @property
    def active(self) -> bool:  # pragma: no cover - overridden
        raise NotImplementedError


class _ReadHold(_Hold):
    def __init__(self, gate: OperationGate) -> None:
        self.gate = gate
        self.released = False

    @property
    def active(self) -> bool:
        return not self.released


_holds: ContextVar[tuple[_Hold, ...]] = ContextVar("unifi_gate_holds", default=())


class GateObserver(Protocol):
    """Told how an operation moves through a gate; installed by a job runner.

    Callbacks run synchronously in the operation's own task and must not raise.

    - ``admitted()``: the operation has joined a gate (its write ticket is in
      the queue, or its read has started). Called at most once per gate entry;
      a runner treats the first call as the job's admission.
    - ``queued(ticket)``: a write ticket joined the queue (it may already be
      granted, when the gate was free).
    - ``granted(ticket)``: the write ticket was granted and the operation is
      about to run. A ticket cancelled after being granted, before it resumed,
      is passed on without this call: its operation never ran.
    """

    def admitted(self) -> None: ...

    def queued(self, ticket: WriteTicket) -> None: ...

    def granted(self, ticket: WriteTicket) -> None: ...


_observer: ContextVar[GateObserver | None] = ContextVar("unifi_gate_observer", default=None)


@asynccontextmanager
async def observing_operations(observer: GateObserver) -> AsyncIterator[None]:
    """Report every gate entry made inside the block (and its tasks) to ``observer``."""
    token = _observer.set(observer)
    try:
        yield
    finally:
        _observer.reset(token)


def _notify(method: str, *args: Any) -> None:
    observer = _observer.get()
    if observer is None:
        return
    try:
        getattr(observer, method)(*args)
    except Exception:
        # An observer is bookkeeping; it must never break the operation.
        logger.exception("Operation gate observer failed in %s", method)


def signal_admitted() -> None:
    """Tell the installed observer the operation is admitted without queueing at a gate.

    For an operation that reaches no gate (a server without one, a meta tool)
    or that knows it will not write. A no-op with no observer installed, and
    harmless when the operation was already admitted.
    """
    _notify("admitted")


def ungated_context() -> contextvars.Context:
    """A copy of the current context with no gate held and no observer installed."""
    context = contextvars.copy_context()
    context.run(_holds.set, ())
    context.run(_observer.set, None)
    return context


def create_ungated_task(coro: Coroutine[Any, Any, T], *, name: str | None = None) -> asyncio.Task[T]:
    """Start a task that does not share the current operation's gates or admission.

    Use it for work that outlives the operation, or that must queue for the
    gate on its own; a task started normally inside a held write shares the
    hold while it lasts.
    """
    return asyncio.get_running_loop().create_task(coro, name=name, context=ungated_context())


def _reset_holds(token: contextvars.Token[tuple[_Hold, ...]]) -> None:
    """Drop the hold mark set on entry; tolerate an exit made in another context.

    A context manager entered in one context and exited in another (a
    framework running a dependency's setup and teardown apart) cannot reset
    the mark. The gate is released regardless, and a mark left behind is
    inert: ownership is honoured only while the hold lasts.
    """
    try:
        _holds.reset(token)
    except ValueError:
        logger.debug("Operation gate exited in a different context than it was entered")


def _held_write(gate: OperationGate) -> WriteTicket | None:
    for hold in _holds.get():
        if isinstance(hold, WriteTicket) and hold.gate is gate and hold.active:
            return hold
    return None


def _holds_read(gate: OperationGate) -> bool:
    return any(isinstance(hold, _ReadHold) and hold.gate is gate and hold.active for hold in _holds.get())


def held_write_remaining_seconds() -> float | None:
    """Seconds left of the hold budget of the write(s) this operation holds, or ``None``."""
    remaining: float | None = None
    for hold in _holds.get():
        if isinstance(hold, WriteTicket) and hold.active and hold.granted_at is not None:
            gate = hold.gate
            left = hold.granted_at + gate.budget_of(hold) - gate.clock.now()
            remaining = left if remaining is None else min(remaining, left)
    return remaining


def extend_write_hold(seconds: float) -> bool:
    """Give the write this operation holds at least ``seconds`` more before it counts as over budget.

    For the rare operation that is known to run long and must not be cut off
    (a backup restore): its own request bound and the queued waiters measure
    against the extended budget, so waiters keep waiting while it legitimately
    runs. Declare it in code next to that operation's own explicit time limit.
    Returns ``False`` (and changes nothing) outside a held write.
    """
    _check_seconds("seconds", seconds)
    extended = False
    for hold in _holds.get():
        if isinstance(hold, WriteTicket) and hold.active and hold.granted_at is not None:
            gate = hold.gate
            needed = gate.clock.now() - hold.granted_at + seconds
            if needed > gate.budget_of(hold):
                hold.hold_budget = needed
                logger.info(
                    "Write gate %s: %s extended its hold budget to %.0fs",
                    gate.name,
                    hold.label or "write",
                    needed,
                )
            extended = True
    return extended


@asynccontextmanager
async def write_request_bound() -> AsyncIterator[None]:
    """Bound a controller request made inside a held write by what is left of its hold budget.

    A no-op outside a held write, so reads and ungated callers are unaffected.
    A request with no budget left is refused before it is sent; one that runs
    out of budget is cancelled and raises :class:`WriteRequestTimeout`.
    """
    remaining = held_write_remaining_seconds()
    if remaining is None:
        yield
        return
    if remaining <= 0:
        raise WriteRequestTimeout(
            "The write's time budget is spent; the controller request was not sent. "
            "Read the resource back before retrying the change."
        )
    # The remaining budget is read on the gate's clock, the timeout runs on the
    # event loop's. Both are monotonic seconds with the default clock; a test
    # clock only decides how much budget is left.
    timeout = asyncio.timeout(remaining)
    try:
        async with timeout:
            yield
    except TimeoutError:
        if timeout.expired():
            raise WriteRequestTimeout(
                "The controller did not answer within the write's time budget. "
                "The change may or may not have been applied; read the resource back before retrying."
            ) from None
        raise


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------

_WAITING = "waiting"
_HELD = "held"
_RELEASED = "released"
_WITHDRAWN = "withdrawn"


@dataclass(eq=False)
class WriteTicket(_Hold):
    """One request for a gate's write turn.

    ``position`` is how many write operations are ahead of it, the holder
    included: ``1`` means next in line, ``0`` means granted or finished.
    """

    gate: OperationGate
    number: int
    label: str | None
    requested_at: float
    granted_at: float | None = None
    state: str = _WAITING
    # A budget of its own, set by extend_write_hold; None uses the gate's.
    hold_budget: float | None = None
    _future: asyncio.Future[None] = field(repr=False, default=None)  # type: ignore[assignment]

    @property
    def active(self) -> bool:
        return self.state == _HELD

    @property
    def granted(self) -> bool:
        return self.state in (_HELD, _RELEASED)

    @property
    def waiting(self) -> bool:
        return self.state == _WAITING

    @property
    def position(self) -> int:
        return self.gate._position_of(self)

    def cancel(self) -> bool:
        """Withdraw the ticket if it is still queued; ``False`` once it was granted.

        The waiting operation raises :class:`WriteTicketCancelled` and nothing
        is sent to the controller.
        """
        return self.gate._withdraw(self)


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


@dataclass
class _LabelStats:
    count: int = 0
    total_seconds: float = 0.0
    max_seconds: float = 0.0

    def add(self, seconds: float) -> None:
        self.count += 1
        self.total_seconds += seconds
        self.max_seconds = max(self.max_seconds, seconds)


class OperationGate:
    """Exclusive FIFO writes and capped shared reads for one controller application."""

    def __init__(
        self,
        settings: GateSettings | None = None,
        *,
        name: str = "controller",
        clock: GateClock | None = None,
    ) -> None:
        self.settings = settings or GateSettings()
        self.name = name
        self.clock: GateClock = clock or MonotonicClock()
        self._holder: WriteTicket | None = None
        self._waiting: deque[WriteTicket] = deque()
        self._next_number = 0
        self._reads_in_use = 0
        self._read_waiters: deque[asyncio.Future[None]] = deque()
        self._counters: dict[str, int] = {
            "writes_requested": 0,
            "writes_granted": 0,
            "writes_completed": 0,
            "writes_withdrawn": 0,
            "writes_busy": 0,
            "holds_over_budget": 0,
            "reads_started": 0,
            "reads_busy": 0,
            "reads_nested": 0,
        }
        self._hold_stats: dict[str, _LabelStats] = {}

    # -- inspection ---------------------------------------------------------

    def budget_of(self, ticket: WriteTicket) -> float:
        """The hold budget that applies to ``ticket``: its own when extended, else the gate's."""
        return ticket.hold_budget if ticket.hold_budget is not None else self.settings.hold_budget_seconds

    @property
    def write_held(self) -> bool:
        """True while any operation holds the write turn."""
        return self._holder is not None

    def holds_write(self) -> bool:
        """True when the current operation holds this gate's write turn (for manager assertions)."""
        return _held_write(self) is not None

    @property
    def queue_depth(self) -> int:
        """Write requests waiting for their turn (the holder excluded)."""
        return len(self._waiting)

    def snapshot(self) -> dict[str, Any]:
        """Queue depth, holder age, read slots in use and counters, for support status.

        Carries no controller identity: labels are whatever callers passed
        (tool or action names).
        """
        now = self.clock.now()
        holder = self._holder
        holder_age = None if holder is None or holder.granted_at is None else max(0.0, now - holder.granted_at)
        oldest_wait = max(0.0, now - self._waiting[0].requested_at) if self._waiting else None
        return {
            "write_held": holder is not None,
            "holder_label": None if holder is None else holder.label,
            "holder_age_seconds": holder_age,
            "holder_over_budget": holder is not None and holder_age is not None and holder_age > self.budget_of(holder),
            "queue_depth": len(self._waiting),
            "oldest_wait_seconds": oldest_wait,
            "reads_in_use": self._reads_in_use,
            "reads_waiting": len(self._read_waiters),
            "read_cap": self.settings.read_cap,
            "hold_budget_seconds": self.settings.hold_budget_seconds,
            "counters": dict(self._counters),
            "hold_times": {
                label: {
                    "count": stats.count,
                    "total_seconds": round(stats.total_seconds, 3),
                    "max_seconds": round(stats.max_seconds, 3),
                }
                for label, stats in self._hold_stats.items()
            },
        }

    # -- writes -------------------------------------------------------------

    @asynccontextmanager
    async def write(self, *, wait_budget: float | None = None, label: str | None = None) -> AsyncIterator[WriteTicket]:
        """Hold this gate's exclusive write turn for the block, in request order.

        ``wait_budget`` (seconds) bounds this caller's wait; ``None`` waits as
        long as the queue keeps moving. Raises :class:`ControllerBusyError`
        when the wait fails, :class:`GateReentryError` when the current
        operation already holds the write.
        """
        if wait_budget is not None:
            _check_seconds("wait_budget", wait_budget)
        if _held_write(self) is not None:
            raise GateReentryError(
                f"The {self.name} write gate is already held by this operation; a nested write would deadlock. "
                "Run the nested change inside the held write, or start it with create_ungated_task."
            )
        ticket = self._enqueue(label)
        # The release sits in the outermost finally, independent of anything
        # else that can fail on the way out (an observer, a context reset).
        try:
            try:
                _notify("queued", ticket)
                _notify("admitted")
                await self._await_grant(ticket, wait_budget)
            except BaseException:
                self._abandon(ticket)
                raise
            _notify("granted", ticket)
            waited = (ticket.granted_at or ticket.requested_at) - ticket.requested_at
            logger.debug(
                "Write gate %s granted %s after %.3fs (%d queued)",
                self.name,
                label or "write",
                waited,
                len(self._waiting),
            )
            token = _holds.set((*_holds.get(), ticket))
            try:
                yield ticket
            finally:
                _reset_holds(token)
        finally:
            self._release(ticket)

    def _enqueue(self, label: str | None) -> WriteTicket:
        self._next_number += 1
        self._counters["writes_requested"] += 1
        ticket = WriteTicket(
            gate=self,
            number=self._next_number,
            label=label,
            requested_at=self.clock.now(),
            _future=asyncio.get_running_loop().create_future(),
        )
        if self._holder is None and not self._waiting:
            self._grant(ticket)
        else:
            self._waiting.append(ticket)
        return ticket

    def _grant(self, ticket: WriteTicket) -> None:
        ticket.state = _HELD
        ticket.granted_at = self.clock.now()
        self._holder = ticket
        self._counters["writes_granted"] += 1
        if not ticket._future.done():
            ticket._future.set_result(None)

    def _grant_next(self) -> None:
        while self._waiting:
            ticket = self._waiting.popleft()
            if ticket.state == _WAITING:
                self._grant(ticket)
                return

    def _release(self, ticket: WriteTicket) -> None:
        if ticket.state != _HELD:
            return
        now = self.clock.now()
        held = max(0.0, now - (ticket.granted_at or now))
        ticket.state = _RELEASED
        if self._holder is ticket:
            self._holder = None
        self._counters["writes_completed"] += 1
        self._record_hold(ticket.label, held)
        budget = self.budget_of(ticket)
        if held > budget:
            self._counters["holds_over_budget"] += 1
            logger.warning(
                "Write gate %s: %s held the write turn for %.1fs, over its %.0fs budget",
                self.name,
                ticket.label or "write",
                held,
                budget,
            )
        logger.debug(
            "Write gate %s released by %s after %.3fs (%d queued)",
            self.name,
            ticket.label or "write",
            held,
            len(self._waiting),
        )
        self._grant_next()

    def _record_hold(self, label: str | None, seconds: float) -> None:
        key = label or "write"
        if key not in self._hold_stats and len(self._hold_stats) >= _MAX_LABEL_STATS:
            key = _OTHER_LABEL
        self._hold_stats.setdefault(key, _LabelStats()).add(seconds)

    def _withdraw(self, ticket: WriteTicket) -> bool:
        if ticket.state != _WAITING:
            return False
        ticket.state = _WITHDRAWN
        try:
            self._waiting.remove(ticket)
        except ValueError:
            pass
        self._counters["writes_withdrawn"] += 1
        if not ticket._future.done():
            ticket._future.set_exception(WriteTicketCancelled("The queued write was cancelled before it ran."))
        return True

    def _abandon(self, ticket: WriteTicket) -> None:
        """The waiter is leaving: withdraw a queued ticket, or pass on a granted turn it never used."""
        if ticket.state == _WAITING:
            ticket.state = _WITHDRAWN
            try:
                self._waiting.remove(ticket)
            except ValueError:
                pass
            self._counters["writes_withdrawn"] += 1
            if not ticket._future.done():
                ticket._future.cancel()
        elif ticket.state == _HELD:
            logger.debug("Write gate %s: granted turn passed on unused", self.name)
            self._release(ticket)
        # Retrieve a stored exception so it is not reported as never retrieved.
        if ticket._future.done() and not ticket._future.cancelled():
            ticket._future.exception()

    def _position_of(self, ticket: WriteTicket) -> int:
        if ticket.state != _WAITING:
            return 0
        ahead = 1 if self._holder is not None else 0
        for other in self._waiting:
            if other is ticket:
                return max(ahead, 1)
            if other.state == _WAITING:
                ahead += 1
        return 0

    async def _await_grant(self, ticket: WriteTicket, wait_budget: float | None) -> None:
        future = ticket._future
        wait_deadline = None if wait_budget is None else ticket.requested_at + wait_budget
        while not future.done():
            now = self.clock.now()
            holder = self._holder
            hold_deadline = None
            if holder is not None and holder.granted_at is not None:
                hold_deadline = holder.granted_at + self.budget_of(holder) + HOLD_GRACE_SECONDS
            if wait_deadline is not None and now >= wait_deadline:
                self._counters["writes_busy"] += 1
                position = ticket.position
                logger.info(
                    "Write gate %s: %s gave up after its %.0fs wait budget at queue position %d",
                    self.name,
                    ticket.label or "write",
                    wait_budget,
                    position,
                )
                raise ControllerBusyError(
                    f"The {self.name} controller is busy with other changes: this change was still queued "
                    f"(position {position}) after {wait_budget:.0f}s and was not sent. Retry shortly, "
                    "or submit it through the batch tool, which waits its turn.",
                    reason="wait_budget",
                    retry_after=BUSY_RETRY_AFTER_SECONDS,
                    position=position,
                )
            if hold_deadline is not None and now >= hold_deadline:
                self._counters["writes_busy"] += 1
                held_for = now - (holder.granted_at or now) if holder is not None else 0.0
                logger.warning(
                    "Write gate %s: %s has held the write turn for %.0fs, over its %.0fs budget; "
                    "failing a queued write",
                    self.name,
                    holder.label if holder is not None and holder.label else "write",
                    held_for,
                    self.budget_of(holder) if holder is not None else self.settings.hold_budget_seconds,
                )
                holder_budget = self.budget_of(holder) if holder is not None else self.settings.hold_budget_seconds
                raise ControllerBusyError(
                    f"The {self.name} controller is busy: an earlier change has run for {held_for:.0f}s, "
                    f"past its {holder_budget:.0f}s budget. This change was not sent; "
                    "retry once the earlier change finishes.",
                    reason="holder_over_budget",
                    retry_after=BUSY_RETRY_AFTER_SECONDS,
                    position=ticket.position,
                )
            deadlines = [deadline for deadline in (wait_deadline, hold_deadline) if deadline is not None]
            if not deadlines:
                await asyncio.wait({future})
            else:
                await self._wait_or_sleep(future, min(deadlines) - now)
        future.result()

    async def _wait_or_sleep(self, future: asyncio.Future[Any], seconds: float) -> None:
        """Wait until ``future`` is done or ``seconds`` pass on the gate's clock."""
        sleeper = asyncio.ensure_future(self.clock.sleep(max(0.0, seconds)))
        try:
            await asyncio.wait({future, sleeper}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            if not sleeper.done():
                sleeper.cancel()

    # -- reads --------------------------------------------------------------

    @asynccontextmanager
    async def read(self, *, wait_budget: float | None = None, label: str | None = None) -> AsyncIterator[None]:
        """Hold one of this gate's shared read slots for the block.

        Inside a write or read the current operation already holds on this
        gate, the block runs without taking a slot. Raises
        :class:`ControllerBusyError` when ``wait_budget`` runs out before a
        slot frees.
        """
        if wait_budget is not None:
            _check_seconds("wait_budget", wait_budget)
        _notify("admitted")
        if _held_write(self) is not None or _holds_read(self):
            self._counters["reads_nested"] += 1
            yield
            return
        await self._acquire_read(wait_budget, label)
        hold = _ReadHold(self)
        try:
            token = _holds.set((*_holds.get(), hold))
            try:
                yield
            finally:
                _reset_holds(token)
        finally:
            hold.released = True
            self._release_read()

    async def _acquire_read(self, wait_budget: float | None, label: str | None) -> None:
        self._counters["reads_started"] += 1
        if self._reads_in_use < self.settings.read_cap and not self._read_waiters:
            self._reads_in_use += 1
            return
        started = self.clock.now()
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._read_waiters.append(future)
        try:
            while not future.done():
                if wait_budget is None:
                    await asyncio.wait({future})
                    continue
                remaining = started + wait_budget - self.clock.now()
                if remaining <= 0:
                    self._counters["reads_busy"] += 1
                    raise ControllerBusyError(
                        f"The {self.name} controller is busy: all {self.settings.read_cap} read slots stayed in use "
                        f"for {wait_budget:.0f}s. Nothing was sent; retry shortly.",
                        reason="wait_budget",
                        retry_after=BUSY_RETRY_AFTER_SECONDS,
                    )
                await self._wait_or_sleep(future, remaining)
        except BaseException:
            if future.done() and not future.cancelled():
                # The slot was handed over as we left: pass it on.
                self._release_read()
            else:
                future.cancel()
                try:
                    self._read_waiters.remove(future)
                except ValueError:
                    pass
            raise
        logger.debug("Read gate %s: %s waited %.3fs for a slot", self.name, label or "read", self.clock.now() - started)

    def _release_read(self) -> None:
        while self._read_waiters:
            waiter = self._read_waiters.popleft()
            if not waiter.done():
                # Hand the slot straight over; the count of slots in use is unchanged.
                waiter.set_result(None)
                return
        self._reads_in_use -= 1


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _normalise_product(product: str) -> str:
    if not isinstance(product, str) or not product.strip():
        raise ValueError("product must be a non-empty string")
    return product.strip().lower()


@dataclass(frozen=True)
class GateKey:
    """A controller application: who it is, plus the product.

    ``for_host`` follows the rule that matches server credentials to a
    console: the host as written with ASCII case folded, plus the effective
    port. Two differences, both of which can only merge gates, never split
    them: surrounding whitespace is dropped from the host, and the port is
    443 when none (or a blank) is given, a number written in digits is
    compared as that number (``"0443"`` is ``443``), and any other port text
    is kept as written once trimmed. ``for_controller`` keys an API server's
    stored controller record by its trimmed id.
    """

    scope: str
    identity: str
    product: str

    @classmethod
    def for_host(cls, host: str, port: int | str | None, product: str) -> GateKey:
        if not isinstance(host, str) or not host.strip():
            raise ValueError("host must be a non-empty string")
        host = host.strip()
        folded = host.lower() if host.isascii() else host
        port_text = "443" if port is None or (isinstance(port, str) and not port.strip()) else str(port).strip()
        if port_text.isdigit():
            port_text = str(int(port_text))
        return cls("host", f"{folded}:{port_text}", _normalise_product(product))

    @classmethod
    def for_controller(cls, controller_id: str, product: str) -> GateKey:
        if not isinstance(controller_id, str) or not controller_id.strip():
            raise ValueError("controller_id must be a non-empty string")
        return cls("controller", controller_id.strip(), _normalise_product(product))

    @property
    def log_name(self) -> str:
        """A name for logs and errors that never carries the host."""
        return self.product if self.scope == "host" else f"{self.product} ({self.identity})"


class GateRegistry:
    """One gate per controller application for the life of the process."""

    for_host = staticmethod(GateKey.for_host)
    for_controller = staticmethod(GateKey.for_controller)

    def __init__(self, *, clock: GateClock | None = None) -> None:
        self._gates: dict[GateKey, OperationGate] = {}
        self._clock = clock

    def get(self, key: GateKey, settings: GateSettings | None = None) -> OperationGate:
        """The gate for ``key``, created with ``settings`` on first use.

        Later calls return the same gate; settings passed after creation are
        ignored, since a server reads its settings once at start-up.
        """
        gate = self._gates.get(key)
        if gate is None:
            gate = OperationGate(settings, name=key.log_name, clock=self._clock)
            self._gates[key] = gate
        return gate

    def gates(self) -> dict[GateKey, OperationGate]:
        """A copy of the gates created so far."""
        return dict(self._gates)

    def reset(self) -> None:
        """Forget every gate. For tests; never while operations are in flight."""
        self._gates.clear()


_DEFAULT_REGISTRY = GateRegistry()


def gate_registry() -> GateRegistry:
    """The process-wide registry."""
    return _DEFAULT_REGISTRY


def reset_gate_registry_for_tests() -> None:
    """Forget every gate in the process-wide registry."""
    _DEFAULT_REGISTRY.reset()
