"""Tests for shared tool registration mode dispatch."""

import importlib
import json
import logging
import sys
import uuid
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


_FIXTURE_MODULES = {
    "cameras": """
from mcp.types import ToolAnnotations

from {package}._runtime import server

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)


@server.tool(name="unifi_get_camera", annotations=READ)
async def get_camera(camera_id: str) -> dict:
    return {{"success": True, "data": {{"read": camera_id}}}}


@server.tool(name="unifi_reboot_camera", annotations=WRITE)
async def reboot_camera(camera_id: str) -> dict:
    return {{"success": True, "data": {{"rebooted": camera_id}}}}


@server.tool(name="unifi_list_cameras", annotations=READ)
async def list_cameras() -> dict:
    return {{"success": True, "data": ["cam-1"]}}
""",
    "evidence": """
from mcp.types import ToolAnnotations

from {package}._runtime import server


@server.tool(name="unifi_get_incident_evidence", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def get_incident_evidence() -> dict:
    return {{"success": True, "data": {{}}}}
""",
    # Registers a second tool without going through ``server.tool``.
    "stray": """
from mcp.types import ToolAnnotations

from {package}._runtime import server

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


@server.tool(name="unifi_get_stray", annotations=READ)
async def get_stray() -> dict:
    return {{"success": True, "data": {{}}}}


async def sneaky() -> dict:
    return {{"success": True, "data": {{}}}}


server.add_tool(sneaky, name="unifi_sneaky", annotations=READ)
""",
}
_FIXTURE_TOOLS = {
    "unifi_get_camera": "cameras",
    "unifi_reboot_camera": "cameras",
    "unifi_list_cameras": "cameras",
    "unifi_get_incident_evidence": "evidence",
    "unifi_get_stray": "stray",
    "unifi_sneaky": "stray",
}
_LAZY_META_TOOLS = {"unifi_tool_index", "unifi_execute", "unifi_batch", "unifi_batch_status", "unifi_load_tools"}


@pytest.fixture
def tool_package(tmp_path, monkeypatch):
    """A throwaway tool package whose modules register with ``server.tool`` on import, as app tool modules do."""
    package = f"lazy_direct_fixture_{uuid.uuid4().hex}"
    root = tmp_path / package
    root.mkdir()
    (root / "__init__.py").write_text("")
    (root / "_runtime.py").write_text("server = None\n")
    for module, source in _FIXTURE_MODULES.items():
        (root / f"{module}.py").write_text(source.format(package=package))
    monkeypatch.syspath_prepend(str(tmp_path))
    yield package
    for name in [name for name in sys.modules if name == package or name.startswith(f"{package}.")]:
        del sys.modules[name]


async def _start(package: str, directory, mode: str, direct: tuple[str, ...]):
    """Run the real registration dispatch against the fixture package; return the server."""
    from unifi_mcp_shared.lazy_tools import setup_lazy_loading
    from unifi_mcp_shared.strict_dispatch import StrictKwargFastMCP
    from unifi_mcp_shared.tool_index import get_tool_index

    server = StrictKwargFastMCP("lazy-direct-test")
    importlib.import_module(f"{package}._runtime").server = server
    module_map = {name: f"{package}.{module}" for name, module in _FIXTURE_TOOLS.items()}
    manifest = directory / "tools_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "count": len(module_map),
                "module_map": module_map,
                "tools": [{"name": name, "description": f"Fixture {name}"} for name in module_map],
            }
        )
    )

    async def tool_index(args=None):
        return get_tool_index(registration_mode="lazy", manifest_path=manifest, **(args or {}))

    await register_tools_for_mode(
        mode=mode,
        server=server,
        original_tool_decorator=server.tool,
        tool_index_handler=tool_index,
        start_async_tool=Mock(),
        get_job_status=Mock(),
        register_tool=Mock(),
        tool_module_map=module_map,
        setup_lazy_loading=lambda srv, decorator: setup_lazy_loading(srv, decorator, module_map),
        base_package=package,
        config=_config(),
        logger=logging.getLogger("test"),
        auto_load_tools=Mock(return_value=None),
        lazy_direct_tools=direct,
    )
    return server


