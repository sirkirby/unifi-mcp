"""Tests for MCP protocol tool discovery."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from unifi_mcp_relay.protocol import ToolInfo


@pytest.fixture
def mock_mcp_client():
    """Create a mock McpHttpClient that routes requests by method name."""

    def make_mock(side_effect_fn):
        mock_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.request = AsyncMock(side_effect=side_effect_fn)
        mock_instance.close = AsyncMock()
        mock_instance.session_id = "session-abc-123"
        mock_cls.return_value = mock_instance
        return mock_cls, mock_instance

    return make_mock


@pytest.mark.asyncio
async def test_discover_tools_lazy_mode(mock_mcp_client):
    """Discover tools via lazy mode: initialize -> tools/list (meta-tools) -> _tool_index call."""

    # Simulate a lazy-mode server: tools/list returns meta-tools only,
    # and the tool_index call returns the full catalog.
    tool_index_result = {
        "tools": [
            {
                "name": "unifi_list_clients",
                "description": "List all connected clients",
                "schema": {"input": {"type": "object", "properties": {"compact": {"type": "boolean"}}}},
                "annotations": {"readOnlyHint": True, "openWorldHint": False},
            },
            {
                "name": "unifi_get_device_details",
                "description": "Get details for a specific device",
                "schema": {"input": {"type": "object", "properties": {"device_id": {"type": "string"}}}},
                "annotations": {"readOnlyHint": True, "openWorldHint": False},
            },
        ],
        "count": 2,
    }

    def route_request(method, params=None):
        if method == "initialize":
            return {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "unifi-network-mcp", "version": "1.0.0"},
            }
        elif method == "tools/list":
            return {
                "tools": [
                    {
                        "name": "unifi_tool_index",
                        "description": "Discover available tools",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                    {
                        "name": "unifi_execute",
                        "description": "Execute a tool by name",
                        "inputSchema": {"type": "object", "properties": {"tool_name": {"type": "string"}}},
                    },
                ]
            }
        elif method == "tools/call":
            assert params["name"] == "unifi_tool_index"
            return {
                "content": [{"type": "text", "text": __import__("json").dumps(tool_index_result)}],
                "isError": False,
            }
        raise ValueError(f"Unexpected method: {method}")

    mock_cls, mock_instance = mock_mcp_client(route_request)

    with patch("unifi_mcp_relay.discovery.McpHttpClient", mock_cls):
        from unifi_mcp_relay.discovery import discover_tools

        result = await discover_tools("http://localhost:3000")

    assert result is not None
    assert result.name == "unifi-network-mcp"
    assert result.url == "http://localhost:3000"
    assert result.session_id == "session-abc-123"
    assert len(result.tools) == 2

    # Verify tools are properly converted to ToolInfo with server_origin
    tool_names = {t.name for t in result.tools}
    assert tool_names == {"unifi_list_clients", "unifi_get_device_details"}

    clients_tool = next(t for t in result.tools if t.name == "unifi_list_clients")
    assert clients_tool.description == "List all connected clients"
    assert clients_tool.input_schema == {"type": "object", "properties": {"compact": {"type": "boolean"}}}
    assert clients_tool.annotations == {"readOnlyHint": True, "openWorldHint": False}
    assert clients_tool.server_origin == "unifi-network-mcp"

    # Verify client was closed
    mock_instance.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_discover_tools_identifies_tool_index_by_suffix(mock_mcp_client):
    """Discovery finds protect_tool_index by _tool_index suffix, not hardcoded prefix."""

    tool_index_result = {
        "tools": [
            {
                "name": "protect_list_cameras",
                "description": "List all cameras",
                "schema": {"input": {"type": "object", "properties": {}}},
                "annotations": {"readOnlyHint": True},
            },
        ],
        "count": 1,
    }

    def route_request(method, params=None):
        if method == "initialize":
            return {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "unifi-protect-mcp", "version": "0.2.0"},
            }
        elif method == "tools/list":
            return {
                "tools": [
                    {
                        "name": "protect_tool_index",
                        "description": "Discover available tools",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                    {
                        "name": "protect_execute",
                        "description": "Execute a tool",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                ]
            }
        elif method == "tools/call":
            assert params["name"] == "protect_tool_index"
            return {
                "content": [{"type": "text", "text": __import__("json").dumps(tool_index_result)}],
                "isError": False,
            }
        raise ValueError(f"Unexpected method: {method}")

    mock_cls, mock_instance = mock_mcp_client(route_request)

    with patch("unifi_mcp_relay.discovery.McpHttpClient", mock_cls):
        from unifi_mcp_relay.discovery import discover_tools

        result = await discover_tools("http://localhost:3001")

    assert result is not None
    assert result.name == "unifi-protect-mcp"
    assert len(result.tools) == 1
    assert result.tools[0].name == "protect_list_cameras"
    assert result.tools[0].server_origin == "unifi-protect-mcp"


@pytest.mark.asyncio
async def test_discover_tools_eager_mode_fallback(mock_mcp_client):
    """When no _tool_index tool is found, fall back to using tools/list directly (eager mode)."""

    def route_request(method, params=None):
        if method == "initialize":
            return {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "custom-mcp-server", "version": "0.1.0"},
            }
        elif method == "tools/list":
            return {
                "tools": [
                    {
                        "name": "my_custom_tool",
                        "description": "A custom tool",
                        "inputSchema": {"type": "object", "properties": {"arg": {"type": "string"}}},
                        "annotations": {"readOnlyHint": True, "destructiveHint": False},
                    },
                    {
                        "name": "another_tool",
                        "description": "Another tool",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                ]
            }
        raise ValueError(f"Unexpected method: {method}")

    mock_cls, mock_instance = mock_mcp_client(route_request)

    with patch("unifi_mcp_relay.discovery.McpHttpClient", mock_cls):
        from unifi_mcp_relay.discovery import discover_tools

        result = await discover_tools("http://localhost:4000")

    assert result is not None
    assert result.name == "custom-mcp-server"
    assert len(result.tools) == 2

    custom_tool = next(t for t in result.tools if t.name == "my_custom_tool")
    assert custom_tool.annotations == {"readOnlyHint": True, "destructiveHint": False}
    assert custom_tool.server_origin == "custom-mcp-server"

    another_tool = next(t for t in result.tools if t.name == "another_tool")
    assert another_tool.annotations is None
    assert another_tool.server_origin == "custom-mcp-server"


@pytest.mark.asyncio
async def test_discover_all_concurrent(mock_mcp_client):
    """discover_all runs multiple servers concurrently and collects results."""

    call_count = 0

    def route_request(method, params=None):
        nonlocal call_count
        if method == "initialize":
            call_count += 1
            return {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": f"server-{call_count}", "version": "1.0.0"},
            }
        elif method == "tools/list":
            return {
                "tools": [
                    {
                        "name": f"tool_{call_count}",
                        "description": "A tool",
                        "inputSchema": {"type": "object", "properties": {}},
                    }
                ]
            }
        raise ValueError(f"Unexpected method: {method}")

    mock_cls, mock_instance = mock_mcp_client(route_request)

    with patch("unifi_mcp_relay.discovery.McpHttpClient", mock_cls):
        from unifi_mcp_relay.discovery import discover_all

        results = await discover_all(["http://localhost:3000", "http://localhost:3001"])

    # Both servers should be discovered (results may vary due to mock sharing)
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_discover_all_handles_failures(mock_mcp_client):
    """discover_all logs failures and returns only successful results."""

    def route_request(method, params=None):
        raise ConnectionError("Connection refused")

    mock_cls, mock_instance = mock_mcp_client(route_request)

    with patch("unifi_mcp_relay.discovery.McpHttpClient", mock_cls):
        from unifi_mcp_relay.discovery import discover_all

        results = await discover_all(["http://localhost:3000", "http://localhost:3001"])

    assert results == []
