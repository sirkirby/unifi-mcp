"""Tests for shared meta-tool registration helpers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from unifi_mcp_shared.meta_tools import register_load_tools


def _capture_tools():
    registered = {}

    def tool_decorator(**kwargs):
        def decorator(func):
            registered[kwargs["name"]] = {"handler": func, **kwargs}
            return func

        return decorator

    return registered, tool_decorator


def _context():
    return SimpleNamespace(session=SimpleNamespace(send_tool_list_changed=AsyncMock()))


class TestRegisterLoadTools:
    """Tests for lazy direct-tool loading and list-changed notifications."""

    @pytest.mark.asyncio
    async def test_loaded_tools_send_list_changed_notification(self):
        registered, tool_decorator = _capture_tools()
        lazy_loader = SimpleNamespace(load_tool=AsyncMock(return_value=True))
        register_tool = Mock()

        register_load_tools(
            server=Mock(),
            tool_decorator=tool_decorator,
            lazy_loader=lazy_loader,
            register_tool=register_tool,
            tool_module_map={"unifi_list_clients": "unifi_network_mcp.tools.clients"},
        )

        ctx = _context()
        result = await registered["unifi_load_tools"]["handler"](["unifi_list_clients"], ctx)

        assert result["loaded"] == ["unifi_list_clients"]
        assert result["errors"] is None
        lazy_loader.load_tool.assert_awaited_once_with("unifi_list_clients")
        ctx.session.send_tool_list_changed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_tools_do_not_send_list_changed_notification(self):
        registered, tool_decorator = _capture_tools()
        lazy_loader = SimpleNamespace(load_tool=AsyncMock(return_value=True))

        register_load_tools(
            server=Mock(),
            tool_decorator=tool_decorator,
            lazy_loader=lazy_loader,
            register_tool=Mock(),
            tool_module_map={"unifi_list_clients": "unifi_network_mcp.tools.clients"},
        )

        ctx = _context()
        result = await registered["unifi_load_tools"]["handler"](["unifi_unknown"], ctx)

        assert result["loaded"] == []
        assert result["errors"] == [{"tool": "unifi_unknown", "error": "Unknown tool"}]
        lazy_loader.load_tool.assert_not_awaited()
        ctx.session.send_tool_list_changed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failed_load_does_not_send_list_changed_notification(self):
        registered, tool_decorator = _capture_tools()
        lazy_loader = SimpleNamespace(load_tool=AsyncMock(return_value=False))

        register_load_tools(
            server=Mock(),
            tool_decorator=tool_decorator,
            lazy_loader=lazy_loader,
            register_tool=Mock(),
            tool_module_map={"unifi_list_clients": "unifi_network_mcp.tools.clients"},
        )

        ctx = _context()
        result = await registered["unifi_load_tools"]["handler"](["unifi_list_clients"], ctx)

        assert result["loaded"] == []
        assert result["errors"] == [{"tool": "unifi_list_clients", "error": "Failed to load"}]
        ctx.session.send_tool_list_changed.assert_not_awaited()

    def test_load_tools_description_uses_standard_notification_name(self):
        registered, tool_decorator = _capture_tools()

        register_load_tools(
            server=Mock(),
            tool_decorator=tool_decorator,
            lazy_loader=SimpleNamespace(load_tool=AsyncMock(return_value=True)),
            register_tool=Mock(),
            tool_module_map={"unifi_list_clients": "unifi_network_mcp.tools.clients"},
        )

        description = registered["unifi_load_tools"]["description"]
        assert "tools/list" in description
        assert "notifications/tools/list_changed" in description
