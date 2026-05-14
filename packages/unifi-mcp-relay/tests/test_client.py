"""Tests for the WebSocket relay client module."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
import websockets
from unifi_mcp_relay.client import RelayClient
from unifi_mcp_relay.config import RelayConfig
from unifi_mcp_relay.protocol import (
    ErrorMessage,
    HeartbeatMessage,
    ToolCallMessage,
    ToolInfo,
)
from websockets.connection import State as WsState
from websockets.frames import Close


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

        # Verify token is in Authorization header, not in subprotocols
        connect_kwargs = mock_websockets.connect.call_args
        headers = connect_kwargs.kwargs.get("additional_headers", {})
        assert headers.get("Authorization") == "Bearer test-token"
        subprotocols = connect_kwargs.kwargs.get("subprotocols", [])
        subprotocol_values = [str(sp) for sp in subprotocols]
        assert "test-token" not in subprotocol_values
        assert "unifi-relay-v1" in subprotocol_values

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
    mock_ws.state = WsState.OPEN
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
    mock_ws.state = WsState.CLOSED
    client._ws = mock_ws

    result = await client.send_catalog_update(tools)
    assert result is False


async def test_client_send_catalog_update_handles_send_failure(config, tools):
    """send_catalog_update returns False and does not raise if ws.send() fails."""
    client = RelayClient(config)
    mock_ws = AsyncMock()
    mock_ws.state = WsState.OPEN
    mock_ws.send = AsyncMock(side_effect=websockets.ConnectionClosed(None, None))
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


# --- _is_auth_failure tests ---


def _make_connection_closed(code: int, reason: str = "") -> websockets.ConnectionClosed:
    """Create a ConnectionClosed exception with the given close code and reason."""
    rcvd = Close(code, reason)
    exc = websockets.ConnectionClosed(rcvd, None)
    return exc


def test_is_auth_failure_code_4001():
    exc = _make_connection_closed(4001)
    assert RelayClient._is_auth_failure(exc) is True


def test_is_auth_failure_code_4003():
    exc = _make_connection_closed(4003)
    assert RelayClient._is_auth_failure(exc) is True


def test_is_auth_failure_normal_close():
    exc = _make_connection_closed(1000, "normal close")
    assert RelayClient._is_auth_failure(exc) is False


def test_is_auth_failure_abnormal_close():
    exc = _make_connection_closed(1006, "abnormal closure")
    assert RelayClient._is_auth_failure(exc) is False


def test_is_auth_failure_reason_rejected():
    exc = _make_connection_closed(1008, "token rejected")
    assert RelayClient._is_auth_failure(exc) is True


def test_is_auth_failure_reason_auth():
    exc = _make_connection_closed(1008, "authentication failed")
    assert RelayClient._is_auth_failure(exc) is True


def test_is_auth_failure_no_rcvd():
    """When rcvd is None (abnormal closure with no close frame), not an auth failure."""
    exc = websockets.ConnectionClosed(None, None)
    assert RelayClient._is_auth_failure(exc) is False


# --- URL validation tests ---


def test_build_ws_url_rejects_invalid_scheme():
    with pytest.raises(ValueError, match="must start with http"):
        RelayClient._build_ws_url("ftp://example.com")


def test_build_ws_url_rejects_missing_scheme():
    with pytest.raises(ValueError, match="must start with http"):
        RelayClient._build_ws_url("example.com")


# --- Timeout enforcement test ---


async def test_client_tool_call_timeout():
    """Tool call should time out when handler exceeds timeout_ms."""
    config = RelayConfig(
        relay_url="https://example.com",
        relay_token="test",
        location_name="Test",
    )
    client = RelayClient(config)

    async def slow_handler(name: str, args: dict) -> tuple[dict | None, str | None]:
        await asyncio.sleep(10)
        return {"success": True}, None

    client._tool_call_handler = slow_handler
    mock_ws = AsyncMock()

    msg = ToolCallMessage(call_id="call-timeout", tool_name="slow_tool", arguments={}, timeout_ms=50)
    await client._handle_tool_call(msg, mock_ws)

    sent_data = json.loads(mock_ws.send.call_args[0][0])
    assert sent_data["type"] == "tool_result"
    assert sent_data["call_id"] == "call-timeout"
    assert "timed out" in sent_data["error"]


# --- Task tracking test ---


async def test_client_tracks_pending_tool_call_tasks(config):
    """Tool call tasks are tracked in _pending_tasks and cleaned up on completion."""
    client = RelayClient(config)
    call_started = asyncio.Event()
    call_proceed = asyncio.Event()

    async def handler(name: str, args: dict) -> tuple[dict | None, str | None]:
        call_started.set()
        await call_proceed.wait()
        return {"success": True}, None

    client._tool_call_handler = handler
    mock_ws = AsyncMock()
    mock_ws.state = WsState.OPEN

    msg = ToolCallMessage(call_id="call-track", tool_name="test_tool", arguments={}, timeout_ms=5000)
    await client._handle_message(msg, mock_ws)

    await call_started.wait()
    assert len(client._pending_tasks) == 1

    call_proceed.set()
    # Let the task complete
    await asyncio.gather(*client._pending_tasks)
    # Done callback should have removed it
    assert len(client._pending_tasks) == 0
