"""Tests for RelaySidecar orchestrator."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from unifi_mcp_relay.main import RelaySidecar
from unifi_mcp_relay.config import RelayConfig


@pytest.fixture
def config():
    return RelayConfig(
        relay_url="https://my-worker.workers.dev",
        relay_token="test-token",
        location_name="Test Lab",
        servers=["http://localhost:3000"],
        refresh_interval=60,
    )


@pytest.mark.asyncio
async def test_sidecar_discovers_and_builds_catalog(config):
    sidecar = RelaySidecar(config)
    from unifi_mcp_relay.discovery import ServerInfo
    from unifi_mcp_relay.protocol import ToolInfo

    mock_info = ServerInfo(
        name="unifi-network-mcp",
        url="http://localhost:3000",
        tools=[ToolInfo(name="unifi_list_devices", description="List", server_origin="unifi-network-mcp")],
    )

    with patch("unifi_mcp_relay.main.discover_all", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = [mock_info]
        with patch("unifi_mcp_relay.main.ToolForwarder") as MockFwd:
            mock_fwd_instance = AsyncMock()
            MockFwd.return_value = mock_fwd_instance

            catalog = await sidecar._discover_catalog()
            assert len(catalog) == 1
            assert catalog[0].name == "unifi_list_devices"
            mock_fwd_instance.open.assert_called_once()


@pytest.mark.asyncio
async def test_sidecar_tool_call_handler_delegates_to_forwarder(config):
    sidecar = RelaySidecar(config)
    from unifi_mcp_relay.discovery import ServerInfo
    from unifi_mcp_relay.protocol import ToolInfo

    mock_info = ServerInfo(
        name="unifi-network-mcp",
        url="http://localhost:3000",
        tools=[ToolInfo(name="unifi_list_devices", description="List", server_origin="unifi-network-mcp")],
    )

    with patch("unifi_mcp_relay.main.discover_all", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = [mock_info]
        with patch("unifi_mcp_relay.main.ToolForwarder") as MockFwd:
            mock_fwd_instance = AsyncMock()
            MockFwd.return_value = mock_fwd_instance
            await sidecar._discover_catalog()

    mock_fwd_instance.forward_with_error = AsyncMock(return_value={"success": True, "data": []})
    sidecar._forwarder = mock_fwd_instance

    result, error = await sidecar._handle_tool_call("unifi_list_devices", {})
    assert result == {"success": True, "data": []}
    assert error is None


@pytest.mark.asyncio
async def test_sidecar_tool_call_handler_returns_error_string(config):
    sidecar = RelaySidecar(config)
    from unifi_mcp_relay.forwarder import ToolForwarder

    mock_fwd = AsyncMock(spec=ToolForwarder)
    mock_fwd.forward_with_error = AsyncMock(return_value="Connection refused")
    sidecar._forwarder = mock_fwd

    result, error = await sidecar._handle_tool_call("unifi_list_devices", {})
    assert result is None
    assert error == "Connection refused"
