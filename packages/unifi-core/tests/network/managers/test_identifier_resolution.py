"""Device and client lookups accept the ``_id`` their list views report, as well as a MAC."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.managers.client_manager import ClientManager
from unifi_core.network.managers.device_manager import DeviceManager
from unifi_core.network.managers.stats_manager import StatsManager

DEVICE_ID = "6E1B2C3D-0000-4000-8000-00000000AA01"
DEVICE_MAC = "11:22:33:44:55:66"
ONLINE_ID = "6e1b2c3d-0000-4000-8000-00000000cc01"
ONLINE_MAC = "aa:bb:cc:dd:ee:01"
OFFLINE_ID = "5f0000000000000000000002"
OFFLINE_MAC = "aa:bb:cc:dd:ee:02"


def _device(mac: str, _id: str, device_type: str = "uap") -> SimpleNamespace:
    return SimpleNamespace(mac=mac, raw={"_id": _id, "mac": mac, "type": device_type, "name": "AP"})


def _device_manager() -> DeviceManager:
    manager = DeviceManager(MagicMock())
    manager.get_devices = AsyncMock(
        return_value=[_device("99:88:77:66:55:44", "other-device"), _device(DEVICE_MAC, DEVICE_ID)]
    )
    return manager


def _client_manager() -> ClientManager:
    """A ClientManager whose online list holds one client and user table another."""
    manager = ClientManager(MagicMock())
    manager.get_clients = AsyncMock(return_value=[{"_id": ONLINE_ID, "mac": ONLINE_MAC, "hostname": "laptop"}])
    manager.get_all_clients = AsyncMock(
        return_value=[
            {"_id": ONLINE_ID, "mac": ONLINE_MAC},
            {"_id": OFFLINE_ID, "mac": OFFLINE_MAC, "name": "printer"},
        ]
    )
    manager._get_user_by_mac = AsyncMock(return_value=None)
    return manager


@pytest.mark.asyncio
async def test_device_resolves_by_id_to_the_record_its_mac_finds():
    manager = _device_manager()

    device = await manager.get_device_by_identifier(DEVICE_ID)

    assert device.raw["mac"] == DEVICE_MAC


@pytest.mark.asyncio
async def test_device_mac_identifier_takes_the_mac_lookup_unchanged():
    manager = _device_manager()
    manager.get_device_details = AsyncMock(return_value="by-mac")

    assert await manager.get_device_by_identifier(DEVICE_MAC.upper()) == "by-mac"
    manager.get_device_details.assert_awaited_once_with(DEVICE_MAC.upper())


@pytest.mark.asyncio
async def test_device_unknown_id_is_not_found_naming_the_identifier_as_given():
    manager = _device_manager()

    with pytest.raises(UniFiNotFoundError) as caught:
        await manager.get_device_by_identifier(DEVICE_ID.lower())

    assert caught.value.identifier == DEVICE_ID.lower()
    assert str(caught.value) == f"device '{DEVICE_ID.lower()}' not found"


@pytest.mark.asyncio
@pytest.mark.parametrize(("identifier", "mac"), [(ONLINE_ID, ONLINE_MAC), (OFFLINE_ID, OFFLINE_MAC)])
async def test_client_resolves_by_id_from_the_online_or_user_table(identifier, mac):
    manager = _client_manager()

    client = await manager.get_client_by_identifier(identifier)

    assert client.raw["mac"] == mac
    assert client.raw["_id"] == identifier


@pytest.mark.asyncio
async def test_client_mac_identifier_takes_the_mac_lookup_unchanged():
    manager = _client_manager()
    manager.get_client_details = AsyncMock(return_value="by-mac")

    assert await manager.get_client_by_identifier(ONLINE_MAC, existence_only=True) == "by-mac"
    manager.get_client_details.assert_awaited_once_with(ONLINE_MAC, existence_only=True)


@pytest.mark.asyncio
async def test_client_unknown_id_is_not_found_naming_the_identifier_as_given():
    manager = _client_manager()

    with pytest.raises(UniFiNotFoundError) as caught:
        await manager.get_client_by_identifier("Unknown-Client-Id")

    assert str(caught.value) == "client 'Unknown-Client-Id' not found"


@pytest.mark.asyncio
async def test_client_id_survives_one_failed_list():
    manager = _client_manager()
    manager.get_clients = AsyncMock(side_effect=ConnectionError("sta down"))

    client = await manager.get_client_by_identifier(OFFLINE_ID)

    assert client.raw["mac"] == OFFLINE_MAC


@pytest.mark.asyncio
async def test_client_id_surfaces_the_outage_when_both_lists_fail():
    manager = _client_manager()
    outage = ConnectionError("controller offline")
    manager.get_clients = AsyncMock(side_effect=outage)
    manager.get_all_clients = AsyncMock(side_effect=ConnectionError("also offline"))

    with pytest.raises(ConnectionError) as caught:
        await manager.get_client_by_identifier(OFFLINE_ID)

    assert caught.value is outage


@pytest.mark.asyncio
async def test_client_stats_for_identifier_fetches_the_resolved_mac():
    stats = StatsManager(MagicMock(), _client_manager())
    stats.get_client_stats = AsyncMock(return_value=[{"rx_bytes": 1}])

    assert await stats.get_client_stats_for_identifier(OFFLINE_ID, duration_hours=24) == [{"rx_bytes": 1}]
    stats.get_client_stats.assert_awaited_once_with(
        OFFLINE_MAC, duration_hours=24, granularity="hourly", start_ms=None, end_ms=None
    )


@pytest.mark.asyncio
async def test_client_stats_for_unknown_identifier_is_not_found():
    stats = StatsManager(MagicMock(), _client_manager())
    stats.get_client_stats = AsyncMock()

    with pytest.raises(UniFiNotFoundError):
        await stats.get_client_stats_for_identifier("missing-id")
    stats.get_client_stats.assert_not_awaited()


@pytest.mark.asyncio
async def test_device_stats_for_identifier_fetches_the_resolved_mac(monkeypatch):
    monkeypatch.setattr(DeviceManager, "get_devices", _device_manager().get_devices)
    stats = StatsManager(MagicMock(), MagicMock())
    stats.get_device_stats = AsyncMock(return_value=[])

    await stats.get_device_stats_for_identifier(DEVICE_ID, duration_hours=168)

    stats.get_device_stats.assert_awaited_once_with(
        DEVICE_MAC, duration_hours=168, granularity="hourly", device_type="ap"
    )
