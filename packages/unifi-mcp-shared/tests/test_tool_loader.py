"""Tests for prefix-independent eager tool filtering."""

import importlib
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from unifi_mcp_shared.tool_loader import auto_load_tools

tool_loader_module = importlib.import_module("unifi_mcp_shared.tool_loader")


@pytest.mark.parametrize("prefix", ["unifi", "protect", "access"])
async def test_enabled_tools_preserves_every_prefix_specific_meta_tool(monkeypatch, prefix):
    package = ModuleType("example_tools")
    package.__path__ = []
    names = [
        f"{prefix}_tool_index",
        f"{prefix}_execute",
        f"{prefix}_batch",
        f"{prefix}_batch_status",
        f"{prefix}_load_tools",
        f"{prefix}_get_support_bundle",
        f"{prefix}_list_devices",
        f"{prefix}_delete_device",
    ]
    server = SimpleNamespace(
        list_tools=AsyncMock(),
        remove_tool=Mock(),
    )
    registered = set(names)

    async def list_tools():
        return [SimpleNamespace(name=name) for name in registered]

    server.list_tools.side_effect = list_tools
    server.remove_tool.side_effect = registered.remove
    monkeypatch.setattr(tool_loader_module.importlib, "import_module", lambda _name: package)
    monkeypatch.setattr(tool_loader_module.pkgutil, "walk_packages", lambda *_args: [])

    filtering = auto_load_tools(
        base_package="example_tools",
        enabled_tools=[f"{prefix}_list_devices"],
        server=server,
    )
    assert filtering is not None
    await filtering

    server.remove_tool.assert_called_once_with(f"{prefix}_delete_device")


async def test_enabled_tools_removal_failure_aborts_filtering(monkeypatch):
    package = ModuleType("example_tools")
    package.__path__ = []
    server = SimpleNamespace(
        list_tools=AsyncMock(return_value=[SimpleNamespace(name="unifi_delete_device")]),
        remove_tool=Mock(side_effect=RuntimeError("cannot remove")),
    )
    monkeypatch.setattr(tool_loader_module.importlib, "import_module", lambda _name: package)
    monkeypatch.setattr(tool_loader_module.pkgutil, "walk_packages", lambda *_args: [])

    filtering = auto_load_tools(
        base_package="example_tools",
        enabled_tools=["unifi_list_devices"],
        server=server,
    )
    assert filtering is not None
    with pytest.raises(RuntimeError, match="cannot remove"):
        await filtering
