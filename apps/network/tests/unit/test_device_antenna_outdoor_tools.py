"""unifi_update_device_radio antenna_id and unifi_set_device_outdoor_mode: previews, writes and refusals."""

import copy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.managers.device_manager import DeviceManager

MAC = "aa:bb:cc:00:00:01"
RAW = {
    "_id": "device-1",
    "mac": MAC,
    "name": "Yard AP",
    "model": "UKPW",
    "type": "uap",
    "antenna_table": [
        {"id": 3, "name": "OMNI", "default": False, "wifi0_gain": 5, "wifi1_gain": 7},
        {"id": 4, "name": "Internal", "default": True, "wifi0_gain": 3, "wifi1_gain": 13},
    ],
    "radio_table": [
        {"name": "wifi0", "radio": "ng", "channel": 6, "tx_power_mode": "auto", "antenna_id": 4},
        {"name": "wifi1", "radio": "na", "channel": 100, "tx_power_mode": "auto", "antenna_id": 4},
    ],
    "outdoor_mode_override": "default",
}


def _device_manager(raw=None) -> DeviceManager:
    """A real DeviceManager over one device record; writes go to a mock connection."""
    raw = copy.deepcopy(RAW if raw is None else raw)
    connection = MagicMock()
    connection.site = "default"
    connection.request = AsyncMock(return_value=[])
    manager = DeviceManager(connection)
    manager.get_device_details = AsyncMock(return_value=MagicMock(mac=MAC, raw=raw))
    return manager


def _sent(manager: DeviceManager):
    return [call[0][0] for call in manager._connection.request.call_args_list]


# --- antenna_id on unifi_update_device_radio -------------------------------------------------


@pytest.mark.asyncio
async def test_radio_preview_shows_the_device_antenna_with_per_radio_gains_before_and_after():
    manager = _device_manager()
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import update_device_radio

        result = await update_device_radio(mac_address=MAC, radio="na", antenna_id=3)

    assert result["success"] is True and result["requires_confirmation"] is True
    preview = result["preview"]
    assert preview["current"] == {
        "antenna_id": 4,
        "antenna": {"id": 4, "name": "Internal", "gain_dbi": {"ng": 3, "na": 13}},
    }
    assert preview["proposed"] == {
        "antenna_id": 3,
        "antenna": {"id": 3, "name": "OMNI", "gain_dbi": {"ng": 5, "na": 7}},
    }
    assert len(result["warnings"]) == 3
    assert result["warnings"][2] == "The antenna is device-wide: the change applies to every radio on this device."
    assert _sent(manager) == []


@pytest.mark.asyncio
async def test_radio_preview_of_the_current_antenna_says_confirming_changes_nothing():
    manager = _device_manager()
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import update_device_radio

        result = await update_device_radio(mac_address=MAC, radio="ng", antenna_id=4)

    assert result["message"] == "Yard AP already uses antenna 'Internal' on every radio; confirming changes nothing."
    assert result["warnings"] == []


@pytest.mark.asyncio
async def test_radio_preview_of_the_current_antenna_with_another_change_is_a_normal_preview():
    manager = _device_manager()
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import update_device_radio

        result = await update_device_radio(mac_address=MAC, radio="na", antenna_id=4, channel=36)

    assert "confirming changes nothing" not in result["message"]
    assert result["preview"]["proposed"]["channel"] == 36


@pytest.mark.asyncio
@pytest.mark.parametrize("radio", ["na", "ng"])
async def test_radio_confirm_writes_the_antenna_to_every_radio(radio):
    manager = _device_manager()
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import update_device_radio

        result = await update_device_radio(mac_address=MAC, radio=radio, antenna_id=3, confirm=True)

    assert result["success"] is True, result
    (request,) = _sent(manager)
    assert [entry["antenna_id"] for entry in request.data["radio_table"]] == [3, 3]


@pytest.mark.asyncio
async def test_radio_confirm_of_the_current_antenna_sends_nothing():
    manager = _device_manager()
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import update_device_radio

        result = await update_device_radio(mac_address=MAC, radio="na", antenna_id=4, confirm=True)

    assert result["success"] is True
    assert _sent(manager) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("radio_table", [[], [{"name": "wifi0", "radio": "ng"}]], ids=["no-radios", "one-radio"])
async def test_radio_antenna_without_antenna_table_reports_that_before_the_radio_lookup(radio_table):
    raw = {**copy.deepcopy(RAW), "radio_table": radio_table}
    del raw["antenna_table"]
    manager = _device_manager(raw)
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import update_device_radio

        result = await update_device_radio(mac_address=MAC, radio="na", antenna_id=4)

    assert result["success"] is False
    assert result["error"].startswith("This device has no selectable antennas")


