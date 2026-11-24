# ruff: noqa: E402
"""Main entry-point for the UniFi Drive MCP server.

The server starts without contacting the NAS: the first tool call logs in.
"""

from unifi_drive_mcp.bootstrap import (
    UNIFI_TOOL_REGISTRATION_MODE,
    logger,
)  # ensures logging/env setup early
from unifi_drive_mcp.categories import DRIVE_CATEGORY_MAP, TOOL_MODULE_MAP, policy_gates, setup_lazy_loading
from unifi_drive_mcp.jobs import get_job_status, start_async_tool
from unifi_drive_mcp.runtime import config, connection_manager, get_operation_gate, server
from unifi_drive_mcp.tool_index import register_tool, tool_index_handler
from unifi_drive_mcp.utils.diagnostics import diagnostics_enabled, wrap_tool
from unifi_mcp_shared.permissioned_tool import setup_permissioned_tool

# --- Permission system setup (module-level, before any tool imports) ---

_original_tool_decorator = getattr(server, "_original_tool", server.tool)

setup_permissioned_tool(
    server=server,
    category_map=DRIVE_CATEGORY_MAP,
    server_prefix="drive",
    register_tool_fn=register_tool,
    diagnostics_enabled_fn=diagnostics_enabled,
    wrap_tool_fn=wrap_tool,
    logger=logger,
    # Reads capped per NAS; writes, when they come, one at a time in request order.
    # No connection_decorator: there is no connection wait, the first tool call logs in from inside the gate.
    gate_provider=get_operation_gate,
)


async def main_async():
    """Set up and run the server."""
    from unifi_core.policy_gate import check_deprecated_env_vars, check_unknown_policy_env_vars
    from unifi_mcp_shared.server_lifecycle import apply_log_level, install_asyncio_exception_handler
    from unifi_mcp_shared.setup_required import controller_host_configured, serve_setup_required
    from unifi_mcp_shared.tool_registration import register_tools_for_mode
    from unifi_mcp_shared.tracing import configure_tracing
    from unifi_mcp_shared.transport import resolve_http_auth_token, resolve_http_config, run_transports

    install_asyncio_exception_handler(logger)
    apply_log_level(config, "unifi-drive-mcp")
    configure_tracing("unifi-drive-mcp", logger=logger)
    check_deprecated_env_vars("drive", logger)
    check_unknown_policy_env_vars("drive", logger, policy_gates(), DRIVE_CATEGORY_MAP)
    if not controller_host_configured(config):
        # Answer initialize and explain setup instead of exiting; register no
        # Drive tools and open no connection.
        await serve_setup_required(
            server=server,
            config=config,
            plugin_name="unifi-drive",
            env_prefix="DRIVE",
            tool_prefix="drive",
            default_port=3004,
            logger=logger,
        )
        return

    try:
        # No startup login: the first tool call makes the first request, so the
        # server answers initialize without waiting on the NAS.
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
            base_package="unifi_drive_mcp.tools",
            config=config,
            logger=logger,
            prefix="drive",
            server_label="UniFi Drive",
        )

        http_enabled, http_transport, host, port = resolve_http_config(config.server, default_port=3004, logger=logger)
        await run_transports(
            server=server,
            http_enabled=http_enabled,
            host=host,
            port=port,
            http_transport=http_transport,
            logger=logger,
            auth_token=resolve_http_auth_token(
                env_prefix="DRIVE", logger=logger, configured=config.server.get("http", {}).get("auth_token")
            )
            if http_enabled
            else None,
        )
    finally:
        await connection_manager.close()


def main():
    """Synchronous entry point."""
    from unifi_mcp_shared.server_lifecycle import run_main

    run_main(main_async, logger=logger)


from unifi_mcp_shared.server_lifecycle import register_main_module

register_main_module("unifi_drive_mcp.main")

if __name__ == "__main__":
    main()
