"""Device IP settings: validation, the config_network written and the preview."""

import copy
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from unifi_core.exceptions import UniFiNotFoundError, UniFiValidationError
from unifi_core.network.managers.device_manager import DeviceManager
from unifi_core.network.models._actions import SetDeviceIpSettingsInput
from unifi_core.network.models.devices import ip_settings_change, ip_settings_view

MAC = "aa:bb:cc:00:00:01"
OTHER_MAC = "aa:bb:cc:00:00:02"
STATIC = {
    "type": "static",
    "ip": "192.0.2.20",
    "netmask": "255.255.255.0",
    "gateway": "192.0.2.1",
    "dns1": "192.0.2.1",
    "dns2": "198.51.100.53",
    "dnssuffix": "",
    "bonding_enabled": False,
}
# A device in DHCP mode can keep the stale address it last had statically.
DHCP = {"type": "dhcp", "ip": "192.0.2.77", "bonding_enabled": False}


def _raw(config=STATIC, **overrides):
    raw = {
        "_id": "device-1",
        "mac": MAC,
        "name": "Hall AP",
        "model": "U7PRO",
        "type": "uap",
        "ip": "192.0.2.20",
        "config_network": copy.deepcopy(config),
    }
    raw.update(copy.deepcopy(overrides))
    return {key: value for key, value in raw.items() if value is not None}


def _manager(raw, others=()):
    connection = MagicMock()
    connection.request = AsyncMock(return_value=[])
    connection._invalidate_cache = MagicMock()
    manager = DeviceManager(connection)
    manager.get_device_details = AsyncMock(return_value=MagicMock(mac=raw["mac"], raw=raw))
    manager.get_devices = AsyncMock(return_value=[raw, *others])
    return manager, connection


# --- models -----------------------------------------------------------------------


def test_view_shows_static_fields_and_hides_a_dhcp_devices_stale_address():
    shown = {key: STATIC[key] for key in ("ip", "netmask", "gateway", "dns1", "dns2")}
    assert ip_settings_view(STATIC) == {"mode": "static", **shown}
    assert ip_settings_view(DHCP) == {"mode": "dhcp"}


def test_static_change_keeps_unset_fields_and_carries_other_keys():
    change = ip_settings_change(_raw(), "static", dns2="203.0.113.53")

    assert change["config_network"] == {**STATIC, "dns2": "203.0.113.53"}
    assert change["current"]["dns2"] == "198.51.100.53"
    assert change["requested"]["dns2"] == "203.0.113.53"
    assert change["unchanged"] is False


def test_static_change_writes_a_prefix_netmask_dotted():
    change = ip_settings_change(_raw(DHCP), "static", ip="192.0.2.30", netmask="24", gateway="192.0.2.1")

    assert change["config_network"] == {
        "type": "static",
        "ip": "192.0.2.30",
        "netmask": "255.255.255.0",
        "gateway": "192.0.2.1",
        "bonding_enabled": False,
    }
    assert change["current"] == {"mode": "dhcp"}


def test_switching_from_dhcp_does_not_reuse_the_stale_address():
    with pytest.raises(ValueError, match="need ip, netmask, gateway"):
        ip_settings_change(_raw(DHCP), "static")


def test_dhcp_change_writes_the_mode_and_other_keys_only():
    change = ip_settings_change(_raw(), "dhcp")

    assert change["config_network"] == {"type": "dhcp", "bonding_enabled": False}
    assert change["requested"] == {"mode": "dhcp"}


def test_an_empty_dns_clears_it():
    change = ip_settings_change(_raw(), "static", dns2="")

    assert change["config_network"]["dns2"] == ""
    assert "dns2" not in change["requested"]


@pytest.mark.parametrize(
    ("config", "mode", "fields"),
    [(STATIC, "static", {}), (STATIC, "static", {"ip": "192.0.2.20", "netmask": "/24"}), (DHCP, "dhcp", {})],
)
def test_the_same_settings_are_unchanged(config, mode, fields):
    assert ip_settings_change(_raw(config), mode, **fields)["unchanged"] is True


