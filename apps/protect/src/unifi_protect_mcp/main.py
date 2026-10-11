# ruff: noqa: E402
"""Main entry-point for the UniFi-Protect MCP server.

Responsibilities:
- configure permissions wrappers
- start FastMCP (stdio) and connect to UniFi Protect in the background
"""

import asyncio
from contextlib import suppress

from unifi_core.policy_gate import PolicyGateChecker
from unifi_mcp_shared.permissioned_tool import create_permissioned_tool
from unifi_protect_mcp.bootstrap import (
    UNIFI_TOOL_REGISTRATION_MODE,
    logger,
)  # ensures logging/env setup early
from unifi_protect_mcp.categories import (
    LAZY_DIRECT_TOOLS,
    PROTECT_CATEGORY_MAP,
    TOOL_MODULE_MAP,
    policy_gates,
    setup_lazy_loading,
)
from unifi_protect_mcp.jobs import get_job_status, start_async_tool
from unifi_protect_mcp.reconnect import reconnecting_tool_decorator

# Shared singletons
from unifi_protect_mcp.runtime import (
    config,
    connection_manager,
    event_manager,
    server,
    support_bundle_service,
)
from unifi_protect_mcp.tool_index import register_tool, tool_index_handler
from unifi_protect_mcp.utils.config_helpers import parse_config_bool
from unifi_protect_mcp.utils.diagnostics import diagnostics_enabled, wrap_tool

# --- Permission system setup (module-level, before any tool imports) ---

_original_tool_decorator = getattr(server, "_original_tool", server.tool)

# Domain tools reconnect first when the controller was unavailable at start-up.
# Meta-tools register with the plain decorator: discovery never contacts the
# controller.
server.tool = create_permissioned_tool(
    original_tool_decorator=reconnecting_tool_decorator(_original_tool_decorator, connection_manager),
    policy_gate_checker=PolicyGateChecker(server_prefix="protect", category_map=PROTECT_CATEGORY_MAP),
    server_prefix="protect",
    register_tool_fn=register_tool,
    diagnostics_enabled_fn=diagnostics_enabled,
    wrap_tool_fn=wrap_tool,
    logger=logger,
)

logger.info("Loaded configuration globally.")
logger.info("Using global ProtectConnectionManager instance.")
logger.info("Using global Manager instances.")


async def start_event_listener() -> None:
    """Start the event websocket listener when it is enabled.

    Runs after every successful connect, at start-up or on an automatic
    reconnect, so real-time events resume as they would after a normal start.
    """
    ws_enabled_raw = config.protect.events.get("websocket_enabled", True) if hasattr(config, "protect") else True
    if not parse_config_bool(ws_enabled_raw):
        logger.info("Protect event websocket disabled via config.")
        return
    try:
        event_manager.set_server(server)
        await event_manager.start_listening()
        logger.info("Protect event websocket listener started.")
    except Exception as ws_exc:
        logger.error(
            "Failed to start event websocket listener: %s. "
            "Real-time events will be unavailable; REST queries still work.",
            ws_exc,
            exc_info=True,
        )


async def connect_at_startup() -> bool:
    """Connect to UniFi Protect in the background while the server answers MCP requests.

    Domain tools wait for this connection within a bound. The event listener
    starts from the connect hook, here or on a later automatic reconnect.
    """
    logger.info("Connecting to UniFi Protect in the background...")
    try:
        connected = await connection_manager.initialize()
    except Exception as exc:
        # Nothing awaits this task's result; a failure must still be reported.
        logger.error("Unexpected error while connecting at startup: %s", type(exc).__name__)
        connected = False
    if not connected:
        logger.error(
            "Failed to connect to UniFi Protect. Tools report the connection error and try to reconnect on later calls."
        )
        return False
    logger.info("Global Protect connection initialized successfully.")
    return True


async def main_async():
    """Main asynchronous function to setup and run the server."""
    from unifi_core.policy_gate import check_deprecated_env_vars, check_unknown_policy_env_vars
    from unifi_mcp_shared.server_lifecycle import apply_log_level, install_asyncio_exception_handler
    from unifi_mcp_shared.setup_required import controller_host_configured, serve_setup_required
    from unifi_mcp_shared.tool_registration import register_tools_for_mode
    from unifi_mcp_shared.transport import resolve_http_config, run_transports

    install_asyncio_exception_handler(logger)
    apply_log_level(config, "unifi-protect-mcp")
    check_deprecated_env_vars("protect", logger)
    check_unknown_policy_env_vars("protect", logger, policy_gates(), PROTECT_CATEGORY_MAP)
    if not controller_host_configured(config):
        # Answer initialize and explain setup instead of exiting; register no
        # controller tools and open no controller connection.
        await serve_setup_required(
            server=server,
            config=config,
            plugin_name="unifi-protect",
            env_prefix="PROTECT",
            tool_prefix="protect",
            default_port=3001,
            logger=logger,
        )
        return

    startup_connect = None
    try:
        # Answer initialize before reaching the controller: clients enforce a
        # short startup timeout. The event listener starts after this connect,
        # or after a later automatic reconnect.
        connection_manager.add_connect_hook(start_event_listener)
        startup_connect = asyncio.create_task(connect_at_startup(), name="protect-startup-connect")

        # ---- Register MCP resources ----
        try:
            import unifi_protect_mcp.resources.events  # noqa: F401
            import unifi_protect_mcp.resources.snapshots  # noqa: F401

            logger.info("MCP resources registered (events, snapshots).")
        except Exception as res_exc:
            logger.error("Failed to register MCP resources: %s", res_exc, exc_info=True)

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
            base_package="unifi_protect_mcp.tools",
            config=config,
            logger=logger,
            support_bundle_handler=support_bundle_service.generate,
            prefix="protect",
            server_label="UniFi Protect",
            lazy_direct_tools=LAZY_DIRECT_TOOLS,
        )

        # ---- Start transports ----
        http_enabled, http_transport, host, port = resolve_http_config(config.server, default_port=3001, logger=logger)
        await run_transports(
            server=server,
            http_enabled=http_enabled,
            host=host,
            port=port,
            http_transport=http_transport,
            logger=logger,
        )
    finally:
        if startup_connect is not None and not startup_connect.done():
            startup_connect.cancel()
            with suppress(asyncio.CancelledError):
                await startup_connect
        try:
            await event_manager.stop_listening()
        finally:
            await connection_manager.close()


def main():
    """Synchronous entry point."""
    from unifi_mcp_shared.server_lifecycle import run_main

    run_main(main_async, logger=logger)


from unifi_mcp_shared.server_lifecycle import register_main_module

register_main_module("unifi_protect_mcp.main")

if __name__ == "__main__":
    main()
