"""Charge every controller request a bounded read makes, retries and probes included.

A bounded collection installs a charge with :func:`charging_requests` around
one page read. Each actual HTTP attempt made while it is installed calls the
charge first, which may refuse the attempt by raising
:class:`RequestBudgetSpent` before anything is sent:

- Network ``ConnectionManager.request`` charges each attempt it sends,
  including the API-version probe and the retry after a re-login, and marks
  it prepaid for the session.
- Connection sessions (Network's aiohttp session, Protect's private and
  public sessions) carry :func:`charged_session_middleware`, so every other
  request a cold connection sends while acquiring the manager (controller
  detection, sites checks, the Protect bootstrap, their retries) is charged
  too. Logins are not charged.
- Protect evidence reads pass :func:`charged_request_middleware` for their
  one request, replacing the session's, so uiprotect's status and reconnect
  retries are charged once each.

With no charge installed every hook is a no-op, so ordinary tool calls are
unaffected. A charge applies only in the task that installed it: a task
started during a read (a bootstrap refresh, a websocket, an SDK's own
helper) inherits the context but is never charged or refused. Persistent
background tasks are also started with :func:`create_uncharged_task`, which
clears the charge outright.
"""

from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, TypeVar

import aiohttp

# The charge, and the task that installed it.
_charge: ContextVar[tuple[Callable[[], None], asyncio.Task[Any] | None] | None] = ContextVar(
    "unifi_request_charge", default=None
)
# Attempts already charged by their caller (ConnectionManager.request), which
# the session middleware must not charge again, and the task they belong to.
_prepaid: ContextVar[tuple[list[int], asyncio.Task[Any] | None] | None] = ContextVar(
    "unifi_request_prepaid", default=None
)

T = TypeVar("T")

# Login endpoints (UniFi OS and standalone): sessions are established, not charged.
LOGIN_PATHS = ("/api/auth/login", "/api/login")


class RequestBudgetSpent(Exception):
    """A request was refused before sending because the call budget is spent."""


@contextmanager
def charging_requests(charge: Callable[[], None]) -> Iterator[None]:
    """Charge each request attempt made inside the block (in this task) to ``charge``."""
    token = _charge.set((charge, _current_task()))
    try:
        yield
    finally:
        _charge.reset(token)


def _current_task() -> asyncio.Task[Any] | None:
    try:
        return asyncio.current_task()
    except RuntimeError:
        return None


def charge_request() -> None:
    """Charge one request attempt, or refuse it; a no-op outside a bounded read's own task."""
    installed = _charge.get()
    if installed is not None and installed[1] is _current_task():
        installed[0]()


@contextmanager
def prepaid_attempt() -> Iterator[None]:
    """The next request sent inside the block was already charged by its caller."""
    token = _prepaid.set(([1], _current_task()))
    try:
        yield
    finally:
        _prepaid.reset(token)


def uncharged_context() -> contextvars.Context:
    """A copy of the current context with no request charge and nothing prepaid."""
    context = contextvars.copy_context()
    context.run(_charge.set, None)
    context.run(_prepaid.set, None)
    return context


def create_uncharged_task(coro: Coroutine[Any, Any, T], *, name: str | None = None) -> asyncio.Task[T]:
    """Start a persistent background task that no bounded read can charge or refuse."""
    return asyncio.get_running_loop().create_task(coro, name=name, context=uncharged_context())


async def charged_request_middleware(
    request: aiohttp.ClientRequest, handler: aiohttp.ClientHandlerType
) -> aiohttp.ClientResponse:
    """Per-request aiohttp middleware: runs once per attempt, so every retry is charged."""
    charge_request()
    return await handler(request)


async def charged_session_middleware(
    request: aiohttp.ClientRequest, handler: aiohttp.ClientHandlerType
) -> aiohttp.ClientResponse:
    """Session-wide aiohttp middleware: charge each non-login attempt not already prepaid."""
    if not request.url.path.endswith(LOGIN_PATHS):
        prepaid = _prepaid.get()
        if prepaid is not None and prepaid[1] is _current_task() and prepaid[0][0] > 0:
            prepaid[0][0] -= 1
        else:
            charge_request()
    return await handler(request)
