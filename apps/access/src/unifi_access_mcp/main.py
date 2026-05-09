# ruff: noqa: E402
"""Main entry-point for the UniFi-Access MCP server.

Responsibilities:
- configure permissions wrappers
- initialise UniFi Access connection
- start FastMCP (stdio)
"""

from unifi_access_mcp.bootstrap import (
    UNIFI_TOOL_REGISTRATION_MODE,
    logger,
)  # ensures logging/env setup early
from unifi_access_mcp.categories import ACCESS_CATEGORY_MAP, TOOL_MODULE_MAP, setup_lazy_loading
from unifi_access_mcp.jobs import get_job_status, start_async_tool

# Shared singletons
from unifi_access_mcp.runtime import (
    config,
    connection_manager,
    event_manager,
    server,
)
from unifi_access_mcp.tool_index import register_tool, tool_index_handler
from unifi_access_mcp.utils.config_helpers import parse_config_bool
from unifi_access_mcp.utils.diagnostics import diagnostics_enabled, wrap_tool
from unifi_mcp_shared.permissioned_tool import setup_permissioned_tool

# --- Permission system setup (module-level, before any tool imports) ---

_original_tool_decorator = getattr(server, "_original_tool", server.tool)

setup_permissioned_tool(
    server=server,
    category_map=ACCESS_CATEGORY_MAP,
    server_prefix="access",
    register_tool_fn=register_tool,
    diagnostics_enabled_fn=diagnostics_enabled,
    wrap_tool_fn=wrap_tool,
    logger=logger,
)

logger.debug("Access MCP server module loaded; singletons initialised.")


async def main_async():
    """Main asynchronous function to setup and run the server."""
    from unifi_core.policy_gate import check_deprecated_env_vars
    from unifi_mcp_shared.bootstrap import assert_credentials_configured
    from unifi_mcp_shared.server_lifecycle import apply_log_level, install_asyncio_exception_handler
    from unifi_mcp_shared.tool_registration import register_tools_for_mode
    from unifi_mcp_shared.transport import resolve_http_config, run_transports

    install_asyncio_exception_handler(logger)
    apply_log_level(config, "unifi-access-mcp")
    check_deprecated_env_vars("access", logger)
    assert_credentials_configured(config, plugin_name="unifi-access", env_prefix="ACCESS", logger=logger)

    # Initialize the global Access connection
    logger.info("Initializing global Access connection from main_async...")
    if not await connection_manager.initialize():
        logger.error("Failed to connect to UniFi Access. Tool functionality may be impaired.")
    else:
        logger.info("Global Access connection initialized successfully from main_async.")

        # Start the websocket event listener if enabled and connection succeeded
        ws_enabled_raw = config.access.events.get("websocket_enabled", True) if hasattr(config, "access") else True
        ws_enabled = parse_config_bool(ws_enabled_raw)
        if ws_enabled:
            try:
                event_manager.set_server(server)
                # TODO: Implement websocket event listening for Access
                logger.info("Access event websocket listener not yet implemented.")
            except Exception as ws_exc:
                logger.error(
                    "Failed to start event websocket listener: %s. "
                    "Real-time events will be unavailable; REST queries still work.",
                    ws_exc,
                    exc_info=True,
                )
        else:
            logger.info("Access event websocket disabled via config.")

    # ---- Register MCP resources ----
    try:
        import unifi_access_mcp.resources.events  # noqa: F401

        logger.info("MCP resources registered (events).")
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
        base_package="unifi_access_mcp.tools",
        config=config,
        logger=logger,
        prefix="access",
        server_label="UniFi Access",
    )

    # ---- Start transports ----
    http_enabled, http_transport, host, port = resolve_http_config(config.server, default_port=3002, logger=logger)
    await run_transports(
        server=server,
        http_enabled=http_enabled,
        host=host,
        port=port,
        http_transport=http_transport,
        logger=logger,
    )


def main():
    """Synchronous entry point."""
    from unifi_mcp_shared.server_lifecycle import run_main

    run_main(main_async, logger=logger)


from unifi_mcp_shared.server_lifecycle import register_main_module

register_main_module("unifi_access_mcp.main")

if __name__ == "__main__":
    main()
