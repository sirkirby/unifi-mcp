"""Network references read from the session objects that name the network."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.managers.network_reference_manager import NetworkReferenceManager

NETWORK = "net-1"
OTHER = "net-2"


def _manager(
    *,
    networks=None,
    wlans=None,
    profiles=None,
    devices=None,
    policies=None,
    clients=None,
    wlan_error=None,
):
    network_manager = SimpleNamespace(
        get_networks=AsyncMock(return_value=networks if networks is not None else [{"_id": NETWORK, "name": "LAN"}]),
        get_wlans=AsyncMock(return_value=wlans or [], side_effect=wlan_error),
    )
    switch_manager = SimpleNamespace(get_port_profiles=AsyncMock(return_value=profiles or []))
    device_manager = SimpleNamespace(get_devices=AsyncMock(return_value=devices or []))
    firewall_manager = SimpleNamespace(get_firewall_policies=AsyncMock(return_value=policies or []))
    client_manager = SimpleNamespace(get_clients=AsyncMock(return_value=clients or []))
    return NetworkReferenceManager(
        MagicMock(),
        network_manager=network_manager,
        switch_manager=switch_manager,
        device_manager=device_manager,
        firewall_manager=firewall_manager,
        client_manager=client_manager,
    )


def _policy(policy_id, *, source=(), destination=()):
    return {
        "_id": policy_id,
        "name": policy_id,
        "source": {"network_ids": list(source)},
        "destination": {"network_ids": list(destination)},
    }


@pytest.mark.asyncio
async def test_unknown_network_is_not_found():
    manager = _manager()

    with pytest.raises(UniFiNotFoundError):
        await manager.get_network_references("missing")


@pytest.mark.asyncio
async def test_wlan_counts_when_a_private_preshared_key_names_the_network():
    manager = _manager(
        wlans=[
            {"_id": "wlan-1", "name": "Office", "networkconf_id": OTHER},
            {
                "_id": "wlan-2",
                "name": "Guests",
                "networkconf_id": OTHER,
                "private_preshared_keys": [{"networkconf_id": NETWORK, "password": "x"}],
            },
        ]
    )

    result = await manager.get_network_references(NETWORK)

    assert [entry["id"] for entry in result["references"]["wlans"]] == ["wlan-2"]
    assert result["counts"]["wlans"] == 1


@pytest.mark.asyncio
async def test_port_profile_reports_every_role():
    manager = _manager(
        profiles=[
            {"_id": "p-1", "name": "Native", "native_networkconf_id": NETWORK},
            {"_id": "p-2", "name": "Tagged", "tagged_networkconf_ids": [NETWORK]},
            {"_id": "p-3", "name": "Excluded", "excluded_networkconf_ids": [NETWORK]},
            {"_id": "p-4", "name": "Unrelated", "native_networkconf_id": OTHER},
        ]
    )

    result = await manager.get_network_references(NETWORK)

    assert [(entry["id"], entry["role"]) for entry in result["references"]["port_profiles"]] == [
        ("p-1", ["native"]),
        ("p-2", ["tagged"]),
        ("p-3", ["excluded"]),
    ]


@pytest.mark.asyncio
async def test_device_port_override_reports_the_port():
    manager = _manager(
        devices=[
            {
                "_id": "dev-1",
                "port_overrides": [
                    {"port_idx": 3, "native_networkconf_id": NETWORK},
                    {"port_idx": 4, "native_networkconf_id": OTHER},
                ],
            }
        ]
    )

    result = await manager.get_network_references(NETWORK)

    assert result["references"]["device_port_overrides"] == [{"device_id": "dev-1", "port_idx": 3, "role": ["native"]}]


@pytest.mark.asyncio
async def test_firewall_policy_direction_covers_both_sides():
    manager = _manager(
        policies=[
            _policy("p-src", source=[NETWORK]),
            _policy("p-dst", destination=[NETWORK]),
            _policy("p-both", source=[NETWORK], destination=[NETWORK]),
            _policy("p-none", source=[OTHER], destination=[OTHER]),
        ]
    )

    result = await manager.get_network_references(NETWORK)

    assert {entry["id"]: entry["direction"] for entry in result["references"]["firewall_policies"]} == {
        "p-src": "source",
        "p-dst": "destination",
        "p-both": "both",
    }


@pytest.mark.asyncio
async def test_clients_match_the_network_or_a_virtual_override():
    manager = _manager(
        clients=[
            {"mac": "aa:aa:aa:aa:aa:01", "network_id": NETWORK},
            {"mac": "aa:aa:aa:aa:aa:02", "virtual_network_override_id": NETWORK},
            {"mac": "aa:aa:aa:aa:aa:03", "network_id": OTHER},
        ]
    )

    result = await manager.get_network_references(NETWORK)

    assert [entry["mac"] for entry in result["references"]["clients"]] == [
        "aa:aa:aa:aa:aa:01",
        "aa:aa:aa:aa:aa:02",
    ]


@pytest.mark.asyncio
async def test_include_clients_false_skips_the_client_read():
    manager = _manager()

    result = await manager.get_network_references(NETWORK, include_clients=False)

    assert "clients" not in result["references"]
    assert "clients" not in result["counts"]
    assert manager._clients.get_clients.await_count == 0


@pytest.mark.asyncio
async def test_failed_family_is_unavailable_and_not_counted():
    manager = _manager(wlan_error=RuntimeError("boom"))

    result = await manager.get_network_references(NETWORK)

    assert result["unavailable"] == ["wlans"]
    assert "wlans" not in result["references"]
    assert "wlans" not in result["counts"]
    assert result["counts"]["port_profiles"] == 0


@pytest.mark.asyncio
async def test_empty_result_reports_zero_counts_for_every_family():
    manager = _manager()

    result = await manager.get_network_references(NETWORK)

    assert result["network_id"] == NETWORK
    assert result["name"] == "LAN"
    assert result["unavailable"] == []
    assert result["counts"] == {
        "wlans": 0,
        "port_profiles": 0,
        "device_port_overrides": 0,
        "firewall_policies": 0,
        "clients": 0,
    }
