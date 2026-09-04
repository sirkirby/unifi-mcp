"""Tests for RelaySidecar orchestrator."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from unifi_mcp_relay.config import RelayConfig
from unifi_mcp_relay.main import DiscoveryNotReadyError, RelaySidecar, _catalog_snapshot
from unifi_mcp_relay.policy import RELAY_EXCLUDED_ERROR


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
@pytest.mark.parametrize("replacement_url", ["http://localhost:3000", "http://localhost:3001"])
@pytest.mark.parametrize("in_flight", [False, True])
async def test_batch_provenance_survives_refresh_only_for_same_backend(config, replacement_url, in_flight):
    from unifi_mcp_relay.discovery import ServerInfo
    from unifi_mcp_relay.protocol import ToolInfo

    tools = [ToolInfo(name=name, description=name) for name in ("unifi_batch", "unifi_batch_status")]
    original = ServerInfo(name="network", url=config.servers[0], tools=tools)
    replacement = ServerInfo(name="network", url=replacement_url, tools=tools)
    sidecar = RelaySidecar(config)
    started = asyncio.Event()
    finish = asyncio.Event()

    async def batch_call(*args):
        started.set()
        await finish.wait()
        return {"jobs": [{"jobId": "relay-created-job"}]}

    with (
        patch("unifi_mcp_relay.main.discover_all", AsyncMock(side_effect=[[original], [replacement], [replacement]])),
        patch("unifi_mcp_relay.forwarder.ToolForwarder.open", AsyncMock()),
        patch("unifi_mcp_relay.forwarder.ToolForwarder.close", AsyncMock()),
    ):
        await sidecar._discover_catalog()
        old_forwarder = sidecar._forwarder
        old_forwarder._call = AsyncMock(side_effect=batch_call)
        pending = asyncio.create_task(sidecar._handle_tool_call("unifi_batch", {"operations": []}))
        await started.wait()
        if not in_flight:
            finish.set()
            await pending
        await sidecar._discover_catalog()
        assert sidecar._forwarder is not old_forwarder
        finish.set()
        await pending

        status_call = AsyncMock(return_value={"status": "running"})
        sidecar._forwarder._call = status_call
        result, error = await sidecar._handle_tool_call("unifi_batch_status", {"jobId": "relay-created-job"})
        if replacement_url == original.url:
            assert result == {"status": "running"}
            assert error is None
            status_call.assert_awaited_once()
        else:
            assert result is None
            assert "only for jobs started" in error
            status_call.assert_not_awaited()

        status_call.reset_mock()
        _, error = await sidecar._handle_tool_call("unifi_batch_status", {"jobId": "foreign-job"})
        assert "only for jobs started" in error
        status_call.assert_not_awaited()

        fresh_sidecar = RelaySidecar(config)
        await fresh_sidecar._discover_catalog()
        fresh_sidecar._forwarder._call = status_call
        _, error = await fresh_sidecar._handle_tool_call("unifi_batch_status", {"jobId": "relay-created-job"})
        assert "only for jobs started" in error
        status_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_sidecar_never_advertises_support_tools_from_stale_discovery(config):
    sidecar = RelaySidecar(config)
    from unifi_mcp_relay.discovery import ServerInfo
    from unifi_mcp_relay.protocol import ToolInfo

    mock_info = ServerInfo(
        name="unifi-network-mcp",
        url="http://localhost:3000",
        tools=[
            ToolInfo(name="unifi_get_support_bundle", description="Support", server_origin="unifi-network-mcp"),
            ToolInfo(name="unifi_tool_index", description="Index", server_origin="unifi-network-mcp"),
        ],
    )
    with (
        patch("unifi_mcp_relay.main.discover_all", new_callable=AsyncMock, return_value=[mock_info]),
        patch("unifi_mcp_relay.main.ToolForwarder") as forwarder_class,
    ):
        forwarder_class.return_value = AsyncMock()
        catalog = await sidecar._discover_catalog()

    assert [tool.name for tool in catalog] == ["unifi_tool_index"]


@pytest.mark.asyncio
async def test_sidecar_discovery_requires_all_configured_servers(config):
    sidecar = RelaySidecar(config)

    with patch("unifi_mcp_relay.main.discover_all", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = []

        with pytest.raises(DiscoveryNotReadyError, match="0/1"):
            await sidecar._discover_catalog()

    assert sidecar._catalog == []
    assert sidecar._forwarder is None


@pytest.mark.asyncio
async def test_sidecar_startup_waits_for_non_empty_catalog_before_registering(config):
    sidecar = RelaySidecar(config)
    from unifi_mcp_relay.discovery import ServerInfo
    from unifi_mcp_relay.protocol import ToolInfo

    mock_info = ServerInfo(
        name="unifi-network-mcp",
        url="http://localhost:3000",
        tools=[ToolInfo(name="unifi_list_devices", description="List", server_origin="unifi-network-mcp")],
    )

    with (
        patch("unifi_mcp_relay.main.discover_all", new_callable=AsyncMock) as mock_discover,
        patch("unifi_mcp_relay.main.ToolForwarder") as MockFwd,
        patch("unifi_mcp_relay.main.RelayClient") as MockClient,
        patch("unifi_mcp_relay.main.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        mock_discover.side_effect = [[], [mock_info]]
        mock_fwd_instance = AsyncMock()
        MockFwd.return_value = mock_fwd_instance
        mock_client = AsyncMock()
        MockClient.return_value = mock_client

        sidecar = RelaySidecar(config)
        await sidecar.run()

    mock_sleep.assert_awaited_once()
    mock_client.run.assert_awaited_once()
    registered_tools = mock_client.run.await_args.kwargs["tools"]
    assert [tool.name for tool in registered_tools] == ["unifi_list_devices"]


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("unifi_get_support_bundle", {}),
        ("unifi_execute", {"tool": "unifi_get_support_bundle"}),
        ("unifi_batch", {"operations": [{"tool": "unifi_get_support_bundle"}]}),
    ],
)
async def test_sidecar_rejects_support_calls_before_forwarder(config, tool_name, arguments):
    sidecar = RelaySidecar(config)
    sidecar._forwarder = AsyncMock()

    result, error = await sidecar._handle_tool_call(tool_name, arguments)

    assert result is None
    assert error == RELAY_EXCLUDED_ERROR
    sidecar._forwarder.forward_with_error.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_loop_sends_metadata_only_catalog_update(config):
    """Refresh must publish changed annotations even when tool names are stable."""
    from unifi_mcp_relay.protocol import ToolInfo

    sidecar = RelaySidecar(config)
    sidecar._catalog = [
        ToolInfo(name="unifi_list_clients", description="List clients", server_origin="unifi-network-mcp")
    ]
    sidecar._advertised_catalog = _catalog_snapshot(sidecar._catalog)
    updated_catalog = [
        ToolInfo(
            name="unifi_list_clients",
            description="List clients",
            annotations={"readOnlyHint": True, "openWorldHint": False},
            server_origin="unifi-network-mcp",
        )
    ]

    async def rediscover():
        sidecar._catalog = updated_catalog
        sidecar._running = False
        return updated_catalog

    sidecar._discover_catalog = AsyncMock(side_effect=rediscover)
    sidecar._client.send_catalog_update = AsyncMock(return_value=True)
    sidecar._running = True

    with patch("unifi_mcp_relay.main.asyncio.sleep", new_callable=AsyncMock):
        await sidecar._refresh_loop()

    sidecar._discover_catalog.assert_awaited_once()
    sidecar._client.send_catalog_update.assert_awaited_once_with(updated_catalog)


@pytest.mark.asyncio
async def test_refresh_loop_ignores_catalog_reordering(config):
    """Refresh must not publish an update when only discovery order changes."""
    from unifi_mcp_relay.protocol import ToolInfo

    first = ToolInfo(name="unifi_list_clients", description="List clients", server_origin="unifi-network-mcp")
    second = ToolInfo(name="unifi_list_devices", description="List devices", server_origin="unifi-network-mcp")
    sidecar = RelaySidecar(config)
    sidecar._catalog = [first, second]
    sidecar._advertised_catalog = _catalog_snapshot(sidecar._catalog)

    async def rediscover():
        sidecar._catalog = [second, first]
        sidecar._running = False
        return sidecar._catalog

    sidecar._discover_catalog = AsyncMock(side_effect=rediscover)
    sidecar._client.send_catalog_update = AsyncMock(return_value=True)
    sidecar._running = True

    with patch("unifi_mcp_relay.main.asyncio.sleep", new_callable=AsyncMock):
        await sidecar._refresh_loop()

    sidecar._discover_catalog.assert_awaited_once()
    sidecar._client.send_catalog_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_loop_retries_catalog_update_after_disconnect(config):
    """A failed update must remain pending until it is advertised successfully."""
    from unifi_mcp_relay.protocol import ToolInfo

    sidecar = RelaySidecar(config)
    initial_catalog = [
        ToolInfo(name="unifi_list_clients", description="List clients", server_origin="unifi-network-mcp")
    ]
    updated_catalog = [
        ToolInfo(
            name="unifi_list_clients",
            description="List clients",
            annotations={"readOnlyHint": True, "openWorldHint": False},
            server_origin="unifi-network-mcp",
        )
    ]
    sidecar._catalog = initial_catalog
    sidecar._advertised_catalog = _catalog_snapshot(initial_catalog)
    attempts = 0

    async def rediscover():
        nonlocal attempts
        attempts += 1
        sidecar._catalog = updated_catalog
        if attempts == 2:
            sidecar._running = False
        return updated_catalog

    sidecar._discover_catalog = AsyncMock(side_effect=rediscover)
    sidecar._client.send_catalog_update = AsyncMock(side_effect=[False, True])
    sidecar._running = True

    with patch("unifi_mcp_relay.main.asyncio.sleep", new_callable=AsyncMock):
        await sidecar._refresh_loop()

    assert sidecar._client.send_catalog_update.await_count == 2
    assert sidecar._advertised_catalog == _catalog_snapshot(updated_catalog)
