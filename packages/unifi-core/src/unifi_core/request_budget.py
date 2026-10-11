"""Charge every controller request a bounded read makes, retries and probes included.

A bounded collection installs a charge with :func:`charging_requests` around
one page read. Each actual HTTP attempt made while it is installed calls the
charge first, which may refuse the attempt by raising
:class:`RequestBudgetSpent` before anything is sent:

- Network ``ConnectionManager.request`` charges each attempt it sends,
  including the API-version probe and the retry after a re-login.
- Protect evidence reads pass :func:`charged_request_middleware` to aiohttp
  for their one request, so uiprotect's status retries and reconnect retries
  are charged too.

Logins that establish or renew a session are not charged. With no charge
installed every hook is a no-op, so ordinary tool calls are unaffected.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

import aiohttp

_charge: ContextVar[Callable[[], None] | None] = ContextVar("unifi_request_charge", default=None)


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


async def charged_request_middleware(
    request: aiohttp.ClientRequest, handler: aiohttp.ClientHandlerType
) -> aiohttp.ClientResponse:
    """Per-request aiohttp middleware: runs once per attempt, so every retry is charged."""
    charge_request()
    return await handler(request)
