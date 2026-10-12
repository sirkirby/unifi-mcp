# ruff: noqa: E402
"""Main entry‑point for the UniFi‑Network MCP server.

Responsibilities:
• configure permissions wrappers
• start FastMCP (stdio) and connect to the controller in the background
"""

import asyncio
from contextlib import suppress

from unifi_core.policy_gate import PolicyGateChecker
from unifi_mcp_shared.permissioned_tool import create_permissioned_tool
from unifi_network_mcp.bootstrap import (
    UNIFI_TOOL_REGISTRATION_MODE,
    logger,
)  # ensures logging/env setup early
from unifi_network_mcp.categories import NETWORK_CATEGORY_MAP, TOOL_MODULE_MAP, policy_gates, setup_lazy_loading
from unifi_network_mcp.jobs import get_job_status, start_async_tool
from unifi_network_mcp.reconnect import reconnecting_tool_decorator

# Shared singletons
from unifi_network_mcp.runtime import (
    config,
    connection_manager,
    event_manager,
    server,
    support_bundle_service,
)
from unifi_network_mcp.tool_index import register_tool, tool_index_handler
from unifi_network_mcp.utils.diagnostics import diagnostics_enabled, wrap_tool

# --- Permission system setup (module-level, before any tool imports) ---

_original_tool_decorator = getattr(server, "_original_tool", server.tool)

# Domain tools wait for the controller connection, within a bound, before they
# run. Meta-tools register with the plain decorator: discovery never contacts
# the controller.
server.tool = create_permissioned_tool(
    original_tool_decorator=reconnecting_tool_decorator(_original_tool_decorator, connection_manager),
    policy_gate_checker=PolicyGateChecker(server_prefix="network", category_map=NETWORK_CATEGORY_MAP),
    server_prefix="network",
    register_tool_fn=register_tool,
    diagnostics_enabled_fn=diagnostics_enabled,
    wrap_tool_fn=wrap_tool,
    logger=logger,
)

logger.info("Loaded configuration globally.")
logger.info("Using global ConnectionManager instance.")
logger.info("Using global Manager instances.")


async def start_event_listener_if_enabled(*, config, connection_manager, event_manager) -> bool:
    """Start the websocket event listener whenever it is enabled (#680).

    Startup must not depend on the boot connect succeeding: the listener owns
    the backoff/reconnect loop, which treats "not connected" as a normal
    state. The websocket still requires configured session credentials; an
    API-key-only process and an active API-key fallback must not start it.
    Returns True when listening was started.
    """
    from unifi_core.config_helpers import parse_config_bool

    # It feeds unifi_recent_events; without it that buffer can never fill.
    ws_enabled_raw = config.network.events.get("websocket_enabled", True) if hasattr(config, "network") else True
    if not parse_config_bool(ws_enabled_raw, default=True):
        logger.info("Network event websocket disabled by config.")
        return False
    auth_status = connection_manager.authentication_status
    if not auth_status.session_configured:
        logger.info("Network event websocket unavailable without session credentials.")
        return False
    if auth_status.api_key_available:
        logger.info("Network event websocket unavailable while the API-key fallback is active.")
        return False
    try:
        await event_manager.start_listening()
    except Exception as ws_exc:
        logger.error(
            "Failed to start event websocket listener: %s. "
            "Real-time events will be unavailable; unifi_list_events still works.",
            type(ws_exc).__name__,
        )
        return False
    return True


async def connect_controller_at_startup(*, config, connection_manager, event_manager) -> bool:
    """Connect to the controller in the background, then start the event listener.

    The server answers MCP requests meanwhile; tool calls wait for this
    connection within a bound. Returns True when the connection succeeded.
    """
    logger.info("Connecting to the Unifi controller in the background...")
    try:
        connected = await connection_manager.initialize()
    except Exception as exc:
        # Nothing awaits this task's result; a failure must still be reported.
        logger.error("Unexpected error while connecting at startup: %s", type(exc).__name__)
        connected = False
    if connected:
        logger.info("Global Unifi connection initialized successfully.")
    else:
        logger.error(
            "Failed to connect to the Unifi controller at startup. Tool calls report the connection "
            "error and try to connect again on later calls."
        )
    await start_event_listener_if_enabled(
        config=config,
        connection_manager=connection_manager,
        event_manager=event_manager,
    )
    return connected


