"""The device and client stats tools accept the ``_id`` their list tools report, as well as a MAC."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unifi_core.network.managers.client_manager import ClientManager
from unifi_core.network.managers.device_manager import DeviceManager

DEVICE_ID = "6e1b2c3d-0000-4000-8000-00000000aa01"
DEVICE_MAC = "11:22:33:44:55:66"
CLIENT_ID = "6e1b2c3d-0000-4000-8000-00000000cc01"
CLIENT_MAC = "aa:bb:cc:dd:ee:01"


def _device_manager() -> DeviceManager:
    manager = DeviceManager(MagicMock())
    device = SimpleNamespace(
        mac=DEVICE_MAC, raw={"_id": DEVICE_ID, "mac": DEVICE_MAC, "type": "uap", "name": "Bedroom AP"}
    )
    manager.get_devices = AsyncMock(return_value=[device])
    return manager


def _client_manager() -> ClientManager:
    manager = ClientManager(MagicMock())
    manager.get_clients = AsyncMock(return_value=[{"_id": CLIENT_ID, "mac": CLIENT_MAC, "hostname": "workbench"}])
    manager.get_all_clients = AsyncMock(return_value=[{"_id": CLIENT_ID, "mac": CLIENT_MAC}])
    return manager


def _stats_manager() -> MagicMock:
    stats = MagicMock()
    stats._connection.site = "default"
    stats.get_device_stats = AsyncMock(return_value=[{"time": 1, "rx_bytes": 5, "tx_bytes": 3, "num_sta": 2}])
    stats.get_client_stats = AsyncMock(return_value=[{"time": 1, "rx_bytes": 5, "tx_bytes": 3}])
    return stats


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", [DEVICE_ID, DEVICE_MAC])
async def test_device_stats_accepts_the_listed_id_or_the_mac(identifier):
    stats = _stats_manager()
    with (
        patch("unifi_network_mcp.tools.stats.stats_manager", stats),
        patch("unifi_network_mcp.tools.stats.device_manager", _device_manager()),
    ):
        from unifi_network_mcp.tools.stats import get_device_stats

        result = await get_device_stats(device_id=identifier)

    assert result["success"] is True, result
    assert result["device_name"] == "Bedroom AP"
    assert stats.get_device_stats.await_args.args == (DEVICE_MAC,)
    assert stats.get_device_stats.await_args.kwargs["device_type"] == "ap"


@pytest.mark.asyncio
async def test_device_stats_unknown_id_is_not_found():
    stats = _stats_manager()
    with (
        patch("unifi_network_mcp.tools.stats.stats_manager", stats),
        patch("unifi_network_mcp.tools.stats.device_manager", _device_manager()),
    ):
        from unifi_network_mcp.tools.stats import get_device_stats

        result = await get_device_stats(device_id="missing-device-id")

    assert result["success"] is False
    assert "device 'missing-device-id' not found" in result["error"]
    stats.get_device_stats.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", [CLIENT_ID, CLIENT_MAC])
async def test_client_stats_accepts_the_listed_id_or_the_mac(identifier):
    stats = _stats_manager()
    with (
        patch("unifi_network_mcp.tools.stats.stats_manager", stats),
        patch("unifi_network_mcp.tools.stats.client_manager", _client_manager()),
    ):
        from unifi_network_mcp.tools.stats import get_client_stats

        result = await get_client_stats(client_id=identifier)

    assert result["success"] is True, result
    assert result["client_name"] == "workbench"
    assert stats.get_client_stats.await_args.args == (CLIENT_MAC,)


@pytest.mark.asyncio
async def test_client_stats_unknown_id_is_not_found():
    stats = _stats_manager()
    with (
        patch("unifi_network_mcp.tools.stats.stats_manager", stats),
        patch("unifi_network_mcp.tools.stats.client_manager", _client_manager()),
    ):
        from unifi_network_mcp.tools.stats import get_client_stats

        result = await get_client_stats(client_id="missing-client-id")

    assert result["success"] is False
    assert "client 'missing-client-id' not found" in result["error"]
    stats.get_client_stats.assert_not_awaited()
