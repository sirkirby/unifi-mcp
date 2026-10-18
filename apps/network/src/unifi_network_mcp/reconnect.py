"""Connect to the UniFi Network controller before a domain tool runs.

The server answers MCP requests while the controller connection is still
being made in the background, or after it failed. Wrapping the tool decorator
gives each tool call one bounded wait for that connection, in one place
instead of in every manager method. The connection manager shares one
attempt between callers and spaces automatic attempts out, so a controller
that stays down fails tool calls quickly. A call that finds no connection
gets the manager's reason (still connecting, unreachable, or login rejected)
instead of the managers' generic "Not connected to controller".

Only the registered MCP tool carries the check; the decorated name in the
tool module stays the plain tool function, as it was before.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from unifi_core.exceptions import UniFiAuthError


def reconnecting_tool_decorator(tool_decorator: Callable, connection_manager: Any) -> Callable:
    """Wrap a FastMCP-style ``tool(...)`` decorator so each tool first ensures a connection."""

    def tool(*d_args: Any, **d_kwargs: Any) -> Callable:
        register = tool_decorator(*d_args, **d_kwargs)
        tool_name = d_kwargs.get("name") or (d_args[0] if d_args and isinstance(d_args[0], str) else None)

        def decorator(func: Callable) -> Any:
            name = tool_name or getattr(func, "__name__", "tool")

            @wraps(func)
            async def connected_tool(*args: Any, **kwargs: Any) -> Any:
                if not connection_manager.host:
                    # Setup mode: no controller is configured, so there is nothing to wait for.
                    return await func(*args, **kwargs)
                try:
                    connected = await connection_manager.ensure_connected()
                except UniFiAuthError:
                    # API-key-only inventory route: the tool reports what it can serve.
                    connected = True
                if not connected:
                    return {
                        "success": False,
                        "error": f"Cannot run {name}: {connection_manager.not_connected_message()}",
                    }
                return await func(*args, **kwargs)

            register(connected_tool)
            return func

        return decorator

    return tool
