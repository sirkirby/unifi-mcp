"""Reconnect to UniFi Protect before a domain tool runs.

Every domain tool reaches the controller through the connection manager's
``client``, which has no client when the controller was unreachable or
rejected the login at start-up. Wrapping the tool decorator gives each tool
call one chance to connect first, in one place instead of in every manager
method. The connection manager rate-limits those attempts and holds them back
during its auth cool-down, so a controller that stays down fails tool calls
quickly with a clear error.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable


def reconnecting_tool_decorator(tool_decorator: Callable, connection_manager: Any) -> Callable:
    """Wrap a FastMCP-style ``tool(...)`` decorator so each tool first ensures a connection."""

    def tool(*d_args: Any, **d_kwargs: Any) -> Callable:
        register = tool_decorator(*d_args, **d_kwargs)

        def decorator(func: Callable) -> Any:
            @wraps(func)
            async def connected_tool(*args: Any, **kwargs: Any) -> Any:
                # A failed attempt leaves the tool to report the connection
                # error the manager raises.
                await connection_manager.ensure_connected()
                return await func(*args, **kwargs)

            return register(connected_tool)

        return decorator

    return tool
