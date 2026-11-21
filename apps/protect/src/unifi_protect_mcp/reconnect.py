"""Reconnect to UniFi Protect before a domain tool runs.

Every domain tool reaches the controller through the connection manager's
``client``, which has no client when the controller was unreachable or
rejected the login at start-up. Wrapping the tool decorator gives each tool
call one chance to connect first, in one place instead of in every manager
method. The connection manager rate-limits those attempts and holds them back
during its auth cool-down, so a controller that stays down fails tool calls
quickly with a clear error.

Inside a held write the tool body is also bounded by what is left of the
write's hold budget. uiprotect owns its HTTP session and retries requests on
its own, so no single request can be bounded from here; bounding the whole
operation keeps a hung controller from holding the write turn past its budget.
Reads and ungated calls are not bounded.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from unifi_core.operation_gate import WriteRequestTimeout, write_request_bound

_STALE_CACHE_NOTE = (
    "Protect's cached device state may show the change until its next bootstrap refresh (about a minute)."
)


def reconnecting_tool_decorator(tool_decorator: Callable, connection_manager: Any) -> Callable:
    """Wrap a FastMCP-style ``tool(...)`` decorator so each tool first ensures a connection."""

    def tool(*d_args: Any, **d_kwargs: Any) -> Callable:
        register = tool_decorator(*d_args, **d_kwargs)
        tool_name = d_kwargs.get("name") or (d_args[0] if d_args and isinstance(d_args[0], str) else None)

        def decorator(func: Callable) -> Any:
            name = tool_name or getattr(func, "__name__", "tool")

            @wraps(func)
            async def connected_tool(*args: Any, **kwargs: Any) -> Any:
                # A failed attempt leaves the tool to report the connection
                # error the manager raises.
                await connection_manager.ensure_connected()
                try:
                    async with write_request_bound():
                        return await func(*args, **kwargs)
                except WriteRequestTimeout as exc:
                    if not getattr(exc, "request_sent", True):
                        # The budget was spent before the body ran: nothing was sent.
                        return {"success": False, "error": f"Failed to run {name}: {exc}", "mutation_applied": False}
                    # The change may have reached the controller: the outcome is
                    # unknown. uiprotect reverts its cached copy only when a request
                    # fails, not when it is cut off, so say the cache may be stale.
                    return {
                        "success": False,
                        "error": f"Failed to run {name}: {exc} {_STALE_CACHE_NOTE}",
                        "mutation_applied": None,
                    }

            return register(connected_tool)

        return decorator

    return tool
