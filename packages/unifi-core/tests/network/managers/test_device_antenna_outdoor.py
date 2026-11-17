"""AP antenna selection and outdoor mode: validation, preview data and the write payload."""

import copy
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from unifi_core.exceptions import UniFiNotFoundError, UniFiValidationError
from unifi_core.network.managers.device_manager import DeviceManager
from unifi_core.network.models._actions import SetDeviceOutdoorModeInput
from unifi_core.network.models.devices import (
    DEVICERADIO_MUTABLE_FIELDS,
    antenna_change,
    radio_from_controller,
    validate_radio_update,
)

MAC = "aa:bb:cc:00:00:01"
# Shapes as an outdoor AP with antenna options reports them: the selection is
# device-wide, so every radio carries the same antenna_id.
ANTENNA_TABLE = [
    {"id": 3, "name": "OMNI", "default": False, "wifi0_gain": 5, "wifi1_gain": 7},
    {"id": 4, "name": "Internal", "default": True, "wifi0_gain": 3, "wifi1_gain": 13},
    {"id": 5, "name": "UMA-D", "default": False, "wifi0_gain": 10, "wifi1_gain": 15},
]
RADIO_TABLE = [
    {"name": "wifi0", "radio": "ng", "channel": 6, "tx_power_mode": "auto", "antenna_id": 4},
    {"name": "wifi1", "radio": "na", "channel": 100, "tx_power_mode": "auto", "antenna_id": 4},
]
# A single-option AP reports antenna_id -1 on every radio.
COMBINED_TABLE = [{"id": 4, "name": "Combined", "default": True, "wifi0_gain": 4, "wifi1_gain": 6, "wifi2_gain": 6}]
COMBINED_RADIOS = [
    {"name": "wifi0", "radio": "ng", "antenna_id": -1},
    {"name": "wifi1", "radio": "na", "antenna_id": -1},
    {"name": "wifi2", "radio": "6e", "antenna_id": -1},
]


def _raw(**overrides):
    raw = {
        "_id": "device-1",
        "mac": MAC,
        "name": "Yard AP",
        "model": "UKPW",
        "type": "uap",
        "antenna_table": copy.deepcopy(ANTENNA_TABLE),
        "radio_table": copy.deepcopy(RADIO_TABLE),
        "outdoor_mode_override": "default",
    }
    raw.update(copy.deepcopy(overrides))
    return {key: value for key, value in raw.items() if value is not None}


def _manager(raw):
    connection = MagicMock()
    connection.request = AsyncMock(return_value=[])
    connection._invalidate_cache = MagicMock()
    manager = DeviceManager(connection)
    manager.get_device_details = AsyncMock(return_value=MagicMock(mac=raw["mac"], raw=raw))
    return manager, connection


# --- models -----------------------------------------------------------------------


def test_antenna_id_is_a_mutable_radio_field_read_from_the_radio_entry():
    assert "antenna_id" in DEVICERADIO_MUTABLE_FIELDS
    assert radio_from_controller(RADIO_TABLE[1]).antenna_id == 4


@pytest.mark.parametrize("antenna_id", [-1, True, "1"])
def test_radio_update_rejects_an_antenna_id_that_is_not_a_non_negative_int(antenna_id):
    with pytest.raises(ValueError, match="antenna_id must be a non-negative integer"):
        validate_radio_update("na", {"antenna_id": antenna_id})


def test_radio_update_keeps_a_valid_antenna_id():
    assert validate_radio_update("na", {"antenna_id": 2}) == {"antenna_id": 2}


def test_antenna_change_describes_the_device_antenna_with_per_radio_gains():
    assert antenna_change(_raw(), 3) == {
        "antenna_id": 3,
        "current": {"id": 4, "name": "Internal", "gain_dbi": {"ng": 3, "na": 13}},
        "requested": {"id": 3, "name": "OMNI", "gain_dbi": {"ng": 5, "na": 7}},
        "unchanged": False,
    }


@pytest.mark.parametrize("missing", [-1, None], ids=["minus-one", "absent"])
def test_minus_one_or_absent_antenna_id_means_the_default_option(missing):
    radios = [{**radio, "antenna_id": missing} for radio in RADIO_TABLE]

    change = antenna_change(_raw(radio_table=radios), 3)

    assert change["current"] == {"id": 4, "name": "Internal", "gain_dbi": {"ng": 3, "na": 13}}


