"""The argument names an MCP caller actually sent with the current tool call.

FastMCP validates tool arguments into a model and calls the tool with every
field, defaults included, so a tool wrapper cannot tell an omitted ``confirm``
from an explicit ``confirm=false`` by looking at its kwargs. ``StrictKwargFastMCP``
records the caller's top-level argument names here for the duration of each
``call_tool``; wrappers read them with :func:`caller_supplied`.

Outside an MCP dispatch (a direct Python call, a unit test, the API server
calling a tool function) nothing is recorded and the wrapper's own kwargs are
the caller's arguments.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Mapping

_SUPPLIED_ARGUMENTS: ContextVar[frozenset[str] | None] = ContextVar("unifi_mcp_supplied_arguments", default=None)


@contextmanager
def recording_supplied_arguments(arguments: Mapping[str, Any] | None) -> Iterator[None]:
    """Record the caller's argument names for one tool dispatch.

    Nested dispatches (``unifi_execute``, ``unifi_batch``) record their own
    arguments and restore the outer value when they return.
    """
    token = _SUPPLIED_ARGUMENTS.set(frozenset(arguments or ()))
    try:
        yield
    finally:
        _SUPPLIED_ARGUMENTS.reset(token)


def supplied_arguments() -> frozenset[str] | None:
    """The argument names of the MCP call in progress, or None outside one."""
    return _SUPPLIED_ARGUMENTS.get()


def caller_supplied(name: str, kwargs: Mapping[str, Any]) -> bool:
    """Whether the caller passed ``name`` itself, rather than receiving its default."""
    supplied = _SUPPLIED_ARGUMENTS.get()
    if supplied is None:
        return name in kwargs
    return name in supplied
