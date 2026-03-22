"""Tests for the WebSocket relay client module."""

from __future__ import annotations

import json

import pytest
import websockets
from unittest.mock import AsyncMock, patch

from unifi_mcp_relay.client import RelayClient
from unifi_mcp_relay.config import RelayConfig
from unifi_mcp_relay.protocol import (
    ToolCallMessage,
    RegisteredMessage,
    HeartbeatMessage,
    ErrorMessage,
    ToolInfo,
)


@pytest.fixture
def config():
    return RelayConfig(
        relay_url="https://my-worker.workers.dev",
        relay_token="test-token",
        location_name="Test Lab",
        servers=["http://localhost:3000"],
    )


@pytest.fixture
def tools():
    return [
        ToolInfo(
            name="unifi_list_devices",
            description="List devices",
            annotations={"readOnlyHint": True},
            server_origin="unifi-network-mcp",
        ),
    ]


def test_client_builds_ws_url(config):
    client = RelayClient(config)
    assert client._ws_url == "wss://my-worker.workers.dev/ws"


def test_client_builds_ws_url_from_http():
    config2 = RelayConfig(
        relay_url="http://localhost:8787",
        relay_token="test",
        location_name="Test",
    )
    client = RelayClient(config2)
    assert client._ws_url == "ws://localhost:8787/ws"


def test_client_builds_ws_url_strips_trailing_slash():
    config2 = RelayConfig(
        relay_url="https://my-worker.workers.dev/",
        relay_token="test",
        location_name="Test",
    )
    client = RelayClient(config2)
    assert client._ws_url == "wss://my-worker.workers.dev/ws"


async def test_client_sends_register_on_connect(config, tools):
    client = RelayClient(config)
    mock_ws = AsyncMock()
    mock_ws.recv = AsyncMock(
        return_value=json.dumps(
            {
                "type": "registered",
                "location_id": "loc_123",
                "location_name": "Test Lab",
            }
        )
    )

    with patch("unifi_mcp_relay.client.websockets") as mock_websockets:
        mock_websockets.connect = AsyncMock(return_value=mock_ws)
        mock_websockets.Subprotocol = websockets.Subprotocol
        await client._connect_and_register(tools)

        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["type"] == "register"
        assert sent_data["token"] == "test-token"
        assert sent_data["location_name"] == "Test Lab"
        assert len(sent_data["tools"]) == 1
        assert client._location_id == "loc_123"


async def test_client_handles_heartbeat(config):
    client = RelayClient(config)
    mock_ws = AsyncMock()
    await client._handle_message(HeartbeatMessage(), mock_ws)
    sent_data = json.loads(mock_ws.send.call_args[0][0])
    assert sent_data["type"] == "heartbeat_ack"


async def test_client_handles_tool_call(config):
    client = RelayClient(config)

    async def handler(name: str, args: dict) -> tuple[dict | None, str | None]:
        return {"success": True, "data": [1, 2, 3]}, None

    client._tool_call_handler = handler
    mock_ws = AsyncMock()

    msg = ToolCallMessage(call_id="call-123", tool_name="unifi_list_devices", arguments={"compact": True})
    await client._handle_tool_call(msg, mock_ws)

    sent_data = json.loads(mock_ws.send.call_args[0][0])
    assert sent_data["type"] == "tool_result"
    assert sent_data["call_id"] == "call-123"
    assert sent_data["result"] == {"success": True, "data": [1, 2, 3]}
    assert "error" not in sent_data


async def test_client_handles_tool_call_error(config):
    client = RelayClient(config)

    async def handler(name: str, args: dict) -> tuple[dict | None, str | None]:
        return None, "Tool execution failed"

    client._tool_call_handler = handler
    mock_ws = AsyncMock()

    msg = ToolCallMessage(call_id="call-456", tool_name="unifi_reboot_device", arguments={})
    await client._handle_tool_call(msg, mock_ws)

    sent_data = json.loads(mock_ws.send.call_args[0][0])
    assert sent_data["type"] == "tool_result"
    assert sent_data["call_id"] == "call-456"
    assert sent_data["error"] == "Tool execution failed"
    assert "result" not in sent_data


async def test_client_handles_tool_call_handler_exception(config):
    client = RelayClient(config)

    async def handler(name: str, args: dict) -> tuple[dict | None, str | None]:
        raise RuntimeError("Unexpected failure")

    client._tool_call_handler = handler
    mock_ws = AsyncMock()

    msg = ToolCallMessage(call_id="call-789", tool_name="unifi_list_devices", arguments={})
    await client._handle_tool_call(msg, mock_ws)

    sent_data = json.loads(mock_ws.send.call_args[0][0])
    assert sent_data["type"] == "tool_result"
    assert sent_data["call_id"] == "call-789"
    assert "error" in sent_data
    assert "Unexpected failure" in sent_data["error"]


async def test_client_handles_error_message(config):
    client = RelayClient(config)
    mock_ws = AsyncMock()
    msg = ErrorMessage(message="Rate limited", code="rate_limit")
    # Should not raise, just log
    await client._handle_message(msg, mock_ws)
    mock_ws.send.assert_not_called()


async def test_client_ignores_none_message(config):
    client = RelayClient(config)
    mock_ws = AsyncMock()
    await client._handle_message(None, mock_ws)
    mock_ws.send.assert_not_called()


async def test_client_send_catalog_update_when_connected(config, tools):
    client = RelayClient(config)
    mock_ws = AsyncMock()
    mock_ws.open = True
    client._ws = mock_ws

    result = await client.send_catalog_update(tools)
    assert result is True
    sent_data = json.loads(mock_ws.send.call_args[0][0])
    assert sent_data["type"] == "catalog_update"
    assert len(sent_data["tools"]) == 1


async def test_client_send_catalog_update_when_disconnected(config, tools):
    client = RelayClient(config)
    client._ws = None

    result = await client.send_catalog_update(tools)
    assert result is False


async def test_client_send_catalog_update_when_ws_closed(config, tools):
    client = RelayClient(config)
    mock_ws = AsyncMock()
    mock_ws.open = False
    client._ws = mock_ws

    result = await client.send_catalog_update(tools)
    assert result is False


async def test_client_stop(config):
    client = RelayClient(config)
    assert client._running is False

    client._running = True
    mock_ws = AsyncMock()
    mock_ws.close = AsyncMock()
    client._ws = mock_ws

    await client.stop()
    assert client._running is False
    mock_ws.close.assert_awaited_once()


async def test_client_stop_when_no_ws(config):
    client = RelayClient(config)
    client._running = True

    await client.stop()
    assert client._running is False


async def test_client_register_raises_on_unexpected_response(config, tools):
    """Registration should raise if the server responds with something other than RegisteredMessage."""
    client = RelayClient(config)
    mock_ws = AsyncMock()
    mock_ws.recv = AsyncMock(
        return_value=json.dumps(
            {
                "type": "error",
                "message": "Invalid token",
                "code": "auth_error",
            }
        )
    )

    with patch("unifi_mcp_relay.client.websockets") as mock_websockets:
        mock_websockets.connect = AsyncMock(return_value=mock_ws)
        mock_websockets.Subprotocol = websockets.Subprotocol

        with pytest.raises(ConnectionError, match="Registration failed"):
            await client._connect_and_register(tools)
