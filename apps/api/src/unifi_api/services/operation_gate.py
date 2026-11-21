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
  concurrent GraphQL fields included, reuse it, and a read nested in the
  handler passes through, so one request never holds two slots on one gate.

The slot is taken inside the handler, where the factory is called, not in the
dependency's own code: FastAPI may run a dependency's setup and teardown in a
different context from the endpoint, and the gate's ownership mark has to live
in the context that does the reading. The dependency only opens the request's
scope and releases what it took.

The guarantee is per API server process. Limits come from ``ApiConfig.gate``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from contextvars import ContextVar

from unifi_core.operation_gate import ControllerBusyError, GateKey, GateSettings, OperationGate, gate_registry

_settings = GateSettings()


def configure_gate_settings(settings: GateSettings) -> None:
    """Set the limits gates are created with; called once when the app is built."""
    global _settings
    _settings = settings


def gate_settings() -> GateSettings:
    return _settings


def gate_for(controller_id: str, product: str) -> OperationGate:
    """The operation gate for one stored controller's product, for the life of the process."""
    return gate_registry().get(GateKey.for_controller(controller_id, product), _settings)


class _RequestReadScope:
    """The read slots one request holds, at most one per gate."""

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._taken: dict[int, asyncio.Future[None]] = {}

    async def take(self, gate: OperationGate, *, controller_id: str, label: str) -> None:
        pending = self._taken.get(id(gate))
        if pending is not None:
            # Another lookup in this request (or a concurrent GraphQL field) has
            # it, or is taking it: share that slot rather than take a second one.
            await asyncio.shield(pending)
            return
        pending = asyncio.get_running_loop().create_future()
        self._taken[id(gate)] = pending
        try:
            await self._stack.enter_async_context(
                gate.read(wait_budget=gate.settings.direct_call_wait_seconds, label=label)
            )
        except BaseException as exc:
            del self._taken[id(gate)]
            if isinstance(exc, ControllerBusyError):
                exc.controller_id = controller_id  # type: ignore[attr-defined]
            if not pending.done():
                pending.set_exception(exc)
                pending.exception()  # retrieved: the error is raised here, not left unread
            raise
        pending.set_result(None)

    async def release(self) -> None:
        await self._stack.aclose()


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


async def take_read_slot(controller_id: str, product: str, *, label: str) -> None:
    """Take this request's read slot on the controller application's gate, if it reads under one.

    A no-op outside a route that installed :func:`hold_controller_read_slots`
    (the action endpoint gates itself; admin and probe paths are not gated).
    """
    scope = _scope.get()
    if scope is not None:
        await scope.take(gate_for(controller_id, product), controller_id=controller_id, label=label)
