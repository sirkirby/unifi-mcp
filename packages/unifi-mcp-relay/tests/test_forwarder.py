"""Tests for the ToolForwarder module."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from unifi_mcp_relay.discovery import ServerInfo
from unifi_mcp_relay.forwarder import ToolForwarder
from unifi_mcp_relay.protocol import ToolInfo


@pytest.fixture
def server_infos():
    return [
        ServerInfo(
            name="unifi-network-mcp",
            url="http://localhost:3000",
            session_id="session-abc",
            tools=[
                ToolInfo(name="unifi_list_devices", description="List devices", server_origin="unifi-network-mcp"),
                ToolInfo(name="unifi_reboot_device", description="Reboot", server_origin="unifi-network-mcp"),
            ],
        ),
        ServerInfo(
            name="unifi-protect-mcp",
            url="http://localhost:3001",
            session_id="session-xyz",
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
    mock_client.request = AsyncMock(
        return_value={"content": [{"type": "text", "text": json.dumps(payload)}]}
    )
    fwd._clients["http://localhost:3000"] = mock_client

    result = await fwd._call("http://localhost:3000", "unifi_list_devices", {"compact": False})
    assert result == payload
    mock_client.request.assert_called_once_with(
        "tools/call", {"name": "unifi_list_devices", "arguments": {"compact": False}}
    )


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


def test_forwarder_update_refreshes_routing_table(server_infos):
    fwd = ToolForwarder(server_infos)
    assert fwd.get_server_url("protect_list_cameras") == "http://localhost:3001"

    new_infos = [
        ServerInfo(
            name="unifi-access-mcp",
            url="http://localhost:3002",
            tools=[
                ToolInfo(name="access_list_doors", description="List doors", server_origin="unifi-access-mcp"),
            ],
        ),
    ]
    fwd.update(new_infos)

    # Old tools no longer routable
    assert fwd.get_server_url("unifi_list_devices") is None
    assert fwd.get_server_url("protect_list_cameras") is None
    # New tool is routable
    assert fwd.get_server_url("access_list_doors") == "http://localhost:3002"


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
