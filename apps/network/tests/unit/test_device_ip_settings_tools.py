"""unifi_set_device_ip_settings: previews, writes and refusals."""

import copy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.managers.device_manager import DeviceManager

MAC = "aa:bb:cc:00:00:01"
CONFIG = {
    "type": "static",
    "ip": "192.0.2.20",
    "netmask": "255.255.255.0",
    "gateway": "192.0.2.1",
    "dns1": "192.0.2.1",
    "dns2": "",
    "bonding_enabled": False,
}
RAW = {
    "_id": "device-1",
    "mac": MAC,
    "name": "Hall AP",
    "model": "U7PRO",
    "type": "uap",
    "ip": "192.0.2.20",
    "config_network": CONFIG,
}


def _device_manager(raw=None, others=()) -> DeviceManager:
    """A real DeviceManager over one device record; writes go to a mock connection."""
    raw = copy.deepcopy(RAW if raw is None else raw)
    connection = MagicMock()
    connection.site = "default"
    connection.request = AsyncMock(return_value=[])
    manager = DeviceManager(connection)
    manager.get_device_details = AsyncMock(return_value=MagicMock(mac=MAC, raw=raw))
    manager.get_devices = AsyncMock(return_value=[raw, *others])
    return manager


def _sent(manager: DeviceManager):
    return [call[0][0] for call in manager._connection.request.call_args_list]


@pytest.mark.asyncio
async def test_preview_shows_current_and_requested_settings_without_writing():
    manager = _device_manager()
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import set_device_ip_settings

        result = await set_device_ip_settings(mac_address=MAC, mode="static", ip="192.0.2.21")

    assert result["success"] is True and result["requires_confirmation"] is True
    assert result["preview"]["current"]["ip"] == "192.0.2.20"
    assert result["preview"]["proposed"]["ip"] == "192.0.2.21"
    assert result["resource_name"] == "Hall AP"
    assert result["current_address"] == "192.0.2.20"
    warnings = " ".join(result["warnings"])
    assert "unreachable until it is reset" in warnings and "moves to 192.0.2.21" in warnings
    assert _sent(manager) == []


@pytest.mark.asyncio
async def test_preview_keeping_the_address_does_not_warn_of_a_move():
    manager = _device_manager()
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import set_device_ip_settings

        result = await set_device_ip_settings(mac_address=MAC, mode="static", dns2="198.51.100.53")

    assert result["preview"]["proposed"]["dns2"] == "198.51.100.53"
    assert not any("moves to" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_preview_of_a_switch_to_dhcp_says_where_the_address_comes_from():
    manager = _device_manager()
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import set_device_ip_settings

        result = await set_device_ip_settings(mac_address=MAC, mode="dhcp")

    assert result["preview"]["proposed"] == {"mode": "dhcp"}
    warnings = " ".join(result["warnings"])
    assert "from DHCP" in warnings and "unreachable" not in warnings and "moves to" not in warnings


@pytest.mark.asyncio
async def test_preview_of_the_current_settings_says_confirming_changes_nothing():
    manager = _device_manager()
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import set_device_ip_settings

        result = await set_device_ip_settings(mac_address=MAC, mode="static")

    assert result["message"] == "IP settings are already as requested; confirming changes nothing."
    assert not result.get("warnings")


@pytest.mark.asyncio
async def test_confirm_puts_config_network_with_only_the_given_fields_changed():
    manager = _device_manager()
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import set_device_ip_settings

        result = await set_device_ip_settings(mac_address=MAC, mode="static", dns2="198.51.100.53", confirm=True)

    assert result == {"success": True, "message": f"IP settings set to static on device '{MAC}'."}
    (request,) = _sent(manager)
    assert (request.method, request.path, request.data) == (
        "put",
        "/rest/device/device-1",
        {"config_network": {**CONFIG, "dns2": "198.51.100.53"}},
    )


@pytest.mark.asyncio
async def test_confirm_dhcp_writes_the_mode():
    manager = _device_manager()
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import set_device_ip_settings

        result = await set_device_ip_settings(mac_address=MAC, mode="dhcp", confirm=True)

    assert result["success"] is True
    (request,) = _sent(manager)
    assert request.data == {"config_network": {"type": "dhcp", "bonding_enabled": False}}


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm", [False, True])
@pytest.mark.parametrize(
    ("raw", "fields", "message"),
    [
        ({**RAW, "type": "udm"}, {"mode": "dhcp"}, "gateway's addresses"),
        (RAW, {"mode": "static", "gateway": "198.51.100.1"}, "outside 192.0.2.0/24"),
        (RAW, {"mode": "dhcp", "ip": "192.0.2.21"}, "DHCP takes no address fields"),
    ],
)
async def test_refused_changes_surface_the_reason_and_send_nothing(raw, fields, message, confirm):
    manager = _device_manager(raw)
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import set_device_ip_settings

        result = await set_device_ip_settings(mac_address=MAC, confirm=confirm, **fields)

    assert result["success"] is False
    assert message in result["error"]
    assert _sent(manager) == []


@pytest.mark.asyncio
async def test_another_devices_address_is_refused():
    manager = _device_manager(others=[{"mac": "aa:bb:cc:00:00:02", "name": "Desk switch", "ip": "192.0.2.30"}])
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import set_device_ip_settings

        result = await set_device_ip_settings(mac_address=MAC, mode="static", ip="192.0.2.30", confirm=True)

    assert result["success"] is False
    assert "another adopted device (Desk switch)" in result["error"]
    assert _sent(manager) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mac", "mode", "message"),
    [(MAC, "manual", "Input should be 'dhcp' or 'static'"), ("hall-ap", "dhcp", "must be a valid MAC address")],
)
async def test_invalid_input_is_rejected_before_any_read(mac, mode, message):
    manager = _device_manager()
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import set_device_ip_settings

        result = await set_device_ip_settings(mac_address=mac, mode=mode, confirm=True)

    assert result["success"] is False
    assert message in result["error"]
    manager.get_device_details.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_device_is_not_found():
    manager = _device_manager()
    manager.get_device_details = AsyncMock(side_effect=UniFiNotFoundError("device", MAC))
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import set_device_ip_settings

        result = await set_device_ip_settings(mac_address=MAC, mode="dhcp")

    assert result == {"success": False, "error": f"device '{MAC}' not found"}


@pytest.mark.asyncio
async def test_controller_failure_is_reported():
    manager = _device_manager()
    manager._connection.request = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import set_device_ip_settings

        result = await set_device_ip_settings(mac_address=MAC, mode="dhcp", confirm=True)

    assert result["success"] is False
    assert result["error"].startswith(f"Failed to set IP settings on {MAC}")
