"""Tests for the ToolForwarder module."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from unifi_mcp_relay.discovery import LEGACY_MCP_PROTOCOL_REVISION, ServerInfo
from unifi_mcp_relay.forwarder import ToolForwarder
from unifi_mcp_relay.protocol import ToolInfo


@pytest.fixture
def server_infos():
    return [
        ServerInfo(
            name="unifi-network-mcp",
            url="http://localhost:3000",
            session_id="session-abc",
            protocol_version="2025-11-25",
            tools=[
                ToolInfo(name="unifi_list_devices", description="List devices", server_origin="unifi-network-mcp"),
                ToolInfo(name="unifi_reboot_device", description="Reboot", server_origin="unifi-network-mcp"),
            ],
        ),
        ServerInfo(
            name="unifi-protect-mcp",
            url="http://localhost:3001",
            session_id="session-xyz",
            protocol_version=LEGACY_MCP_PROTOCOL_REVISION,
            tools=[
                ToolInfo(name="protect_list_cameras", description="List cameras", server_origin="unifi-protect-mcp"),
            ],
        ),
    ]


def test_forwarder_builds_routing_table(server_infos):
    fwd = ToolForwarder(server_infos)
    assert fwd.get_server_url("unifi_list_devices") == "http://localhost:3000"
    assert fwd.get_server_url("unifi_reboot_device") == "http://localhost:3000"
    assert fwd.get_server_url("protect_list_cameras") == "http://localhost:3001"
    assert fwd.get_server_url("nonexistent_tool") is None


def test_forwarder_creates_one_client_per_server(server_infos):
    fwd = ToolForwarder(server_infos)
    # Two servers -> two clients
    assert len(fwd._clients) == 2
    assert "http://localhost:3000" in fwd._clients
    assert "http://localhost:3001" in fwd._clients


def test_forwarder_pre_sets_session_ids(server_infos):
    fwd = ToolForwarder(server_infos)
    assert fwd._clients["http://localhost:3000"]._session_id == "session-abc"
    assert fwd._clients["http://localhost:3001"]._session_id == "session-xyz"


def test_forwarder_pre_sets_negotiated_protocol_versions(server_infos):
    fwd = ToolForwarder(server_infos)
    assert fwd._clients["http://localhost:3000"]._protocol_version == "2025-11-25"
    assert fwd._clients["http://localhost:3001"]._protocol_version == LEGACY_MCP_PROTOCOL_REVISION


def test_forwarder_tracks_lazy_loaders():
    fwd = ToolForwarder(
        [
            ServerInfo(
                name="unifi-network-mcp",
                url="http://localhost:3000",
                session_id="session-abc",
                protocol_version="2025-11-25",
                lazy_load_tool_name="unifi_load_tools",
                tools=[
                    ToolInfo(name="unifi_tool_index", description="Index", server_origin="unifi-network-mcp"),
                    ToolInfo(name="unifi_load_tools", description="Load", server_origin="unifi-network-mcp"),
                    ToolInfo(name="unifi_list_clients", description="List clients", server_origin="unifi-network-mcp"),
                ],
            )
        ]
    )

    assert fwd._lazy_load_tool_by_url["http://localhost:3000"] == "unifi_load_tools"
    assert fwd._lazy_advertised_tools_by_url["http://localhost:3000"] == {"unifi_list_clients"}


async def test_forwarder_forwards_tool_call(server_infos):
    fwd = ToolForwarder(server_infos)
    with patch.object(fwd, "_call", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = {"success": True, "data": [{"mac": "aa:bb:cc:dd:ee:ff"}]}
        result = await fwd.forward("unifi_list_devices", {"compact": True})
        assert result == {"success": True, "data": [{"mac": "aa:bb:cc:dd:ee:ff"}]}
        mock_call.assert_called_once_with("http://localhost:3000", "unifi_list_devices", {"compact": True})


async def test_forwarder_returns_none_for_unknown_tool(server_infos):
    fwd = ToolForwarder(server_infos)
    result = await fwd.forward("nonexistent_tool", {})
    assert result is None


async def test_forwarder_forward_with_error_returns_none_for_unknown_tool(server_infos):
    fwd = ToolForwarder(server_infos)
    result = await fwd.forward_with_error("nonexistent_tool", {})
    assert "nonexistent_tool" in result


async def test_forwarder_returns_error_string_on_connection_failure(server_infos):
    fwd = ToolForwarder(server_infos)
    with patch.object(fwd, "_call", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = ConnectionError("Connection refused")
        error = await fwd.forward_with_error("unifi_list_devices", {})
        assert "Connection" in error


async def test_forwarder_forward_with_error_returns_result_on_success(server_infos):
    fwd = ToolForwarder(server_infos)
    with patch.object(fwd, "_call", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = {"success": True}
        result = await fwd.forward_with_error("protect_list_cameras", {})
        assert result == {"success": True}


async def test_forwarder_call_uses_client_request(server_infos):
    """_call delegates to the McpHttpClient.request and parses JSON text content."""
    fwd = ToolForwarder(server_infos)

    import json

    payload = {"success": True, "data": []}
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value={"content": [{"type": "text", "text": json.dumps(payload)}]})
    fwd._clients["http://localhost:3000"] = mock_client

    result = await fwd._call("http://localhost:3000", "unifi_list_devices", {"compact": False})
    assert result == payload
    mock_client.request.assert_called_once_with(
        "tools/call", {"name": "unifi_list_devices", "arguments": {"compact": False}}
    )


async def test_forwarder_loads_lazy_tool_before_first_direct_call():
    fwd = ToolForwarder(
        [
            ServerInfo(
                name="unifi-network-mcp",
                url="http://localhost:3000",
                session_id="session-abc",
                protocol_version="2025-11-25",
                lazy_load_tool_name="unifi_load_tools",
                tools=[
                    ToolInfo(name="unifi_tool_index", description="Index", server_origin="unifi-network-mcp"),
                    ToolInfo(name="unifi_load_tools", description="Load", server_origin="unifi-network-mcp"),
                    ToolInfo(name="unifi_list_clients", description="List clients", server_origin="unifi-network-mcp"),
                ],
            )
        ]
    )
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(
        side_effect=[
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"loaded": ["unifi_list_clients"], "errors": None}),
                    }
                ]
            },
            {"content": [{"type": "text", "text": json.dumps({"success": True, "data": []})}]},
        ]
    )
    fwd._clients["http://localhost:3000"] = mock_client

    result = await fwd.forward("unifi_list_clients", {"compact": True})

    assert result == {"success": True, "data": []}
    assert mock_client.request.await_args_list[0].args == (
        "tools/call",
        {"name": "unifi_load_tools", "arguments": {"tools": ["unifi_list_clients"]}},
    )
    assert mock_client.request.await_args_list[1].args == (
        "tools/call",
        {"name": "unifi_list_clients", "arguments": {"compact": True}},
    )


async def test_forwarder_caches_successfully_loaded_lazy_tools():
    fwd = ToolForwarder(
        [
            ServerInfo(
                name="unifi-network-mcp",
                url="http://localhost:3000",
                lazy_load_tool_name="unifi_load_tools",
                tools=[
                    ToolInfo(name="unifi_load_tools", description="Load", server_origin="unifi-network-mcp"),
                    ToolInfo(name="unifi_list_clients", description="List clients", server_origin="unifi-network-mcp"),
                ],
            )
        ]
    )
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(
        side_effect=[
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"loaded": ["unifi_list_clients"], "errors": None}),
                    }
                ]
            },
            {"content": [{"type": "text", "text": json.dumps({"success": True, "data": [1]})}]},
            {"content": [{"type": "text", "text": json.dumps({"success": True, "data": [2]})}]},
        ]
    )
    fwd._clients["http://localhost:3000"] = mock_client

    first = await fwd.forward("unifi_list_clients", {})
    second = await fwd.forward("unifi_list_clients", {})

    assert first == {"success": True, "data": [1]}
    assert second == {"success": True, "data": [2]}
    load_calls = [call for call in mock_client.request.await_args_list if call.args[1]["name"] == "unifi_load_tools"]
    assert len(load_calls) == 1


async def test_forwarder_does_not_load_eager_or_meta_tools():
    fwd = ToolForwarder(
        [
            ServerInfo(
                name="unifi-network-mcp",
                url="http://localhost:3000",
                lazy_load_tool_name="unifi_load_tools",
                tools=[
                    ToolInfo(name="unifi_tool_index", description="Index", server_origin="unifi-network-mcp"),
                    ToolInfo(name="unifi_load_tools", description="Load", server_origin="unifi-network-mcp"),
                    ToolInfo(name="unifi_list_clients", description="List clients", server_origin="unifi-network-mcp"),
                ],
            ),
            ServerInfo(
                name="unifi-protect-mcp",
                url="http://localhost:3001",
                tools=[
                    ToolInfo(
                        name="protect_list_cameras",
                        description="List cameras",
                        server_origin="unifi-protect-mcp",
                    ),
                ],
            ),
        ]
    )
    network_client = AsyncMock()
    network_client.request = AsyncMock(return_value={"content": [{"type": "text", "text": json.dumps({"tools": []})}]})
    protect_client = AsyncMock()
    protect_client.request = AsyncMock(
        return_value={"content": [{"type": "text", "text": json.dumps({"success": True, "data": []})}]}
    )
    fwd._clients["http://localhost:3000"] = network_client
    fwd._clients["http://localhost:3001"] = protect_client

    await fwd.forward("unifi_tool_index", {})
    await fwd.forward("protect_list_cameras", {})

    assert network_client.request.await_args.args[1]["name"] == "unifi_tool_index"
    assert protect_client.request.await_args.args[1]["name"] == "protect_list_cameras"


async def test_forwarder_reports_lazy_load_failure():
    fwd = ToolForwarder(
        [
            ServerInfo(
                name="unifi-network-mcp",
                url="http://localhost:3000",
                lazy_load_tool_name="unifi_load_tools",
                tools=[
                    ToolInfo(name="unifi_load_tools", description="Load", server_origin="unifi-network-mcp"),
                    ToolInfo(name="unifi_list_clients", description="List clients", server_origin="unifi-network-mcp"),
                ],
            )
        ]
    )
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(
        return_value={
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "loaded": [],
                            "errors": [{"tool": "unifi_list_clients", "error": "Failed to load"}],
                        }
                    ),
                }
            ]
        }
    )
    fwd._clients["http://localhost:3000"] = mock_client

    error = await fwd.forward_with_error("unifi_list_clients", {})

    assert "Failed to load lazy tool unifi_list_clients" in error
    assert mock_client.request.await_count == 1


async def test_forwarder_call_prefers_structured_content(server_infos):
    """_call returns MCP structuredContent when current protocol servers provide it."""
    fwd = ToolForwarder(server_infos)

    payload = {"success": True, "data": [{"mac": "aa:bb:cc:dd:ee:ff"}]}
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(
        return_value={
            "structuredContent": payload,
            "content": [{"type": "text", "text": ""}],
            "isError": False,
        }
    )
    fwd._clients["http://localhost:3000"] = mock_client

    result = await fwd._call("http://localhost:3000", "unifi_list_devices", {"compact": False})
    assert result == payload


async def test_forwarder_call_returns_raw_result_when_no_text_content(server_infos):
    """_call returns the raw result dict when content is missing or not text."""
    fwd = ToolForwarder(server_infos)

    mock_client = AsyncMock()
    raw = {"something": "unexpected"}
    mock_client.request = AsyncMock(return_value=raw)
    fwd._clients["http://localhost:3000"] = mock_client

    result = await fwd._call("http://localhost:3000", "unifi_list_devices", {})
    assert result == raw


async def test_forwarder_call_raises_for_unknown_server(server_infos):
    fwd = ToolForwarder(server_infos)
    with pytest.raises(RuntimeError, match="No client"):
        await fwd._call("http://localhost:9999", "some_tool", {})


async def test_forwarder_call_returns_raw_on_bad_json(server_infos):
    """_call falls back to raw result when text content is not valid JSON."""
    fwd = ToolForwarder(server_infos)

    mock_client = AsyncMock()
    raw_result = {"content": [{"type": "text", "text": "not-json-at-all"}]}
    mock_client.request = AsyncMock(return_value=raw_result)
    fwd._clients["http://localhost:3000"] = mock_client

    result = await fwd._call("http://localhost:3000", "unifi_list_devices", {})
    assert result == raw_result


async def test_forwarder_open_and_close_lifecycle(server_infos):
    """open() and close() delegate to each client."""
    fwd = ToolForwarder(server_infos)

    for url, client in fwd._clients.items():
        fwd._clients[url] = AsyncMock()
        fwd._clients[url].open = AsyncMock()
        fwd._clients[url].close = AsyncMock()

    await fwd.open()
    for client in fwd._clients.values():
        client.open.assert_awaited_once()

    await fwd.close()
    for client in fwd._clients.values():
        client.close.assert_awaited_once()
