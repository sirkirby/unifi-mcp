"""Integration test: full lifecycle with a mock WebSocket worker server."""

from __future__ import annotations

import asyncio
import json

import pytest
import websockets
from websockets.asyncio.server import serve

from unifi_mcp_relay.client import RelayClient
from unifi_mcp_relay.config import RelayConfig
from unifi_mcp_relay.protocol import ToolInfo


class MockWorker:
    """A mock Cloudflare Worker WebSocket relay for integration testing.

    Runs a websockets server that:
    1. Receives register message and validates token
    2. Sends registered response
    3. Sends a tool_call message
    4. Receives tool_result response
    5. Sends heartbeat, receives heartbeat_ack
    6. Closes connection
    """

    def __init__(self, expected_token: str) -> None:
        self._expected_token = expected_token
        self._server = None
        self.port: int | None = None

        # Recorded state for assertions
        self.register_received: dict | None = None
        self.tool_result_received: dict | None = None
        self.heartbeat_ack_received: bool = False
        self.registered_tools: list[dict] = []

    async def _handler(self, ws: websockets.asyncio.server.ServerConnection) -> None:
        """Handle a single sidecar connection through the full lifecycle."""
        # Step 1: Receive register message
        raw = await ws.recv()
        msg = json.loads(raw)
        self.register_received = msg

        assert msg["type"] == "register"
        assert msg["token"] == self._expected_token
        self.registered_tools = msg.get("tools", [])

        # Step 2: Send registered response
        await ws.send(
            json.dumps(
                {
                    "type": "registered",
                    "location_id": "loc_test_123",
                    "location_name": msg["location_name"],
                }
            )
        )

        # Step 3: Send a tool_call
        await ws.send(
            json.dumps(
                {
                    "type": "tool_call",
                    "call_id": "call_integration_001",
                    "tool_name": "unifi_list_devices",
                    "arguments": {"compact": True},
                    "timeout_ms": 5000,
                }
            )
        )

        # Step 4: Receive tool_result
        raw = await ws.recv()
        result_msg = json.loads(raw)
        assert result_msg["type"] == "tool_result"
        self.tool_result_received = result_msg

        # Step 5: Send heartbeat
        await ws.send(json.dumps({"type": "heartbeat"}))

        # Receive heartbeat_ack
        raw = await ws.recv()
        ack_msg = json.loads(raw)
        assert ack_msg["type"] == "heartbeat_ack"
        self.heartbeat_ack_received = True

        # Step 6: Close connection cleanly
        await ws.close()

    def _select_subprotocol(
        self,
        connection: websockets.asyncio.server.ServerConnection,
        subprotocols: list[websockets.Subprotocol],
    ) -> websockets.Subprotocol | None:
        """Accept the unifi-relay-v1 subprotocol."""
        for sp in subprotocols:
            if sp == "unifi-relay-v1":
                return sp
        return None

    async def start(self) -> None:
        """Start the mock WebSocket server on a random port."""
        self._server = await serve(
            self._handler,
            "localhost",
            0,
            select_subprotocol=self._select_subprotocol,
        )
        # Extract the assigned port
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        """Shut down the mock server."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()


async def test_full_lifecycle(sample_tools: list[ToolInfo]) -> None:
    """End-to-end test: connect -> register -> tool call -> heartbeat -> disconnect."""
    token = "integration-test-token"
    mock_worker = MockWorker(expected_token=token)
    await mock_worker.start()

    assert mock_worker.port is not None

    config = RelayConfig(
        relay_url=f"http://localhost:{mock_worker.port}",
        relay_token=token,
        location_name="Integration Test Lab",
        reconnect_max_delay=1,  # Short delay so the test exits quickly after disconnect
    )
    client = RelayClient(config)

    # Canned tool call handler
    async def tool_handler(name: str, args: dict) -> tuple[dict | None, str | None]:
        if name == "unifi_list_devices":
            return {"success": True, "data": [{"mac": "aa:bb:cc:dd:ee:ff", "name": "USW-Pro-24"}]}, None
        return None, f"Unknown tool: {name}"

    # Run the client with a timeout. After the mock worker closes the connection,
    # the client will attempt to reconnect, fail (server is closing), and retry.
    # We stop the client explicitly to break the reconnect loop.
    async def run_client_with_shutdown() -> None:
        # Give the client time to do a full lifecycle, then stop it
        # once the mock worker has completed its sequence.
        client_task = asyncio.create_task(client.run(sample_tools, tool_handler))
        try:
            # Wait for the mock worker to finish its handler sequence.
            # Poll until the heartbeat ack is received (the last step before close).
            for _ in range(100):
                if mock_worker.heartbeat_ack_received:
                    break
                await asyncio.sleep(0.05)

            # Give a brief moment for the connection close to propagate
            await asyncio.sleep(0.1)

            # Stop the client to break the reconnect loop
            await client.stop()

            # Wait for the client task to finish
            await asyncio.wait_for(client_task, timeout=3.0)
        except asyncio.TimeoutError:
            client_task.cancel()
            with pytest.raises((asyncio.CancelledError, Exception)):
                await client_task

    try:
        await asyncio.wait_for(run_client_with_shutdown(), timeout=10.0)
    finally:
        await mock_worker.stop()

    # --- Assertions ---

    # Registration happened with correct data
    assert mock_worker.register_received is not None
    assert mock_worker.register_received["type"] == "register"
    assert mock_worker.register_received["token"] == token
    assert mock_worker.register_received["location_name"] == "Integration Test Lab"

    # Tools were registered correctly
    assert len(mock_worker.registered_tools) == 2
    tool_names = {t["name"] for t in mock_worker.registered_tools}
    assert tool_names == {"unifi_list_devices", "unifi_reboot_device"}

    # Verify tool metadata was transmitted
    list_tool = next(t for t in mock_worker.registered_tools if t["name"] == "unifi_list_devices")
    assert list_tool["description"] == "List all UniFi network devices"
    assert list_tool["annotations"]["readOnlyHint"] is True
    assert list_tool["server_origin"] == "unifi-network-mcp"

    reboot_tool = next(t for t in mock_worker.registered_tools if t["name"] == "unifi_reboot_device")
    assert reboot_tool["annotations"]["destructiveHint"] is True

    # Tool result was received correctly
    assert mock_worker.tool_result_received is not None
    assert mock_worker.tool_result_received["call_id"] == "call_integration_001"
    assert mock_worker.tool_result_received["result"]["success"] is True
    assert len(mock_worker.tool_result_received["result"]["data"]) == 1
    assert mock_worker.tool_result_received["result"]["data"][0]["name"] == "USW-Pro-24"

    # Heartbeat was acknowledged
    assert mock_worker.heartbeat_ack_received is True


async def test_tool_call_error_response(sample_tools: list[ToolInfo]) -> None:
    """Test that a tool handler returning an error is correctly relayed."""
    token = "error-test-token"

    tool_result_received: dict | None = None

    async def handler(ws: websockets.asyncio.server.ServerConnection) -> None:
        nonlocal tool_result_received

        # Receive register
        raw = await ws.recv()
        msg = json.loads(raw)
        assert msg["type"] == "register"

        # Send registered
        await ws.send(
            json.dumps({"type": "registered", "location_id": "loc_err", "location_name": msg["location_name"]})
        )

        # Send tool_call for an unknown tool
        await ws.send(
            json.dumps(
                {
                    "type": "tool_call",
                    "call_id": "call_err_001",
                    "tool_name": "nonexistent_tool",
                    "arguments": {},
                }
            )
        )

        # Receive tool_result (should be an error)
        raw = await ws.recv()
        tool_result_received = json.loads(raw)

        await ws.close()

    def select_sp(conn, subprotocols):
        for sp in subprotocols:
            if sp == "unifi-relay-v1":
                return sp
        return None

    async with serve(handler, "localhost", 0, select_subprotocol=select_sp) as server:
        port = server.sockets[0].getsockname()[1]

        config = RelayConfig(
            relay_url=f"http://localhost:{port}",
            relay_token=token,
            location_name="Error Test Lab",
            reconnect_max_delay=1,
        )
        client = RelayClient(config)

        async def tool_handler(name: str, args: dict) -> tuple[dict | None, str | None]:
            return None, f"Unknown tool: {name}"

        client_task = asyncio.create_task(client.run(sample_tools, tool_handler))

        # Wait for the tool result to be received by the mock server
        for _ in range(100):
            if tool_result_received is not None:
                break
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.1)
        await client.stop()

        try:
            await asyncio.wait_for(client_task, timeout=3.0)
        except asyncio.TimeoutError:
            client_task.cancel()

    # Assert error result
    assert tool_result_received is not None
    assert tool_result_received["type"] == "tool_result"
    assert tool_result_received["call_id"] == "call_err_001"
    assert "error" in tool_result_received
    assert "Unknown tool: nonexistent_tool" in tool_result_received["error"]
