"""Tool-layer behavior of merged switch port overrides and fixed IP reservations."""

from __future__ import annotations

import importlib
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

MAC = "aa:bb:cc:dd:ee:ff"
CURRENT = [
    {"port_idx": 1, "name": "uplink", "portconf_id": "trunk"},
    {"port_idx": 2, "name": "printer", "portconf_id": "office"},
]


def _switch_manager(plan: dict | None = None, error: Exception | None = None) -> MagicMock:
    manager = MagicMock()
    manager.plan_port_overrides = AsyncMock(return_value=plan, side_effect=error)
    manager.set_port_overrides = AsyncMock(return_value=True)
    return manager


def _plan(merged: list[dict], changed=(), added=(), removed=(), kept=()) -> dict:
    # Independent copies: expected values in the tests must not share objects with the mocked plan.
    return {
        "current": deepcopy(CURRENT),
        "merged": deepcopy(merged),
        "changed_ports": list(changed),
        "added_ports": list(added),
        "removed_ports": list(removed),
        "kept_ports": list(kept),
    }


@pytest.mark.asyncio
async def test_switch_preview_shows_current_and_proposed_entries_without_writing():
    switch = importlib.import_module("unifi_network_mcp.tools.switch")
    proposed = {"port_idx": 2, "portconf_id": "cameras"}
    manager = _switch_manager(_plan([CURRENT[0], proposed, {"port_idx": 4}], changed=[2], added=[4], kept=[1]))

    with patch.object(switch, "switch_manager", manager):
        result = await switch.set_switch_port_profile(
            mac_address=MAC, port_overrides=[proposed, {"port_idx": 4}], remove_port_idxs=None
        )

    data = result["preview"]["will_create"]
    assert data["changed_ports"] == [{"port_idx": 2, "current": CURRENT[1], "proposed": proposed}]
    assert data["added_ports"] == [{"port_idx": 4}]
    assert data["removed_ports"] == []
    assert data["unchanged_port_count"] == 1
    manager.set_port_overrides.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("function", ["set_switch_port_profile", "configure_port_mirror", "configure_port_aggregation"])
async def test_switch_writes_pass_removals_through(function: str):
    switch = importlib.import_module("unifi_network_mcp.tools.switch")
    manager = _switch_manager()

    with patch.object(switch, "switch_manager", manager):
        result = await getattr(switch, function)(mac_address=MAC, port_overrides=[], remove_port_idxs=[3], confirm=True)

    assert result["success"] is True
    manager.set_port_overrides.assert_awaited_once_with(MAC, [], remove_port_idxs=[3])


@pytest.mark.asyncio
async def test_a_refused_change_says_why():
    switch = importlib.import_module("unifi_network_mcp.tools.switch")
    manager = _switch_manager(error=ValueError("Port 5 has no override to remove."))

    with patch.object(switch, "switch_manager", manager):
        result = await switch.set_switch_port_profile(mac_address=MAC, port_overrides=[], remove_port_idxs=[5])

    assert result == {"success": False, "error": "Failed to set port overrides: Port 5 has no override to remove."}


@pytest.mark.asyncio
@pytest.mark.parametrize(("member_entry", "warned"), [(True, True), (False, False)])
async def test_aggregation_preview_names_member_ports_that_keep_an_override(member_entry: bool, warned: bool):
    switch = importlib.import_module("unifi_network_mcp.tools.switch")
    master = {"port_idx": 1, "op_mode": "aggregate", "aggregate_members": [1, 2], "lag_idx": 1}
    merged = [master, CURRENT[1]] if member_entry else [master]
    manager = _switch_manager(_plan(merged, changed=[1], kept=[2] if member_entry else []))

    with patch.object(switch, "switch_manager", manager):
        result = await switch.configure_port_aggregation(mac_address=MAC, port_overrides=[master])

    warnings = result.get("warnings", [])
    assert bool(warnings) is warned
    if warned:
        assert "Member port(s) 2" in warnings[0] and "remove_port_idxs" in warnings[0]


def _client_manager(client: dict, network: dict | None = None, error: Exception | None = None) -> MagicMock:
    manager = MagicMock()
    manager.get_client_details = AsyncMock(return_value=SimpleNamespace(raw=client))
    manager.resolve_fixed_ip_network = AsyncMock(return_value=network, side_effect=error)
    manager.set_client_ip_settings = AsyncMock(return_value=True)
    return manager


IOT = {"network_id": "iot", "name": "IoT", "subnet": "10.20.0.0/24"}


