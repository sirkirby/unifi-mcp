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
unaffected.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

import aiohttp

_charge: ContextVar[Callable[[], None] | None] = ContextVar("unifi_request_charge", default=None)
# Attempts already charged by their caller (ConnectionManager.request), which
# the session middleware must not charge again.
_prepaid: ContextVar[list[int] | None] = ContextVar("unifi_request_prepaid", default=None)

# Login endpoints (UniFi OS and standalone): sessions are established, not charged.
LOGIN_PATHS = ("/api/auth/login", "/api/login")


class RequestBudgetSpent(Exception):
    """A request was refused before sending because the call budget is spent."""


@contextmanager
def charging_requests(charge: Callable[[], None]) -> Iterator[None]:
    """Charge each request attempt made inside the block (in this task) to ``charge``."""
    token = _charge.set(charge)
    try:
        yield
    finally:
        _charge.reset(token)


def charge_request() -> None:
    """Charge one request attempt, or refuse it; a no-op outside a bounded read."""
    charge = _charge.get()
    if charge is not None:
        charge()


@contextmanager
def prepaid_attempt() -> Iterator[None]:
    """The next request sent inside the block was already charged by its caller."""
    token = _prepaid.set([1])
    try:
        yield
    finally:
        _prepaid.reset(token)


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
        if prepaid and prepaid[0] > 0:
            prepaid[0] -= 1
        else:
            charge_request()
    return await handler(request)
