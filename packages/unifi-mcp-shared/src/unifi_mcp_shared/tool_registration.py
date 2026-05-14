"""Shared tool registration mode dispatch for MCP servers.

All three MCP servers (Network, Protect, Access) use the same three-mode
registration pattern: ``meta_only``, ``lazy``, and ``eager``.  This module
extracts that dispatch logic so each server's ``main.py`` only needs to
call :func:`register_tools_for_mode` with server-specific parameters.
"""

from __future__ import annotations

import logging
from typing import Any, Callable


def _parse_filter_list(value: Any) -> list[str] | None:
    """Parse a comma-separated string (or None/null) into a list or None."""
    if isinstance(value, str) and value not in ("null", ""):
        return [item.strip() for item in value.split(",")]
    if value in (None, "null", ""):
        return None
    # Already a list or other type — pass through
    return value


async def register_tools_for_mode(
    *,
    mode: str,
    server: Any,
    original_tool_decorator: Callable,
    tool_index_handler: Callable,
    start_async_tool: Callable,
    get_job_status: Callable,
    register_tool: Callable,
    tool_module_map: dict,
    setup_lazy_loading: Callable,
    base_package: str,
    config: Any,
    logger: logging.Logger,
    prefix: str = "",
    server_label: str = "",
    register_meta_tools: Callable | None = None,
    register_load_tools: Callable | None = None,
    auto_load_tools: Callable | None = None,
) -> None:
    """Register meta-tools and domain tools based on *mode*.

    Args:
        mode: One of ``"meta_only"``, ``"lazy"``, or ``"eager"``.
        server: The FastMCP server instance.
        original_tool_decorator: The unwrapped ``server.tool`` decorator.
        tool_index_handler: Handler for the tool index meta-tool.
        start_async_tool: Handler for starting async tool execution.
        get_job_status: Handler for checking async job status.
        register_tool: Function to register tool metadata in the index.
        tool_module_map: Mapping of tool names to their module paths.
        setup_lazy_loading: Function to set up lazy loading for the server.
        base_package: Dotted package path for tool modules (e.g. ``"unifi_network_mcp.tools"``).
        config: Server config object (used for ``enabled_categories``/``enabled_tools``).
        logger: Logger instance.
        prefix: Tool name prefix (e.g. ``"protect"``). Empty string for Network (uses ``"unifi"``).
        server_label: Human-readable server name (e.g. ``"UniFi Protect"``).
        register_meta_tools: Shared meta-tools registration function.
        register_load_tools: Shared load_tools registration function.
        auto_load_tools: Shared eager tool auto-discovery function.
    """
    # Late-import defaults from shared package if not provided
    if register_meta_tools is None:
        from unifi_mcp_shared.meta_tools import register_meta_tools
    if register_load_tools is None:
        from unifi_mcp_shared.meta_tools import register_load_tools
    if auto_load_tools is None:
        from unifi_mcp_shared.tool_loader import auto_load_tools

    # Build kwargs for meta-tools (prefix/server_label only if non-default)
    meta_kwargs: dict[str, Any] = dict(
        server=server,
        tool_decorator=original_tool_decorator,
        tool_index_handler=tool_index_handler,
        start_async_tool=start_async_tool,
        get_job_status=get_job_status,
        register_tool=register_tool,
    )
    if prefix:
        meta_kwargs["prefix"] = prefix
        meta_kwargs["server_label"] = server_label

    # Always register meta-tools first
    register_meta_tools(**meta_kwargs)

    tool_prefix = prefix or "unifi"

    if mode == "meta_only":
        logger.info("Tool registration mode: meta_only")
        logger.info(
            "   Meta-tools: %s_tool_index, %s_execute, %s_batch, %s_batch_status",
            tool_prefix,
            tool_prefix,
            tool_prefix,
            tool_prefix,
        )
        logger.info("   Use %s_execute to run any tool discovered via %s_tool_index", tool_prefix, tool_prefix)
        logger.info("   To load all tools directly: set UNIFI_TOOL_REGISTRATION_MODE=eager")

        setup_lazy_loading(server, original_tool_decorator)
        logger.info("   On-demand loader ready - %d tools available via %s_execute", len(tool_module_map), tool_prefix)

    elif mode == "lazy":
        logger.info("Tool registration mode: lazy")
        logger.info(
            "   Meta-tools: %s_tool_index, %s_execute, %s_batch, %s_batch_status, %s_load_tools",
            tool_prefix,
            tool_prefix,
            tool_prefix,
            tool_prefix,
            tool_prefix,
        )
        logger.info("   Use %s_execute to run any tool - works with all clients", tool_prefix)

        lazy_loader = setup_lazy_loading(server, original_tool_decorator)

        load_kwargs: dict[str, Any] = dict(
            server=server,
            tool_decorator=original_tool_decorator,
            lazy_loader=lazy_loader,
            register_tool=register_tool,
            tool_module_map=tool_module_map,
        )
        if prefix:
            load_kwargs["prefix"] = prefix
            load_kwargs["server_label"] = server_label
        register_load_tools(**load_kwargs)

        logger.info("   Lazy loader ready - %d tools available on-demand", len(tool_module_map))

    else:  # eager
        logger.info("Tool registration mode: eager")

        enabled_categories = _parse_filter_list(config.server.get("enabled_categories"))
        enabled_tools = _parse_filter_list(config.server.get("enabled_tools"))

        if enabled_categories:
            logger.info("   Filtering by categories: %s", enabled_categories)
        elif enabled_tools:
            logger.info("   Filtering to %d specific tools", len(enabled_tools))
        else:
            logger.info("   All tools registered (no filtering)")

        auto_load_tools(
            base_package=base_package,
            enabled_categories=enabled_categories,
            enabled_tools=enabled_tools,
            server=server,
        )

    # Log registered tools
    try:
        tools = await server.list_tools()
        logger.debug("Registered tools: %s", [tool.name for tool in tools])
    except Exception as e:
        logger.debug("Error listing tools: %s", e)