@pytest.mark.asyncio
@pytest.mark.parametrize(("client_network", "warned"), [("lan", True), ("iot", False), (None, False)])
async def test_ip_preview_shows_the_reservation_network_and_warns_on_a_mismatch(client_network, warned):
    clients = importlib.import_module("unifi_network_mcp.tools.clients")
    client = {"_id": "u1", "mac": MAC, "name": "cam", "network": "LAN", "network_id": client_network}
    manager = _client_manager(client, IOT)

    with patch.object(clients, "client_manager", manager):
        result = await clients.set_client_ip_settings(mac_address=MAC, use_fixedip=True, fixed_ip="10.20.0.50")

    manager.resolve_fixed_ip_network.assert_awaited_once_with("10.20.0.50", None)
    assert "iot" in str(result["preview"]) and "IoT" in str(result["preview"])
    assert bool(result.get("warnings")) is warned
    manager.set_client_ip_settings.assert_not_awaited()


@pytest.mark.asyncio
async def test_ip_preview_reports_an_address_without_a_network():
    clients = importlib.import_module("unifi_network_mcp.tools.clients")
    manager = _client_manager(
        {"_id": "u1", "mac": MAC}, error=ValueError("No configured network contains the fixed IP")
    )

    with patch.object(clients, "client_manager", manager):
        result = await clients.set_client_ip_settings(mac_address=MAC, fixed_ip="172.16.0.5")

    assert result["success"] is False and "No configured network contains" in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "warned"),
    [({}, True), ({"local_dns_record_enabled": False}, False)],
    ids=["dns-stays-on", "dns-turned-off"],
)
async def test_ip_preview_warns_before_a_release_the_controller_refuses(kwargs, warned):
    clients = importlib.import_module("unifi_network_mcp.tools.clients")
    client = {"_id": "u1", "mac": MAC, "use_fixedip": True, "fixed_ip": "10.0.0.5", "local_dns_record_enabled": True}
    manager = _client_manager(client)

    with patch.object(clients, "client_manager", manager):
        result = await clients.set_client_ip_settings(mac_address=MAC, use_fixedip=False, **kwargs)

    assert any("local DNS record" in w for w in result.get("warnings", [])) is warned
    manager.resolve_fixed_ip_network.assert_not_awaited()


@pytest.mark.asyncio
async def test_ip_write_passes_the_network_through():
    clients = importlib.import_module("unifi_network_mcp.tools.clients")
    manager = _client_manager({"_id": "u1", "mac": MAC})

    with patch.object(clients, "client_manager", manager):
        result = await clients.set_client_ip_settings(
            mac_address=MAC, fixed_ip="10.20.0.50", network_id="iot", confirm=True
        )

    assert result["success"] is True
    assert manager.set_client_ip_settings.await_args.kwargs["network_id"] == "iot"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("record", "warned"),
    [
        # Offline record: network_id is the saved reservation's network, last_connection is where it connects.
        ({"network_id": "iot", "last_connection_network_id": "lan", "last_connection_network_name": "LAN"}, True),
        ({"network_id": "lan", "last_connection_network_id": "iot"}, False),
        # A reservation's network_id alone says nothing about where the client connects.
        ({"use_fixedip": True, "fixed_ip": "10.0.0.9", "network_id": "lan"}, False),
    ],
    ids=["reservation-iot-last-lan", "reservation-lan-last-iot", "reservation-only"],
)
async def test_ip_preview_compares_with_the_last_connected_network_not_the_reservation(record, warned):
    clients = importlib.import_module("unifi_network_mcp.tools.clients")
    manager = _client_manager({"_id": "u1", "mac": MAC, **record}, IOT)

    with patch.object(clients, "client_manager", manager):
        result = await clients.set_client_ip_settings(mac_address=MAC, use_fixedip=True, fixed_ip="10.20.0.50")

    assert bool(result.get("warnings")) is warned


@pytest.mark.asyncio
async def test_ip_preview_treats_an_empty_dns_hostname_as_enabling_dns_like_core():
    clients = importlib.import_module("unifi_network_mcp.tools.clients")
    client = {"_id": "u1", "mac": MAC, "use_fixedip": True, "fixed_ip": "10.0.0.5", "local_dns_record_enabled": False}
    manager = _client_manager(client)

    with patch.object(clients, "client_manager", manager):
        result = await clients.set_client_ip_settings(mac_address=MAC, use_fixedip=False, local_dns_record="")

    assert any("local DNS record" in w for w in result.get("warnings", []))


@pytest.mark.asyncio
async def test_ip_preview_shows_the_current_reservation_network():
    clients = importlib.import_module("unifi_network_mcp.tools.clients")
    client = {"_id": "u1", "mac": MAC, "use_fixedip": True, "fixed_ip": "192.168.1.9", "network_id": "lan"}
    manager = _client_manager(client, IOT)

    with patch.object(clients, "client_manager", manager):
        result = await clients.set_client_ip_settings(mac_address=MAC, fixed_ip="10.20.0.50")

    assert "'network_id': 'lan'" in str(result["preview"]) and "'network_id': 'iot'" in str(result["preview"])
