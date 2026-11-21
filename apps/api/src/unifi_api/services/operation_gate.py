"""The controller operation gate for the API server.

One gate per (stored controller, product), shared by the action endpoint, the
resource routes and GraphQL, so REST and GraphQL clients never write to one
controller application at the same time:

- ``dispatch_action`` enters the gate itself, in write mode for a confirmed
  mutation and read mode otherwise, before it resolves a manager.
- Resource and GraphQL read routes install :func:`hold_controller_read_slots`
  as a route dependency. The first time a request reaches a controller
  application through the :class:`ManagerFactory`, it takes one read slot on
  that gate for the rest of the request; later lookups in the same request,
  concurrent GraphQL fields included, reuse it, so one request never holds two
  slots on one gate.

The slot is taken inside the handler, where the factory is called, not in the
dependency's own code: FastAPI may run a dependency's setup and teardown in a
different context from the endpoint. The dependency opens the request's scope
and, when the request ends, closes it: it releases every slot it took and
cancels any work of the request still running (a GraphQL field left behind
when a sibling field failed), and a lookup made after that is refused. No read
runs outside its request's slot, and no slot outlives its request.

Reads that reach a controller outside this cap: the controller capability
probes and ``probe_controller`` (admin and controller-management paths), and
event streams, which read the websocket buffer.

The guarantee is per API server process. Limits come from ``ApiConfig.gate``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextvars import ContextVar
from typing import Any

from unifi_core.operation_gate import ControllerBusyError, GateKey, GateSettings, OperationGate, gate_registry

logger = logging.getLogger(__name__)

_settings = GateSettings()

# How long closing a request waits for its cancelled leftover work to stop.
_LEFTOVER_STOP_SECONDS = 5.0


def configure_gate_settings(settings: GateSettings) -> None:
    """Set the limits gates are created with; called once when the app is built."""
    global _settings
    _settings = settings


def gate_settings() -> GateSettings:
    return _settings


def gate_for(controller_id: str, product: str) -> OperationGate:
    """The operation gate for one stored controller's product, for the life of the process."""
    return gate_registry().get(GateKey.for_controller(controller_id, product), _settings)


class RequestAlreadyFinished(RuntimeError):
    """A controller read was asked for after its request ended; it was not run."""


class _RequestReadScope:
    """The read slots one request holds, at most one per gate, and the work that uses them."""

    def __init__(self) -> None:
        self.closed = False
        self._held: list[Any] = []
        self._taken: dict[int, asyncio.Future[None]] = {}
        self._tasks: set[asyncio.Task[Any]] = set()

    def _refuse_if_closed(self) -> None:
        if self.closed:
            raise RequestAlreadyFinished("The request already finished; this controller read was not run.")

    async def take(self, gate: OperationGate, *, controller_id: str, label: str) -> None:
        task = asyncio.current_task()
        while True:
            self._refuse_if_closed()
            if task is not None:
                self._tasks.add(task)
            pending = self._taken.get(id(gate))
            if pending is not None:
                # Another lookup in this request (or a concurrent GraphQL field)
                # has the slot, or is taking it: share it rather than take a
                # second one. If that attempt failed, try again ourselves.
                try:
                    await asyncio.shield(pending)
                except ControllerBusyError:
                    raise
                except (Exception, asyncio.CancelledError):
                    if task is not None and task.cancelling():
                        raise
                    continue
                self._refuse_if_closed()
                return
            await self._acquire(gate, controller_id=controller_id, label=label)
            return

    async def _acquire(self, gate: OperationGate, *, controller_id: str, label: str) -> None:
        pending: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._taken[id(gate)] = pending
        read = gate.read(wait_budget=gate.settings.direct_call_wait_seconds, label=label)
        try:
            await read.__aenter__()
        except BaseException as exc:
            if self._taken.get(id(gate)) is pending:
                del self._taken[id(gate)]
            if isinstance(exc, ControllerBusyError):
                exc.controller_id = controller_id  # type: ignore[attr-defined]
            if isinstance(exc, asyncio.CancelledError):
                pending.cancel()
            else:
                pending.set_exception(exc)
                pending.exception()  # retrieved: the error is raised here, not left unread
            raise
        if self.closed:
            # Granted after the request ended: give the slot straight back.
            await read.__aexit__(None, None, None)
            pending.set_exception(RequestAlreadyFinished("The request already finished."))
            pending.exception()
            self._refuse_if_closed()
        self._held.append(read)
        pending.set_result(None)

    async def release(self) -> None:
        """End the request: stop its leftover work, then give back every slot it holds."""
        self.closed = True
        current = asyncio.current_task()
        leftovers = [task for task in self._tasks if task is not current and not task.done()]
        for task in leftovers:
            task.cancel()
        if leftovers:
            # Bounded: work that ignores its cancellation cannot hold the request open.
            await asyncio.wait(leftovers, timeout=_LEFTOVER_STOP_SECONDS)
        self._tasks.clear()
        held, self._held = self._held, []
        for read in reversed(held):
            try:
                await read.__aexit__(None, None, None)
            except Exception:
                logger.exception("Releasing a controller read slot failed")


_scope: ContextVar[_RequestReadScope | None] = ContextVar("unifi_api_read_scope", default=None)


async def hold_controller_read_slots() -> AsyncIterator[None]:
    """Route dependency: reads in this request take one controller read slot per gate."""
    scope = _RequestReadScope()
    token = _scope.set(scope)
    try:
        yield
    finally:
        try:
            _scope.reset(token)
        except ValueError:
            # Torn down in another context: the scope is released below regardless.
            pass
        await scope.release()


def in_read_scope() -> bool:
    """Whether the current request reads controllers under a read slot."""
    return _scope.get() is not None


async def take_read_slot(gate: OperationGate, *, controller_id: str, label: str) -> None:
    """Take this request's read slot on ``gate``, if the request reads under one.

    A no-op outside a route that installed :func:`hold_controller_read_slots`
    (the action endpoint gates itself; admin and probe paths are not gated).
    Raises :class:`RequestAlreadyFinished` once the request has ended.
    """
    scope = _scope.get()
    if scope is not None:
        await scope.take(gate, controller_id=controller_id, label=label)