def test_a_single_option_ap_on_minus_one_already_uses_its_only_antenna():
    change = antenna_change(_raw(antenna_table=COMBINED_TABLE, radio_table=COMBINED_RADIOS), 4)

    assert change["unchanged"] is True
    assert (
        change["current"]
        == change["requested"]
        == {
            "id": 4,
            "name": "Combined",
            "gain_dbi": {"ng": 4, "na": 6, "6e": 6},
        }
    )


def test_requesting_the_antenna_every_radio_uses_is_unchanged():
    assert antenna_change(_raw(), 4)["unchanged"] is True


def test_radios_on_different_antennas_are_shown_per_radio():
    radios = copy.deepcopy(RADIO_TABLE)
    radios[1]["antenna_id"] = 5

    change = antenna_change(_raw(radio_table=radios), 5)

    assert change["unchanged"] is False
    assert change["current"] == {
        "per_radio": {
            "ng": {"id": 4, "name": "Internal", "gain_dbi": {"ng": 3}},
            "na": {"id": 5, "name": "UMA-D", "gain_dbi": {"na": 15}},
        }
    }


def test_antenna_change_writes_the_id_as_the_controller_spells_it():
    table = [{**option, "id": str(option["id"])} for option in ANTENNA_TABLE]

    assert antenna_change(_raw(antenna_table=table), 5)["antenna_id"] == "5"


def test_a_device_without_an_antenna_table_refuses_antenna_id():
    raw = _raw()
    del raw["antenna_table"]

    with pytest.raises(ValueError, match="no selectable antennas"):
        antenna_change(raw, 4)


def test_an_unknown_antenna_id_names_the_choices():
    with pytest.raises(ValueError, match=r"Choose one of: 3 \(OMNI\), 4 \(Internal\), 5 \(UMA-D\)"):
        antenna_change(_raw(), 7)


def test_outdoor_mode_input_accepts_the_three_modes_only():
    assert SetDeviceOutdoorModeInput(device_mac=MAC, mode="on").mode == "on"
    with pytest.raises(ValidationError):
        SetDeviceOutdoorModeInput(device_mac=MAC, mode="auto")
    with pytest.raises(ValidationError):
        SetDeviceOutdoorModeInput(device_mac="yard-ap", mode="on")


# --- manager: antenna ----------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("radio", ["na", "ng", "wifi0"])
async def test_radio_update_writes_the_antenna_to_every_radio_in_one_put(radio):
    raw = _raw()
    manager, connection = _manager(raw)

    assert await manager.update_device_radio(MAC, radio, {"antenna_id": 3}) is True

    (call,) = connection.request.call_args_list
    request = call[0][0]
    assert (request.method, request.path) == ("put", "/rest/device/device-1")
    assert request.data == {
        "radio_table": [
            {"name": "wifi0", "radio": "ng", "channel": 6, "tx_power_mode": "auto", "antenna_id": 3},
            {"name": "wifi1", "radio": "na", "channel": 100, "tx_power_mode": "auto", "antenna_id": 3},
        ]
    }
    assert [radio["antenna_id"] for radio in raw["radio_table"]] == [4, 4]


@pytest.mark.asyncio
async def test_radio_update_with_antenna_and_channel_changes_the_channel_on_the_named_radio_only():
    manager, connection = _manager(_raw())

    assert await manager.update_device_radio(MAC, "na", {"antenna_id": 5, "channel": 36}) is True

    sent = connection.request.call_args[0][0].data["radio_table"]
    assert [(radio["channel"], radio["antenna_id"]) for radio in sent] == [(6, 5), (36, 5)]


@pytest.mark.asyncio
async def test_radio_update_to_the_current_antenna_sends_nothing():
    manager, connection = _manager(_raw(antenna_table=COMBINED_TABLE, radio_table=COMBINED_RADIOS))

    assert await manager.update_device_radio(MAC, "na", {"antenna_id": 4}) is True

    connection.request.assert_not_called()


