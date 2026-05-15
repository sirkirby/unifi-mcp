"""Permissioned FastMCP tool decorator.

Wraps ``@server.tool()`` with auth and policy enforcement from
``unifi_core.permission``.
"""

from __future__ import annotations

import inspect
from functools import wraps
from typing import Any, Callable

from unifi_core.permission import _infer_input_schema
from unifi_core.policy_gate import resolve_permission_mode

from unifi_mcp_shared.output_schema import apply_unifi_tool_response_signature, get_unifi_tool_response_output_schema


def setup_permissioned_tool(
    *,
    server: Any,
    category_map: dict[str, str],
    server_prefix: str,
    register_tool_fn: Callable,
    diagnostics_enabled_fn: Callable[[], bool],
    wrap_tool_fn: Callable,
    logger: Any,
) -> Callable:
    """One-call setup: create a permissioned_tool decorator and install it on *server*.

    This is a convenience wrapper around :func:`create_permissioned_tool` that also
    creates the ``PolicyGateChecker`` and replaces ``server.tool``.

    Returns the permissioned_tool decorator (also installed as ``server.tool``).
    """
    from unifi_core.policy_gate import PolicyGateChecker

    original = getattr(server, "_original_tool", server.tool)
    checker = PolicyGateChecker(server_prefix=server_prefix, category_map=category_map)
    pt = create_permissioned_tool(
        original_tool_decorator=original,
        policy_gate_checker=checker,
        server_prefix=server_prefix,
        register_tool_fn=register_tool_fn,
        diagnostics_enabled_fn=diagnostics_enabled_fn,
        wrap_tool_fn=wrap_tool_fn,
        logger=logger,
    )
    server.tool = pt  # type: ignore[assignment]
    return pt


def create_permissioned_tool(
    *,
    original_tool_decorator: Callable,
    policy_gate_checker: Any,
    server_prefix: str,
    register_tool_fn: Callable,
    diagnostics_enabled_fn: Callable[[], bool],
    wrap_tool_fn: Callable,
    logger: Any,
) -> Callable:
    """Create a permissioned_tool decorator for a specific MCP server.

    Args:
        original_tool_decorator: The original FastMCP ``server.tool`` decorator.
        policy_gate_checker: A ``PolicyGateChecker`` instance for this server.
        server_prefix: The server prefix for permission mode resolution (e.g. "NETWORK").
        register_tool_fn: Function to register tool metadata in the tool index.
        diagnostics_enabled_fn: Callable returning whether diagnostics are enabled.
        wrap_tool_fn: Function to wrap a tool with diagnostics logging.
        logger: Logger instance for permission messages.

    Returns:
        A ``permissioned_tool`` decorator function that acts like ``@server.tool``.
    """

    def permissioned_tool(*d_args, **d_kwargs):
        """Decorator that registers the tool and checks policy gates at call time."""

        tool_name = d_kwargs.get("name") if d_kwargs.get("name") else (d_args[0] if d_args else None)

        category = d_kwargs.pop("permission_category", None)
        action = d_kwargs.pop("permission_action", None)
        auth_method = d_kwargs.pop("auth", None)

        # Default to local_only when auth is not specified (backward compatible)
        resolved_auth = auth_method if auth_method else "local_only"

        def decorator(func):
            """Inner decorator that always registers the tool with MCP."""
            nonlocal category, action, tool_name

            if not tool_name:
                tool_name = getattr(func, "__name__", "<unknown>")

            description = d_kwargs.get("description", "")
            input_schema = d_kwargs.pop("input_schema", None)
            output_schema = d_kwargs.pop("output_schema", None)
            if output_schema is None:
                output_schema = get_unifi_tool_response_output_schema()
            if d_kwargs.get("structured_output") is None:
                d_kwargs["structured_output"] = True

            # If no explicit input_schema, try to infer from function annotations
            if input_schema is None:
                input_schema = _infer_input_schema(func, tool_name, logger)

            # Fast path: no permissions requested, just register.
            if not category or not action:
                register_tool_fn(
                    name=tool_name,
                    description=description,
                    input_schema=input_schema,
                    output_schema=output_schema,
                    auth_method=resolved_auth,
                )
                wrapped = (
                    wrap_tool_fn(func, tool_name or getattr(func, "__name__", "<tool>"))
                    if diagnostics_enabled_fn()
                    else func
                )
                wrapped = apply_unifi_tool_response_signature(wrapped)
                return original_tool_decorator(*d_args, **d_kwargs)(wrapped)

            # ALWAYS register in tool index (for discovery)
            register_tool_fn(
                name=tool_name,
                description=description,
                input_schema=input_schema,
                output_schema=output_schema,
                auth_method=resolved_auth,
                permission_category=category,
                permission_action=action,
            )

            # Wrap function with policy gate + bypass injection
            @wraps(func)
            async def gated_func(*args, **kwargs):
                # 1. Policy gate check at call time
                if not policy_gate_checker.check(category, action):
                    return {"success": False, "error": policy_gate_checker.denial_message(category, action)}

                # 2. Bypass injection — only for mutation actions with confirm param
                #    Only inject if caller didn't explicitly provide confirm
                if action.lower() != "read":
                    mode = resolve_permission_mode(server_prefix)
                    if mode == "bypass":
                        sig = inspect.signature(func)
                        if "confirm" in sig.parameters and "confirm" not in kwargs:
                            kwargs["confirm"] = True

                return await func(*args, **kwargs)

            # Apply diagnostics wrapping if enabled
            wrapped = (
                wrap_tool_fn(gated_func, tool_name or getattr(func, "__name__", "<tool>"))
                if diagnostics_enabled_fn()
                else gated_func
            )
            wrapped = apply_unifi_tool_response_signature(wrapped)

            # ALWAYS register with MCP
            return original_tool_decorator(*d_args, **d_kwargs)(wrapped)

        return decorator

    return permissioned_tool
