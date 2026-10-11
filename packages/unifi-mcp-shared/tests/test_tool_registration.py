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
        "support_bundle_handler": AsyncMock(return_value={"success": True, "data": {}}),
        "tool_module_map": {"unifi_list_clients": "unifi_network_mcp.tools.clients"},
        "setup_lazy_loading": Mock(return_value="lazy-loader"),
        "register_meta_tools": Mock(),
        "register_load_tools": Mock(),
        "auto_load_tools": Mock(return_value=None),
    }


class TestRegisterToolsForMode:
    """Tests for the tool visibility surfaces in each registration mode."""

    @pytest.mark.parametrize("mode", ["lazy", "meta_only", "eager"])
    async def test_legacy_apps_can_omit_support_handler(self, mode, caplog):
        deps = _deps()
        deps.pop("support_bundle_handler")
        with caplog.at_level("INFO"):
            await register_tools_for_mode(
                mode=mode,
                server=_server(),
                base_package="unifi_network_mcp.tools",
                config=_config(),
                logger=logging.getLogger("test"),
                **deps,
            )
        assert "support_bundle_handler" not in deps["register_meta_tools"].call_args.kwargs
        assert "get_support_bundle" not in caplog.text

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
        assert deps["register_meta_tools"].call_args.kwargs["support_bundle_handler"] is deps["support_bundle_handler"]
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
        assert deps["register_meta_tools"].call_args.kwargs["support_bundle_handler"] is deps["support_bundle_handler"]
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
        assert deps["register_meta_tools"].call_args.kwargs["support_bundle_handler"] is deps["support_bundle_handler"]
        deps["setup_lazy_loading"].assert_not_called()
        deps["register_load_tools"].assert_not_called()
        deps["auto_load_tools"].assert_called_once_with(
            base_package="unifi_network_mcp.tools",
            enabled_categories=["clients", "devices"],
            enabled_tools=None,
            server=server,
        )
        server.list_tools.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_eager_mode_can_omit_indirect_meta_tools(self):
        server = _server()
        deps = _deps()

        await register_tools_for_mode(
            mode="eager",
            server=server,
            base_package="unifi_network_mcp.tools",
            config=_config(enabled_tools="unifi_get_system_info"),
            logger=logging.getLogger("test"),
            include_meta_tools=False,
            **deps,
        )

        deps["register_meta_tools"].assert_not_called()
        deps["auto_load_tools"].assert_called_once()

    @pytest.mark.asyncio
    async def test_eager_mode_cannot_omit_meta_tools_without_an_allowlist(self):
        deps = _deps()

        with pytest.raises(ValueError, match="requires enabled_categories or enabled_tools"):
            await register_tools_for_mode(
                mode="eager",
                server=_server(),
                base_package="unifi_network_mcp.tools",
                config=_config(),
                logger=logging.getLogger("test"),
                include_meta_tools=False,
                **deps,
            )

        deps["register_meta_tools"].assert_not_called()
        deps["auto_load_tools"].assert_not_called()

    @pytest.mark.asyncio
    async def test_eager_mode_awaits_enabled_tool_filtering(self):
        server = _server()
        deps = _deps()
        filtering = AsyncMock()
        deps["auto_load_tools"] = Mock(return_value=filtering())

        await register_tools_for_mode(
            mode="eager",
            server=server,
            base_package="unifi_network_mcp.tools",
            config=_config(enabled_tools="unifi_get_system_info"),
            logger=logging.getLogger("test"),
            **deps,
        )

        filtering.assert_awaited_once()


class _ModuleLoader:
    """Stands in for LazyToolLoader: loading a tool registers every tool its module holds."""

    def __init__(self, server, modules: dict[str, list[tuple[str, bool]]]):
        self.server = server
        self.modules = modules
        self.loaded: list[str] = []

    async def load_tool(self, name: str) -> bool:
        for module_tools in self.modules.values():
            if name in {tool for tool, _ in module_tools}:
                for tool, read_only in module_tools:
                    if tool not in self.loaded:
                        self.loaded.append(tool)
                        self._register(tool, read_only)
                return True
        return False

    def _register(self, name: str, read_only: bool) -> None:
        from mcp.types import ToolAnnotations

        async def handler() -> dict:
            return {"success": True}

        self.server.tool(name=name, annotations=ToolAnnotations(readOnlyHint=read_only, openWorldHint=False))(handler)


class TestLazyDirectTools:
    """Lazy mode can list chosen read-only tools so read-only clients reach them without *_execute."""

    def _real_server(self):
        from unifi_mcp_shared.strict_dispatch import StrictKwargFastMCP

        return StrictKwargFastMCP("lazy-direct-test")

    async def _register(self, mode, server, loader, direct):
        deps = _deps()
        deps["setup_lazy_loading"] = Mock(return_value=loader)
        await register_tools_for_mode(
            mode=mode,
            server=server,
            base_package="unifi_network_mcp.tools",
            config=_config(),
            logger=logging.getLogger("test"),
            lazy_direct_tools=direct,
            **deps,
        )

    @pytest.mark.asyncio
    async def test_lazy_mode_lists_direct_read_only_tools_with_their_annotations(self):
        server = self._real_server()
        loader = _ModuleLoader(server, {"evidence": [("unifi_get_incident_evidence", True)]})
        await self._register("lazy", server, loader, ("unifi_get_incident_evidence",))
        listed = {tool.name: tool for tool in await server.list_tools()}
        assert listed["unifi_get_incident_evidence"].annotations.read_only_hint is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["meta_only", "eager"])
    async def test_other_modes_ignore_direct_tools(self, mode):
        server = self._real_server()
        loader = _ModuleLoader(server, {"evidence": [("unifi_get_incident_evidence", True)]})
        await self._register(mode, server, loader, ("unifi_get_incident_evidence",))
        assert loader.loaded == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("modules", "problem"),
        [
            ({"evidence": [("unifi_get_incident_evidence", False)]}, "is not read-only"),
            (
                {"events": [("unifi_get_incident_evidence", True), ("unifi_archive_alarm", False)]},
                "unifi_archive_alarm was registered alongside them",
            ),
            ({}, "could not be loaded"),
        ],
    )
    async def test_direct_tools_must_be_read_only_and_alone_in_their_module(self, modules, problem):
        server = self._real_server()
        loader = _ModuleLoader(server, modules)
        with pytest.raises(ValueError, match=problem):
            await self._register("lazy", server, loader, ("unifi_get_incident_evidence",))
