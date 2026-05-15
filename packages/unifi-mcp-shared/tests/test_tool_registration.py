"""Tests for shared tool registration mode dispatch."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from unifi_mcp_shared.tool_registration import register_tools_for_mode


def _config(**server_values):
    defaults = {"enabled_categories": None, "enabled_tools": None}
    defaults.update(server_values)
    return SimpleNamespace(server=defaults)


def _server():
    return SimpleNamespace(list_tools=AsyncMock(return_value=[]))


def _deps():
    return {
        "original_tool_decorator": Mock(),
        "tool_index_handler": Mock(),
        "start_async_tool": Mock(),
        "get_job_status": Mock(),
        "register_tool": Mock(),
        "tool_module_map": {"unifi_list_clients": "unifi_network_mcp.tools.clients"},
        "setup_lazy_loading": Mock(return_value="lazy-loader"),
        "register_meta_tools": Mock(),
        "register_load_tools": Mock(),
        "auto_load_tools": Mock(),
    }


class TestRegisterToolsForMode:
    """Tests for the tool visibility surfaces in each registration mode."""

    @pytest.mark.asyncio
    async def test_lazy_mode_registers_meta_tools_load_tools_and_lazy_loader(self):
        server = _server()
        deps = _deps()

        await register_tools_for_mode(
            mode="lazy",
            server=server,
            base_package="unifi_network_mcp.tools",
            config=_config(),
            logger=logging.getLogger("test"),
            **deps,
        )

        deps["register_meta_tools"].assert_called_once()
        deps["setup_lazy_loading"].assert_called_once_with(server, deps["original_tool_decorator"])
        deps["register_load_tools"].assert_called_once()
        assert deps["register_load_tools"].call_args.kwargs["lazy_loader"] == "lazy-loader"
        deps["auto_load_tools"].assert_not_called()
        server.list_tools.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_meta_only_mode_registers_only_meta_tools_with_lazy_execute_support(self):
        server = _server()
        deps = _deps()

        await register_tools_for_mode(
            mode="meta_only",
            server=server,
            base_package="unifi_network_mcp.tools",
            config=_config(),
            logger=logging.getLogger("test"),
            **deps,
        )

        deps["register_meta_tools"].assert_called_once()
        deps["setup_lazy_loading"].assert_called_once_with(server, deps["original_tool_decorator"])
        deps["register_load_tools"].assert_not_called()
        deps["auto_load_tools"].assert_not_called()
        server.list_tools.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_eager_mode_registers_direct_tools_through_auto_loader(self):
        server = _server()
        deps = _deps()

        await register_tools_for_mode(
            mode="eager",
            server=server,
            base_package="unifi_network_mcp.tools",
            config=_config(enabled_categories="clients,devices"),
            logger=logging.getLogger("test"),
            **deps,
        )

        deps["register_meta_tools"].assert_called_once()
        deps["setup_lazy_loading"].assert_not_called()
        deps["register_load_tools"].assert_not_called()
        deps["auto_load_tools"].assert_called_once_with(
            base_package="unifi_network_mcp.tools",
            enabled_categories=["clients", "devices"],
            enabled_tools=None,
            server=server,
        )
        server.list_tools.assert_awaited_once()
