"""Fixed IP reservations name the network that holds the address, and releases respect local DNS records."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.errors import ResponseError
from unifi_core.network.managers.client_manager import ClientManager

CLIENT_MAC = "aa:bb:cc:dd:ee:ff"
NETWORKS = [
    {"_id": "lan", "name": "LAN", "purpose": "corporate", "ip_subnet": "192.168.1.1/24"},
    {"_id": "iot", "name": "IoT", "purpose": "corporate", "ip_subnet": "10.20.0.1/24"},
    {"_id": "wan", "name": "Internet", "purpose": "wan"},
]


def _manager(user: dict | None = None, networks: list[dict] = NETWORKS, *, stat_user_404: bool = False):
    record = {"_id": "user-1", "mac": CLIENT_MAC, "noted": True, **(user or {})}
    conn = MagicMock()
    conn.ensure_connected = AsyncMock(return_value=True)
    conn._invalidate_cache = MagicMock()
    puts: list[dict] = []

    async def request(api_request):
        if api_request.method == "get" and api_request.path == "/rest/networkconf":
            return deepcopy(networks)
        if api_request.method == "get" and api_request.path.startswith("/stat/user/"):
            if stat_user_404:
                raise ResponseError("Call https://c/stat/user/x received 404 Not Found")
            return [deepcopy(record)]
        if api_request.method == "get" and api_request.path == "/rest/user":
            return [{"_id": "other", "mac": "00:11:22:33:44:55"}, deepcopy(record)]
        if api_request.method == "put":
            puts.append(deepcopy(api_request.data))
        return {}

    conn.request = AsyncMock(side_effect=request)
    manager = ClientManager(conn)
    manager.get_client_details = AsyncMock(return_value=SimpleNamespace(raw=deepcopy(record)))
    return manager, puts


@pytest.mark.asyncio
async def test_a_reservation_names_the_network_whose_subnet_holds_the_address():
    manager, puts = _manager()

    assert await manager.set_client_ip_settings(CLIENT_MAC, use_fixedip=True, fixed_ip="10.20.0.50") is True

    assert puts == [{"use_fixedip": True, "fixed_ip": "10.20.0.50", "network_id": "iot"}]


@pytest.mark.asyncio
async def test_an_address_alone_also_names_its_network():
    manager, puts = _manager()

    await manager.set_client_ip_settings(CLIENT_MAC, fixed_ip="192.168.1.20")

    assert puts[0]["network_id"] == "lan"


@pytest.mark.asyncio
async def test_a_given_network_must_hold_the_address():
    manager, puts = _manager()

    await manager.set_client_ip_settings(CLIENT_MAC, fixed_ip="192.168.1.20", network_id="lan")
    assert puts[0]["network_id"] == "lan"

    with pytest.raises(ValueError, match="not in network"):
        await manager.set_client_ip_settings(CLIENT_MAC, fixed_ip="192.168.1.20", network_id="iot")
    with pytest.raises(ValueError, match="No network with id"):
        await manager.set_client_ip_settings(CLIENT_MAC, fixed_ip="192.168.1.20", network_id="gone")
    assert len(puts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fixed_ip", "networks", "message"),
    [
        ("172.16.0.5", NETWORKS, "No configured network contains"),
        ("192.168.1.20", [*NETWORKS, {"_id": "dup", "name": "Dup", "ip_subnet": "192.168.1.1/16"}], "network_id"),
        ("not-an-ip", NETWORKS, "not a valid IPv4 address"),
    ],
)
async def test_an_address_without_exactly_one_network_is_refused_before_writing(fixed_ip, networks, message):
    manager, puts = _manager(networks=networks)

    with pytest.raises(ValueError, match=message):
        await manager.set_client_ip_settings(CLIENT_MAC, use_fixedip=True, fixed_ip=fixed_ip)
    assert puts == []


@pytest.mark.asyncio
async def test_releasing_a_fixed_ip_with_a_local_dns_record_is_refused_with_the_reason():
    manager, puts = _manager({"use_fixedip": True, "fixed_ip": "192.168.1.20", "local_dns_record_enabled": True})

    with pytest.raises(ValueError, match="local DNS record"):
        await manager.set_client_ip_settings(CLIENT_MAC, use_fixedip=False)
    assert puts == []


@pytest.mark.asyncio
async def test_releasing_with_the_dns_record_turned_off_in_the_same_call_is_sent_together():
    manager, puts = _manager({"use_fixedip": True, "fixed_ip": "192.168.1.20", "local_dns_record_enabled": True})

    await manager.set_client_ip_settings(CLIENT_MAC, use_fixedip=False, local_dns_record_enabled=False)

    assert puts == [{"use_fixedip": False, "fixed_ip": "", "local_dns_record_enabled": False, "local_dns_record": ""}]


@pytest.mark.asyncio
async def test_releasing_without_a_dns_record_is_unchanged():
    manager, puts = _manager({"use_fixedip": True, "fixed_ip": "192.168.1.20"})

    await manager.set_client_ip_settings(CLIENT_MAC, use_fixedip=False)

    assert puts == [{"use_fixedip": False, "fixed_ip": ""}]


@pytest.mark.asyncio
@pytest.mark.parametrize("dns_enabled", [True, False])
async def test_a_release_reads_the_user_table_where_the_controller_has_no_stat_user(dns_enabled):
    manager, puts = _manager(
        {"use_fixedip": True, "fixed_ip": "192.168.1.20", "local_dns_record_enabled": dns_enabled}, stat_user_404=True
    )

    if dns_enabled:
        with pytest.raises(ValueError, match="local DNS record"):
            await manager.set_client_ip_settings(CLIENT_MAC, use_fixedip=False)
        assert puts == []
    else:
        await manager.set_client_ip_settings(CLIENT_MAC, use_fixedip=False)
        assert puts == [{"use_fixedip": False, "fixed_ip": ""}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dns_change",
    [{"local_dns_record_enabled": True, "local_dns_record": "host.lan"}, {"local_dns_record": "host.lan"}],
    ids=["explicit-enable", "hostname-enables"],
)
async def test_a_release_that_would_enable_a_dns_record_is_refused_before_any_write(dns_change):
    manager, puts = _manager({"noted": False, "use_fixedip": True, "fixed_ip": "192.168.1.20"})

    with pytest.raises(ValueError, match="local DNS record"):
        await manager.set_client_ip_settings(CLIENT_MAC, use_fixedip=False, **dns_change)
    assert puts == []


@pytest.mark.asyncio
async def test_the_network_resolver_reports_the_network_for_a_preview():
    manager, puts = _manager()

    assert await manager.resolve_fixed_ip_network("10.20.0.50") == {
        "network_id": "iot",
        "name": "IoT",
        "subnet": "10.20.0.0/24",
    }
    assert puts == []