@pytest.mark.asyncio
async def test_radio_update_to_the_current_antenna_still_applies_other_fields_without_touching_antenna_ids():
    manager, connection = _manager(_raw(antenna_table=COMBINED_TABLE, radio_table=COMBINED_RADIOS))

    assert await manager.update_device_radio(MAC, "na", {"antenna_id": 4, "channel": 36}) is True

    sent = connection.request.call_args[0][0].data["radio_table"]
    assert [radio["antenna_id"] for radio in sent] == [-1, -1, -1]
    assert sent[1]["channel"] == 36


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (_raw(antenna_table=[]), "no selectable antennas"),
        (_raw(), "is not one of this device's antennas"),
    ],
    ids=["no-antenna-table", "unknown-id"],
)
async def test_radio_update_refuses_an_invalid_antenna_before_writing(raw, message):
    manager, connection = _manager(raw)

    with pytest.raises(UniFiValidationError, match=message):
        await manager.update_device_radio(MAC, "na", {"antenna_id": 9})
    connection.request.assert_not_called()


@pytest.mark.asyncio
async def test_preview_radio_antenna_reads_without_writing():
    manager, connection = _manager(_raw())

    change = await manager.preview_radio_antenna(MAC, 5)

    assert change["requested"] == {"id": 5, "name": "UMA-D", "gain_dbi": {"ng": 10, "na": 15}}
    connection.request.assert_not_called()


@pytest.mark.asyncio
async def test_preview_radio_antenna_refuses_a_device_without_antennas():
    raw = _raw()
    del raw["antenna_table"]
    manager, _ = _manager(raw)

    with pytest.raises(UniFiValidationError, match="no selectable antennas"):
        await manager.preview_radio_antenna(MAC, 4)


@pytest.mark.asyncio
async def test_device_radio_lists_the_antennas_and_each_radio_selection():
    manager, _ = _manager(_raw())

    result = await manager.get_device_radio(MAC)

    assert result["antennas"] == ANTENNA_TABLE
    assert [radio["antenna_id"] for radio in result["radios"]] == [4, 4]


@pytest.mark.asyncio
async def test_device_radio_omits_antennas_when_the_device_has_none():
    raw = _raw(radio_table=[{"name": "wifi0", "radio": "ng"}])
    del raw["antenna_table"]
    manager, _ = _manager(raw)

    result = await manager.get_device_radio(MAC)

    assert "antennas" not in result
    assert "antenna_id" not in result["radios"][0]


# --- manager: outdoor mode ---------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["on", "off"])
async def test_outdoor_mode_writes_the_one_field(mode):
    manager, connection = _manager(_raw())

    assert await manager.set_device_outdoor_mode(MAC, mode) is True

    request = connection.request.call_args[0][0]
    assert (request.method, request.path, request.data) == (
        "put",
        "/rest/device/device-1",
        {"outdoor_mode_override": mode},
    )
    connection._invalidate_cache.assert_called_once()


@pytest.mark.asyncio
async def test_outdoor_mode_already_set_sends_nothing():
    manager, connection = _manager(_raw(outdoor_mode_override="on"))

    assert await manager.set_device_outdoor_mode(MAC, "on") is True

    connection.request.assert_not_called()


@pytest.mark.asyncio
async def test_outdoor_mode_reads_the_current_value():
    manager, _ = _manager(_raw(outdoor_mode_override="on"))

    assert await manager.get_device_outdoor_mode(MAC) == {
        "mac": MAC,
        "name": "Yard AP",
        "model": "UKPW",
        "outdoor_mode_override": "on",
    }


@pytest.mark.asyncio
async def test_outdoor_mode_refuses_a_device_without_the_field():
    raw = _raw(type="usw", model="USW-24")
    del raw["outdoor_mode_override"]
    manager, connection = _manager(raw)

    with pytest.raises(UniFiValidationError, match="does not report outdoor_mode_override"):
        await manager.set_device_outdoor_mode(MAC, "on")
    with pytest.raises(UniFiValidationError):
        await manager.get_device_outdoor_mode(MAC)
    connection.request.assert_not_called()


@pytest.mark.asyncio
async def test_outdoor_mode_refuses_an_unknown_mode_before_any_read():
    manager, connection = _manager(_raw())

    with pytest.raises(UniFiValidationError, match="Invalid outdoor mode"):
        await manager.set_device_outdoor_mode(MAC, "auto")
    manager.get_device_details.assert_not_called()
    connection.request.assert_not_called()


@pytest.mark.asyncio
async def test_outdoor_mode_on_an_unknown_device_is_not_found():
    manager, connection = _manager(_raw())
    manager.get_device_details = AsyncMock(side_effect=UniFiNotFoundError("device", MAC))

    with pytest.raises(UniFiNotFoundError):
        await manager.set_device_outdoor_mode(MAC, "on")
    connection.request.assert_not_called()
