# ruff: noqa: E402
"""Main entry-point for the UniFi InnerSpace MCP server.

Responsibilities:
- configure permissions wrappers
- start FastMCP and connect to the console in the background
"""

import asyncio
from contextlib import suppress

from unifi_innerspace_mcp.bootstrap import (
    UNIFI_TOOL_REGISTRATION_MODE,
    logger,
)  # ensures logging/env setup early
from unifi_innerspace_mcp.categories import (
    INNERSPACE_CATEGORY_MAP,
    LAZY_DIRECT_TOOLS,
    TOOL_MODULE_MAP,
    policy_gates,
    setup_lazy_loading,
)
from unifi_innerspace_mcp.jobs import get_job_status, start_async_tool
from unifi_innerspace_mcp.runtime import config, connection_manager, get_operation_gate, server
from unifi_innerspace_mcp.tool_index import register_tool, tool_index_handler
from unifi_innerspace_mcp.utils.diagnostics import diagnostics_enabled, wrap_tool
from unifi_mcp_shared.permissioned_tool import setup_permissioned_tool

# --- Permission system setup (module-level, before any tool imports) ---

_original_tool_decorator = getattr(server, "_original_tool", server.tool)

setup_permissioned_tool(
    server=server,
    category_map=INNERSPACE_CATEGORY_MAP,
    server_prefix="innerspace",
    register_tool_fn=register_tool,
    diagnostics_enabled_fn=diagnostics_enabled,
    wrap_tool_fn=wrap_tool,
    logger=logger,
    # Reads capped per console; writes, when they come, one at a time in request order.
    gate_provider=get_operation_gate,
)


async def connect_at_startup() -> bool:
    """Connect to the console in the background while the server answers MCP requests.

    Manager operations wait for this connection within a bound.
    """
    logger.info("Connecting to the UniFi OS console in the background...")
    try:
        connected = await connection_manager.initialize()
    except Exception as exc:
        # Nothing awaits this task's result; a failure must still be reported.
        logger.error("Unexpected error while connecting at startup: %s", type(exc).__name__)
        connected = False
    if not connected:
        logger.error(
            "Failed to connect to the UniFi OS console. Tools report the connection error and try to reconnect on later calls."
        )
        return False
    logger.info("Global InnerSpace connection initialized successfully.")
    return True


async def plan_image_resource_enabled() -> bool:
    """Whether the plan image resources are served: only beside ``innerspace_get_plan_asset``.

    The category and tool filters apply in eager mode only; there, the resource
    follows whether the filtered registration kept that tool.
    """
    if UNIFI_TOOL_REGISTRATION_MODE != "eager":
        return True
    return any(tool.name == "innerspace_get_plan_asset" for tool in await server.list_tools())


async def main_async():
    """Main asynchronous function to setup and run the server."""
    from unifi_core.policy_gate import check_deprecated_env_vars, check_unknown_policy_env_vars
    from unifi_mcp_shared.server_lifecycle import apply_log_level, install_asyncio_exception_handler
    from unifi_mcp_shared.setup_required import controller_host_configured, serve_setup_required
    from unifi_mcp_shared.tool_registration import register_tools_for_mode
    from unifi_mcp_shared.tracing import configure_tracing
    from unifi_mcp_shared.transport import resolve_http_auth_token, resolve_http_config, run_transports

    install_asyncio_exception_handler(logger)
    apply_log_level(config, "unifi-innerspace-mcp")
    configure_tracing("unifi-innerspace-mcp", logger=logger)
    check_deprecated_env_vars("innerspace", logger)
    check_unknown_policy_env_vars("innerspace", logger, policy_gates(), INNERSPACE_CATEGORY_MAP)
    if not controller_host_configured(config):
        # Answer initialize and explain setup instead of exiting; register no
        # controller tools and open no controller connection.
        await serve_setup_required(
            server=server,
            config=config,
            plugin_name="unifi-innerspace",
            env_prefix="INNERSPACE",
            tool_prefix="innerspace",
            default_port=3005,
            logger=logger,
        )
        return

    startup_connect = None
    try:
        # Answer initialize before reaching the console: clients enforce a
        # short startup timeout.
        startup_connect = asyncio.create_task(connect_at_startup(), name="innerspace-startup-connect")

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
            base_package="unifi_innerspace_mcp.tools",
            config=config,
            logger=logger,
            prefix="innerspace",
            server_label="UniFi InnerSpace",
            lazy_direct_tools=LAZY_DIRECT_TOOLS,
        )

        # ---- Register MCP resources ----
        if await plan_image_resource_enabled():
            from unifi_innerspace_mcp.resources.plan_image import register_plan_image_resource

            register_plan_image_resource()
            logger.info("MCP resources registered (plan images).")
        else:
            logger.info("Plan image resource not registered: innerspace_get_plan_asset is filtered out.")

        # ---- Start transports ----
        http_enabled, http_transport, host, port = resolve_http_config(config.server, default_port=3005, logger=logger)
        await run_transports(
            server=server,
            http_enabled=http_enabled,
            host=host,
            port=port,
            http_transport=http_transport,
            logger=logger,
            env_prefix="INNERSPACE",
            auth_token=resolve_http_auth_token(
                env_prefix="INNERSPACE", logger=logger, configured=config.server.get("http", {}).get("auth_token")
            )
            if http_enabled
            else None,
        )
    finally:
        if startup_connect is not None and not startup_connect.done():
            startup_connect.cancel()
            with suppress(asyncio.CancelledError):
                await startup_connect
        try:
            await connection_manager.close()
        except Exception as exc:
            # Logged by class only, and never in place of the error that ended the server.
            logger.error("Failed to close the console connection: %s", type(exc).__name__)


def main():
    """Synchronous entry point."""
    from unifi_mcp_shared.server_lifecycle import run_main

    run_main(main_async, logger=logger)


from unifi_mcp_shared.server_lifecycle import register_main_module

register_main_module("unifi_innerspace_mcp.main")

if __name__ == "__main__":
    main()