async def start_event_listener_after_connection(*, config, connection_manager, event_manager) -> bool:
    """Start events after deferred initialization establishes its first connection."""
    await connection_manager.wait_until_connected()
    return await start_event_listener_if_enabled(
        config=config,
        connection_manager=connection_manager,
        event_manager=event_manager,
    )


async def main_async():
    """Main asynchronous function to setup and run the server."""
    from unifi_core.config_helpers import parse_config_bool
    from unifi_core.policy_gate import check_deprecated_env_vars, check_unknown_policy_env_vars
    from unifi_mcp_shared.server_lifecycle import apply_log_level, install_asyncio_exception_handler
    from unifi_mcp_shared.setup_required import controller_host_configured, serve_setup_required
    from unifi_mcp_shared.tool_registration import register_tools_for_mode
    from unifi_mcp_shared.transport import resolve_http_config, run_transports

    install_asyncio_exception_handler(logger)
    apply_log_level(config, "unifi-network-mcp")
    check_deprecated_env_vars("network", logger)
    check_unknown_policy_env_vars("network", logger, policy_gates(), NETWORK_CATEGORY_MAP)
    if not controller_host_configured(config):
        # Answer initialize and explain setup instead of exiting; register no
        # controller tools and open no controller connection.
        await serve_setup_required(
            server=server,
            config=config,
            plugin_name="unifi-network",
            env_prefix="NETWORK",
            tool_prefix="unifi",
            default_port=3000,
            logger=logger,
        )
        return

    background_task = None
    try:
        # Local MCP clients enforce a short startup timeout, so the server
        # answers initialize before it reaches the controller: the connection
        # is made in the background, and tool calls wait for it within a bound.
        # Confined stdio deployments can defer controller I/O entirely until
        # the first tool call.
        defer_controller_init = parse_config_bool(config.server.get("defer_controller_init", False))
        if defer_controller_init:
            logger.info("Deferring controller initialization until the first tool call")
            background_task = asyncio.create_task(
                start_event_listener_after_connection(
                    config=config,
                    connection_manager=connection_manager,
                    event_manager=event_manager,
                ),
                name="network-deferred-event-listener",
            )
        else:
            background_task = asyncio.create_task(
                connect_controller_at_startup(
                    config=config,
                    connection_manager=connection_manager,
                    event_manager=event_manager,
                ),
                name="network-startup-connect",
            )

        # ---- Register tools ----
        await register_tools_for_mode(
            mode=UNIFI_TOOL_REGISTRATION_MODE,
            server=server,
            original_tool_decorator=_original_tool_decorator,
            tool_index_handler=tool_index_handler,
            start_async_tool=start_async_tool,
            get_job_status=get_job_status,
            register_tool=register_tool,
            tool_module_map=TOOL_MODULE_MAP,
            setup_lazy_loading=setup_lazy_loading,
            base_package="unifi_network_mcp.tools",
            config=config,
            logger=logger,
            support_bundle_handler=support_bundle_service.generate,
            include_meta_tools=parse_config_bool(config.server.get("meta_tools_enabled", True), default=True),
        )

        # ---- Start transports ----
        http_enabled, http_transport, host, port = resolve_http_config(config.server, default_port=3000, logger=logger)
        await run_transports(
            server=server,
            http_enabled=http_enabled,
            host=host,
            port=port,
            http_transport=http_transport,
            logger=logger,
        )
    finally:
        if background_task is not None and not background_task.done():
            background_task.cancel()
            with suppress(asyncio.CancelledError):
                await background_task
        try:
            await event_manager.stop_listening()
        finally:
            await connection_manager.cleanup()


def main():
    """Synchronous entry point."""
    from unifi_mcp_shared.server_lifecycle import run_main

    run_main(main_async, logger=logger)


from unifi_mcp_shared.server_lifecycle import register_main_module

register_main_module("unifi_network_mcp.main")

if __name__ == "__main__":
    main()