@pytest.mark.asyncio
async def test_radio_lookup_on_a_device_without_radios_says_so():
    raw = {**copy.deepcopy(RAW), "radio_table": []}
    manager = _device_manager(raw)
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import update_device_radio

        result = await update_device_radio(mac_address=MAC, radio="na", channel=36)

    assert result == {"success": False, "error": "Radio 'na' not found on device. This device reports no radios."}


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm", [False, True])
async def test_radio_antenna_on_a_device_without_antennas_is_refused(confirm):
    raw = copy.deepcopy(RAW)
    del raw["antenna_table"]
    manager = _device_manager(raw)
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import update_device_radio

        result = await update_device_radio(mac_address=MAC, radio="na", antenna_id=4, confirm=confirm)

    assert result == {
        "success": False,
        "error": "This device has no selectable antennas (it reports no antenna_table), so antenna_id cannot be set.",
    }
    assert _sent(manager) == []


@pytest.mark.asyncio
async def test_radio_unknown_antenna_id_lists_the_choices():
    manager = _device_manager()
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import update_device_radio

        result = await update_device_radio(mac_address=MAC, radio="na", antenna_id=5)

    assert result["success"] is False
    assert result["error"].endswith("Choose one of: 3 (OMNI), 4 (Internal).")


@pytest.mark.asyncio
async def test_radio_negative_antenna_id_fails_validation_without_a_read():
    manager = _device_manager()
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import update_device_radio

        result = await update_device_radio(mac_address=MAC, radio="na", antenna_id=-1)

    assert result["success"] is False
    assert "antenna_id must be a non-negative integer" in result["error"]
    manager.get_device_details.assert_not_called()


# --- unifi_set_device_outdoor_mode ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_outdoor_preview_shows_the_current_value_without_writing():
    manager = _device_manager()
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import set_device_outdoor_mode

        result = await set_device_outdoor_mode(mac_address=MAC, mode="on")

    assert result["success"] is True and result["requires_confirmation"] is True
    assert result["preview"]["current"] == {"outdoor_mode_override": "default"}
    assert result["preview"]["proposed"] == {"outdoor_mode_override": "on"}
    assert result["resource_name"] == "Yard AP"
    assert _sent(manager) == []


@pytest.mark.asyncio
async def test_outdoor_preview_of_the_current_value_says_confirming_changes_nothing():
    manager = _device_manager()
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import set_device_outdoor_mode

        result = await set_device_outdoor_mode(mac_address=MAC, mode="default")

    assert result["message"] == "Outdoor mode override is already 'default'; confirming changes nothing."
    assert not result.get("warnings")


@pytest.mark.asyncio
async def test_outdoor_confirm_of_the_current_value_sends_nothing():
    manager = _device_manager()
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import set_device_outdoor_mode

        result = await set_device_outdoor_mode(mac_address=MAC, mode="default", confirm=True)

    assert result["success"] is True
    assert _sent(manager) == []


@pytest.mark.asyncio
async def test_outdoor_confirm_puts_the_one_field():
    manager = _device_manager()
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import set_device_outdoor_mode

        result = await set_device_outdoor_mode(mac_address=MAC, mode="off", confirm=True)

    assert result == {"success": True, "message": f"Outdoor mode override set to 'off' on device '{MAC}'."}
    (request,) = _sent(manager)
    assert (request.method, request.path, request.data) == (
        "put",
        "/rest/device/device-1",
        {"outdoor_mode_override": "off"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm", [False, True])
async def test_outdoor_mode_refuses_a_device_without_the_field(confirm):
    raw = copy.deepcopy(RAW)
    del raw["outdoor_mode_override"]
    manager = _device_manager(raw)
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import set_device_outdoor_mode

        result = await set_device_outdoor_mode(mac_address=MAC, mode="on", confirm=confirm)

    assert result["success"] is False
    assert "does not report outdoor_mode_override" in result["error"]
    assert _sent(manager) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mac", "mode", "message"),
    [(MAC, "auto", "Input should be 'default', 'on' or 'off'"), ("yard-ap", "on", "must be a valid MAC address")],
)
async def test_outdoor_mode_rejects_invalid_input_before_any_read(mac, mode, message):
    manager = _device_manager()
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import set_device_outdoor_mode

        result = await set_device_outdoor_mode(mac_address=mac, mode=mode, confirm=True)

    assert result["success"] is False
    assert message in result["error"]
    manager.get_device_details.assert_not_called()


@pytest.mark.asyncio
async def test_outdoor_mode_on_an_unknown_device_is_not_found():
    manager = _device_manager()
    manager.get_device_details = AsyncMock(side_effect=UniFiNotFoundError("device", MAC))
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import set_device_outdoor_mode

        result = await set_device_outdoor_mode(mac_address=MAC, mode="on")

    assert result == {"success": False, "error": f"device '{MAC}' not found"}


@pytest.mark.asyncio
async def test_outdoor_mode_controller_failure_is_reported():
    manager = _device_manager()
    manager._connection.request = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("unifi_network_mcp.tools.devices.device_manager", manager):
        from unifi_network_mcp.tools.devices import set_device_outdoor_mode

        result = await set_device_outdoor_mode(mac_address=MAC, mode="on", confirm=True)

    assert result["success"] is False
    assert result["error"].startswith(f"Failed to set outdoor mode on {MAC}")
