# ruff: noqa: E402
"""Main entry‑point for the UniFi‑Network MCP server.

Responsibilities:
• configure permissions wrappers
• initialise UniFi connection
• start FastMCP (stdio)
"""

from unifi_mcp_shared.permissioned_tool import setup_permissioned_tool
from unifi_network_mcp.bootstrap import (
    UNIFI_TOOL_REGISTRATION_MODE,
    logger,
)  # ensures logging/env setup early
from unifi_network_mcp.categories import NETWORK_CATEGORY_MAP, TOOL_MODULE_MAP, setup_lazy_loading
from unifi_network_mcp.jobs import get_job_status, start_async_tool

# Shared singletons
from unifi_network_mcp.runtime import (
    config,
    connection_manager,
    server,
)
from unifi_network_mcp.tool_index import register_tool, tool_index_handler
from unifi_network_mcp.utils.diagnostics import diagnostics_enabled, wrap_tool

# --- Permission system setup (module-level, before any tool imports) ---

_original_tool_decorator = getattr(server, "_original_tool", server.tool)

setup_permissioned_tool(
    server=server,
    category_map=NETWORK_CATEGORY_MAP,
    server_prefix="network",
    register_tool_fn=register_tool,
    diagnostics_enabled_fn=diagnostics_enabled,
    wrap_tool_fn=wrap_tool,
    logger=logger,
)

logger.info("Loaded configuration globally.")
logger.info("Using global ConnectionManager instance.")
logger.info("Using global Manager instances.")


async def main_async():
    """Main asynchronous function to setup and run the server."""
    from unifi_core.policy_gate import check_deprecated_env_vars
    from unifi_mcp_shared.bootstrap import assert_credentials_configured
    from unifi_mcp_shared.server_lifecycle import apply_log_level, install_asyncio_exception_handler
    from unifi_mcp_shared.tool_registration import register_tools_for_mode
    from unifi_mcp_shared.transport import resolve_http_config, run_transports

    install_asyncio_exception_handler(logger)
    apply_log_level(config, "unifi-network-mcp")
    check_deprecated_env_vars("network", logger)
    assert_credentials_configured(config, plugin_name="unifi-network", env_prefix="NETWORK", logger=logger)

    # Initialize the global Unifi connection
    logger.info("Initializing global Unifi connection from main_async...")
    if not await connection_manager.initialize():
        logger.error("Failed to connect to Unifi Controller from main_async. Tool functionality may be impaired.")
    else:
        logger.info("Global Unifi connection initialized successfully from main_async.")

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


def main():
    """Synchronous entry point."""
    from unifi_mcp_shared.server_lifecycle import run_main

    run_main(main_async, logger=logger)


from unifi_mcp_shared.server_lifecycle import register_main_module

register_main_module("unifi_network_mcp.main")

if __name__ == "__main__":
    main()