@pytest.mark.parametrize(
    ("raw", "mode", "fields", "message"),
    [
        (_raw(type="udm"), "static", {}, "gateway's addresses"),
        (_raw(type="ugw"), "dhcp", {}, "gateway's addresses"),
        (_raw(config=None), "dhcp", {}, "reports no IP settings"),
        (_raw(), "manual", {}, "Invalid mode"),
        (_raw(), "dhcp", {"ip": "192.0.2.30"}, "DHCP takes no address fields"),
        (_raw(), "static", {"ip": "192.0.2.300"}, "ip '192.0.2.300' is not an IPv4"),
        (_raw(), "static", {"ip": "2001:db8::1"}, "not an IPv4"),
        (_raw(), "static", {"gateway": "router"}, "gateway 'router' is not an IPv4"),
        (_raw(), "static", {"netmask": "255.0.255.0"}, "is not an IPv4 netmask"),
        (_raw(), "static", {"netmask": "31"}, "leaves no room"),
        (_raw(), "static", {"ip": "192.0.2.0"}, "network or broadcast"),
        (_raw(), "static", {"ip": "192.0.2.255"}, "network or broadcast"),
        (_raw(), "static", {"gateway": "198.51.100.1"}, "outside 192.0.2.0/24"),
        (_raw(), "static", {"ip": "192.0.2.1"}, "the same address"),
        (_raw(), "static", {"dns1": "dns.example"}, "dns1 'dns.example'"),
    ],
)
def test_change_refuses(raw, mode, fields, message):
    with pytest.raises(ValueError, match=message):
        ip_settings_change(raw, mode, **fields)


def test_input_accepts_the_two_modes_and_a_mac_only():
    assert SetDeviceIpSettingsInput(device_mac=MAC, mode="dhcp").mode == "dhcp"
    with pytest.raises(ValidationError):
        SetDeviceIpSettingsInput(device_mac=MAC, mode="manual")
    with pytest.raises(ValidationError):
        SetDeviceIpSettingsInput(device_mac="hall-ap", mode="dhcp")


# --- manager ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_returns_the_address_and_settings():
    manager, _ = _manager(_raw())

    result = await manager.get_device_ip_settings(MAC)

    assert result == {
        "mac": MAC,
        "name": "Hall AP",
        "model": "U7PRO",
        "ip": "192.0.2.20",
        "ip_settings": ip_settings_view(STATIC),
    }


@pytest.mark.asyncio
async def test_read_refuses_a_device_without_settings():
    manager, _ = _manager(_raw(config=None))

    with pytest.raises(UniFiValidationError, match="no IP settings"):
        await manager.get_device_ip_settings(MAC)


@pytest.mark.asyncio
async def test_preview_describes_the_change_without_writing():
    manager, connection = _manager(_raw())

    preview = await manager.preview_device_ip_settings(MAC, "static", ip="192.0.2.21")

    assert preview["ip"] == "192.0.2.20"
    assert (preview["current"]["ip"], preview["requested"]["ip"]) == ("192.0.2.20", "192.0.2.21")
    connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_writes_config_network_and_invalidates_the_device_cache():
    manager, connection = _manager(_raw())

    assert await manager.set_device_ip_settings(MAC, "static", dns2="203.0.113.53") is True

    (call,) = connection.request.await_args_list
    request = call.args[0]
    assert (request.method, request.path) == ("put", "/rest/device/device-1")
    assert request.data == {"config_network": {**STATIC, "dns2": "203.0.113.53"}}
    connection._invalidate_cache.assert_called_once()


@pytest.mark.asyncio
async def test_set_with_nothing_to_change_sends_nothing():
    manager, connection = _manager(_raw())

    assert await manager.set_device_ip_settings(MAC, "static") is True
    connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_refuses_another_devices_address():
    other = {"_id": "device-2", "mac": OTHER_MAC.upper(), "name": "Desk switch", "ip": "192.0.2.21"}
    manager, connection = _manager(_raw(), others=[other])

    with pytest.raises(UniFiValidationError, match="another adopted device \\(Desk switch\\)"):
        await manager.set_device_ip_settings(MAC, "static", ip="192.0.2.21")
    connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_keeps_its_own_address_without_a_conflict():
    manager, connection = _manager(_raw(), others=[{"mac": OTHER_MAC, "ip": "192.0.2.21"}])

    assert await manager.set_device_ip_settings(MAC, "static", ip="192.0.2.20", dns1="192.0.2.2") is True
    connection.request.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_refusal_is_a_validation_error_and_sends_nothing():
    manager, connection = _manager(_raw(type="udm"))

    with pytest.raises(UniFiValidationError, match="gateway"):
        await manager.set_device_ip_settings(MAC, "dhcp")
    connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_device_is_not_found():
    manager, _ = _manager(_raw())
    manager.get_device_details = AsyncMock(side_effect=UniFiNotFoundError("device", MAC))

    with pytest.raises(UniFiNotFoundError):
        await manager.preview_device_ip_settings(MAC, "dhcp")