async def _call(server, name: str, arguments: dict) -> dict:
    from unifi_mcp_shared.response_serialization import normalize_call_tool_result

    result = normalize_call_tool_result(await server.call_tool(name, arguments))
    if isinstance(result, dict):
        return result
    return json.loads(result[0].text)


class TestLazyDirectTools:
    """Lazy mode lists chosen read-only tools so read-only clients reach them without *_execute."""

    DIRECT = ("unifi_get_incident_evidence", "unifi_get_camera")

    @pytest.mark.asyncio
    async def test_lists_only_the_named_tools_even_beside_other_tools_in_their_module(self, tool_package, tmp_path):
        server = await _start(tool_package, tmp_path, "lazy", self.DIRECT)
        listed = {tool.name: tool for tool in await server.list_tools()}
        assert set(listed) == _LAZY_META_TOOLS | set(self.DIRECT)
        assert all(listed[name].annotations.read_only_hint is True for name in self.DIRECT)

    @pytest.mark.asyncio
    async def test_a_listed_tool_runs_directly_and_through_execute(self, tool_package, tmp_path):
        server = await _start(tool_package, tmp_path, "lazy", self.DIRECT)
        assert await _call(server, "unifi_get_camera", {"camera_id": "cam-1"}) == {
            "success": True,
            "data": {"read": "cam-1"},
        }
        executed = await _call(
            server, "unifi_execute", {"tool": "unifi_get_camera", "arguments": {"camera_id": "cam-1"}}
        )
        assert executed == {"success": True, "data": {"read": "cam-1"}}

    @pytest.mark.asyncio
    async def test_module_siblings_still_run_through_execute(self, tool_package, tmp_path):
        server = await _start(tool_package, tmp_path, "lazy", self.DIRECT)
        rebooted = await _call(
            server, "unifi_execute", {"tool": "unifi_reboot_camera", "arguments": {"camera_id": "cam-1"}}
        )
        assert rebooted == {"success": True, "data": {"rebooted": "cam-1"}}
        listed = await _call(server, "unifi_execute", {"tool": "unifi_list_cameras", "arguments": {}})
        assert listed == {"success": True, "data": ["cam-1"]}
        # As before, a tool runs once it is registered; nothing else was registered with it.
        names = {tool.name for tool in await server.list_tools()}
        assert names == _LAZY_META_TOOLS | set(self.DIRECT) | {"unifi_reboot_camera", "unifi_list_cameras"}

    @pytest.mark.asyncio
    async def test_the_index_still_lists_the_listed_tool_and_its_siblings(self, tool_package, tmp_path):
        server = await _start(tool_package, tmp_path, "lazy", self.DIRECT)
        index = await _call(server, "unifi_tool_index", {})
        assert {"unifi_get_camera", "unifi_reboot_camera", "unifi_list_cameras"} <= {
            tool["name"] for tool in index["tools"]
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["meta_only", "eager"])
    async def test_other_modes_ignore_direct_tools(self, tool_package, tmp_path, mode):
        server = await _start(tool_package, tmp_path, mode, self.DIRECT)
        assert not {tool.name for tool in await server.list_tools()} & set(_FIXTURE_TOOLS)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("direct", "problem"),
        [
            (("unifi_reboot_camera",), "unifi_reboot_camera is not read-only"),
            (("unifi_get_nothing",), "'unifi_get_nothing' could not be loaded"),
            (("unifi_get_stray",), "unifi_sneaky was registered alongside them"),
        ],
    )
    async def test_startup_is_refused_for_a_write_an_unknown_name_or_an_unnamed_registration(
        self, tool_package, tmp_path, direct, problem
    ):
        with pytest.raises(ValueError, match=problem):
            await _start(tool_package, tmp_path, "lazy", direct)
