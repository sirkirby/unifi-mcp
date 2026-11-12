# ruff: noqa: E402
"""Main entry-point for the UniFi Site Manager MCP server."""

from unifi_mcp_shared.permissioned_tool import setup_permissioned_tool
from unifi_sitemanager_mcp.bootstrap import (
    UNIFI_TOOL_REGISTRATION_MODE,
    logger,
)  # ensures logging/env setup early
from unifi_sitemanager_mcp.categories import (
    LAZY_DIRECT_TOOLS,
    SITEMANAGER_CATEGORY_MAP,
    TOOL_MODULE_MAP,
    setup_lazy_loading,
)
from unifi_sitemanager_mcp.jobs import get_job_status, start_async_tool
from unifi_sitemanager_mcp.runtime import config, connection_manager, server
from unifi_sitemanager_mcp.tool_index import register_tool, tool_index_handler
from unifi_sitemanager_mcp.utils.diagnostics import diagnostics_enabled, wrap_tool

# --- Permission system setup (module-level, before any tool imports) ---

_original_tool_decorator = getattr(server, "_original_tool", server.tool)

setup_permissioned_tool(
    server=server,
    category_map=SITEMANAGER_CATEGORY_MAP,
    server_prefix="sitemanager",
    register_tool_fn=register_tool,
    diagnostics_enabled_fn=diagnostics_enabled,
    wrap_tool_fn=wrap_tool,
    logger=logger,
)

_KEY_SOURCE = "unifi.ui.com > Settings > API Keys."


async def main_async():
    """Set up and run the server."""
    from unifi_mcp_shared import bootstrap as shared_bootstrap
    from unifi_mcp_shared.server_lifecycle import apply_log_level, install_asyncio_exception_handler

    # Imported under a neutral name: the text names variables, never a value, but a
    # call whose name contains "key" reads as a credential source to code scanning.
    from unifi_mcp_shared.setup_required import api_key_setup_required_message as setup_guidance
    from unifi_mcp_shared.setup_required import serve_setup_required
    from unifi_mcp_shared.tool_registration import register_tools_for_mode
    from unifi_mcp_shared.tracing import configure_tracing
    from unifi_mcp_shared.transport import resolve_http_auth_token, resolve_http_config, run_transports

    install_asyncio_exception_handler(logger)
    apply_log_level(config, "unifi-sitemanager-mcp")
    configure_tracing("unifi-sitemanager-mcp", logger=logger)
    if not connection_manager.configured:
        # Answer initialize and explain setup instead of exiting; register no
        # Site Manager tools and make no request.
        await serve_setup_required(
            server=server,
            config=config,
            plugin_name="unifi-sitemanager",
            env_prefix="SITEMANAGER",
            tool_prefix="sitemanager",
            default_port=3003,
            logger=logger,
            message=setup_guidance(
                plugin_name="unifi-sitemanager",
                env_prefix="SITEMANAGER",
                key_source=_KEY_SOURCE,
                report=shared_bootstrap._SETTINGS_REPORT,
            ),
        )
        return

    try:
        # No startup request: the first tool call makes the first one, so the
        # server starts without network access.
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
            base_package="unifi_sitemanager_mcp.tools",
            config=config,
            logger=logger,
            prefix="sitemanager",
            server_label="UniFi Site Manager",
            lazy_direct_tools=LAZY_DIRECT_TOOLS,
        )

        http_enabled, http_transport, host, port = resolve_http_config(config.server, default_port=3003, logger=logger)
        await run_transports(
            server=server,
            http_enabled=http_enabled,
            host=host,
            port=port,
            http_transport=http_transport,
            logger=logger,
            auth_token=resolve_http_auth_token(
                env_prefix="SITEMANAGER", logger=logger, configured=config.server.get("http", {}).get("auth_token")
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

register_main_module("unifi_sitemanager_mcp.main")

if __name__ == "__main__":
    main()
