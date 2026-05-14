"""Unit tests for the Network Device + DeviceRadio CRUD domain models."""

from __future__ import annotations

from unifi_core.network.models.devices import (
    DEVICE_MUTABLE_FIELDS,
    DEVICE_READ_ONLY_FIELDS,
    DEVICERADIO_MUTABLE_FIELDS,
    DEVICERADIO_READ_ONLY_FIELDS,
    Device,
    DeviceRadio,
    from_controller,
    radio_from_controller,
    radio_to_controller_update,
    to_controller_update,
)


class TestDeviceFieldSets:
    def test_mutable_fields_contains_name(self) -> None:
        assert "name" in DEVICE_MUTABLE_FIELDS

    def test_mutable_fields_excludes_mac_and_model(self) -> None:
        for field in ("mac", "model", "type", "version", "uptime", "state", "ip"):
            assert field not in DEVICE_MUTABLE_FIELDS, f"{field!r} should NOT be in DEVICE_MUTABLE_FIELDS"

    def test_read_only_fields_contains_mac(self) -> None:
        assert "mac" in DEVICE_READ_ONLY_FIELDS

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = DEVICE_MUTABLE_FIELDS & DEVICE_READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_cover_all_model_fields(self) -> None:
        all_fields = frozenset(Device.model_fields.keys())
        assert DEVICE_MUTABLE_FIELDS | DEVICE_READ_ONLY_FIELDS == all_fields


class TestDeviceRadioFieldSets:
    def test_mutable_fields_contains_update_schema_fields(self) -> None:
        for field in (
            "tx_power_mode",
            "tx_power",
            "channel",
            "ht",
            "min_rssi_enabled",
            "min_rssi",
            "assisted_roaming_enabled",
            "antenna_gain",
            "vwire_enabled",
            "sens_level_enabled",
            "sens_level",
        ):
            assert field in DEVICERADIO_MUTABLE_FIELDS, f"Expected {field!r} in DEVICERADIO_MUTABLE_FIELDS"

    def test_mutable_fields_excludes_radio(self) -> None:
        assert "radio" not in DEVICERADIO_MUTABLE_FIELDS

    def test_read_only_fields_contains_radio(self) -> None:
        assert "radio" in DEVICERADIO_READ_ONLY_FIELDS

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = DEVICERADIO_MUTABLE_FIELDS & DEVICERADIO_READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_cover_all_model_fields(self) -> None:
        all_fields = frozenset(DeviceRadio.model_fields.keys())
        assert DEVICERADIO_MUTABLE_FIELDS | DEVICERADIO_READ_ONLY_FIELDS == all_fields


class TestFromControllerDevice:
    def test_full_device(self) -> None:
        raw = {
            "mac": "aa:bb:cc:dd:ee:ff",
            "name": "Office AP",
            "model": "U6-Pro",
            "type": "uap",
            "version": "6.0.22",
            "uptime": 86400,
            "state": 1,
            "ip": "192.168.1.10",
        }
        device = from_controller(raw)
        assert device.mac == "aa:bb:cc:dd:ee:ff"
        assert device.name == "Office AP"
        assert device.model == "U6-Pro"
        assert device.type == "uap"
        assert device.version == "6.0.22"
        assert device.uptime == 86400
        assert device.state == "connected"
        assert device.ip == "192.168.1.10"

    def test_state_mapping(self) -> None:
        assert from_controller({"state": 0}).state == "disconnected"
        assert from_controller({"state": 1}).state == "connected"
        assert from_controller({"state": 5}).state == "provisioning"

    def test_unknown_state_becomes_string(self) -> None:
        device = from_controller({"state": 99})
        assert device.state == "99"

    def test_handles_empty_dict(self) -> None:
        device = from_controller({})
        assert device.mac is None
        assert device.name is None
        assert device.state is None


class TestDeviceToControllerUpdate:
    def test_allows_name_update(self) -> None:
        result = to_controller_update({"name": "New Name"})
        assert result == {"name": "New Name"}

    def test_drops_read_only_fields(self) -> None:
        result = to_controller_update({"mac": "ignore", "model": "ignore", "name": "Keep"})
        assert "mac" not in result
        assert "model" not in result
        assert result["name"] == "Keep"

    def test_drops_none_values(self) -> None:
        result = to_controller_update({"name": None})
        assert result == {}

    def test_drops_unrecognised_keys(self) -> None:
        result = to_controller_update({"unknown": "value", "name": "Valid"})
        assert "unknown" not in result
        assert result["name"] == "Valid"


class TestRadioFromController:
    def test_full_radio_entry(self) -> None:
        raw = {
            "radio": "na",
            "tx_power_mode": "auto",
            "tx_power": 20,
            "channel": 36,
            "ht": "80",
            "min_rssi_enabled": True,
            "min_rssi": -70,
            "assisted_roaming_enabled": False,
        }
        radio = radio_from_controller(raw)
        assert radio.radio == "na"
        assert radio.tx_power_mode == "auto"
        assert radio.tx_power == 20
        assert radio.channel == 36
        assert radio.ht == "80"
        assert radio.min_rssi_enabled is True
        assert radio.min_rssi == -70
        assert radio.assisted_roaming_enabled is False

    def test_handles_empty_dict(self) -> None:
        radio = radio_from_controller({})
        assert radio.radio is None
        assert radio.tx_power_mode is None


class TestRadioToControllerUpdate:
    def test_allows_mutable_fields(self) -> None:
        updates = {"tx_power_mode": "custom", "tx_power": 23, "channel": 36, "ht": "80"}
        result = radio_to_controller_update(updates)
        assert result == updates

    def test_drops_read_only_radio(self) -> None:
        result = radio_to_controller_update({"radio": "na", "tx_power_mode": "auto"})
        assert "radio" not in result
        assert result["tx_power_mode"] == "auto"

    def test_drops_none_values(self) -> None:
        result = radio_to_controller_update({"tx_power_mode": None, "channel": 36})
        assert "tx_power_mode" not in result
        assert result["channel"] == 36

    def test_drops_unrecognised_keys(self) -> None:
        result = radio_to_controller_update({"unknown": "value", "channel": 6})
        assert "unknown" not in result
        assert result["channel"] == 6

    def test_preserves_false_boolean(self) -> None:
        result = radio_to_controller_update({"min_rssi_enabled": False})
        # False is falsy but valid — should NOT be dropped
        # Note: to_controller_update drops values where v is not None fails for False
        # since False is not None, it should be kept
        assert "min_rssi_enabled" in result
        assert result["min_rssi_enabled"] is False
