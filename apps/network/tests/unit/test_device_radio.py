"""Tests for device radio configuration tools.

Tests the get_device_radio and update_device_radio manager methods,
and the unifi_get_device_radio / unifi_update_device_radio tool functions.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")

SAMPLE_RADIO_TABLE = [
    {
        "name": "wifi0",
        "radio": "ng",
        "channel": 11,
        "ht": "20",
        "tx_power_mode": "medium",
        "tx_power": 16,
        "min_rssi_enabled": True,
        "min_rssi": -80,
        "max_txpower": 23,
        "min_txpower": 6,
        "has_dfs": True,
        "nss": 2,
        "is_11ax": True,
        "is_11be": True,
        "antenna_gain": 8,
        "builtin_ant_gain": 8,
        "builtin_antenna": True,
    },
    {
        "name": "wifi1",
        "radio": "na",
        "channel": 44,
        "ht": "80",
        "tx_power_mode": "auto",
        "tx_power": 21,
        "min_rssi_enabled": True,
        "min_rssi": -82,
        "max_txpower": 26,
        "min_txpower": 6,
        "has_dfs": True,
        "nss": 2,
        "is_11ax": True,
        "is_11be": True,
        "antenna_gain": 13,
        "builtin_ant_gain": 13,
        "builtin_antenna": True,
    },
]

SAMPLE_RADIO_TABLE_STATS = [
    {
        "name": "wifi0",
        "radio": "ng",
        "channel": 11,
        "tx_power": 14,
        "cu_total": 58,
        "cu_self_tx": 3,
        "cu_self_rx": 0,
        "satisfaction": -1,
        "num_sta": 1,
        "tx_retries": 223,
        "tx_packets": 718,
        "state": "RUN",
    },
    {
        "name": "wifi1",
        "radio": "na",
        "channel": 44,
        "tx_power": 23,
        "cu_total": 19,
        "cu_self_tx": 1,
        "cu_self_rx": 0,
        "satisfaction": -1,
        "num_sta": 3,
        "tx_retries": 420,
        "tx_packets": 2133,
        "state": "RUN",
    },
]


# Shapes captured from a live UDM running a 6GHz radio. The 6e entry differs from
# every AP sample above in two ways: "channel" is the string "auto" when the radio
# is on automatic selection, and "ht" comes back as an int rather than a string.
UDM_RADIO_TABLE = [
    {
        "name": "wifi0",
        "radio": "ng",
        "channel": 11,
        "ht": "20",
        "tx_power_mode": "low",
        "min_rssi_enabled": False,
        "max_txpower": 23,
        "min_txpower": 6,
        "has_dfs": True,
        "nss": 2,
        "is_11ax": True,
        "is_11be": True,
    },
    {
        "name": "wifi1",
        "radio": "na",
        "channel": 132,
        "ht": "80",
        "tx_power_mode": "low",
        "min_rssi_enabled": True,
        "min_rssi": -75,
        "max_txpower": 26,
        "min_txpower": 6,
        "has_dfs": True,
        "nss": 2,
        "is_11ax": True,
        "is_11be": True,
    },
    {
        "name": "wifi2",
        "radio": "6e",
        "channel": "auto",
        "ht": 160,
        "tx_power_mode": "auto",
        "min_rssi_enabled": True,
        "min_rssi": -75,
        "max_txpower": 24,
        "min_txpower": 6,
        "has_dfs": True,
        "nss": 2,
        "is_11ax": True,
        "is_11be": True,
    },
]

UDM_RADIO_TABLE_STATS = [
    {
        "name": "wifi0",
        "radio": "ng",
        "channel": 11,
        "tx_power": 6,
        "cu_total": 38,
        "cu_self_tx": 17,
        "cu_self_rx": 20,
        "satisfaction": -1,
        "num_sta": 10,
        "tx_retries": 8,
        "tx_packets": 156,
        "state": "RUN",
    },
    {
        "name": "wifi1",
        "radio": "na",
        "channel": 132,
        "tx_power": 6,
        "cu_total": 2,
        "cu_self_tx": 1,
        "cu_self_rx": 0,
        "satisfaction": -1,
        "num_sta": 2,
        "tx_retries": 0,
        "tx_packets": 0,
        "state": "RUN",
    },
    {
        "name": "wifi2",
        "radio": "6e",
        "channel": 37,
        "tx_power": 21,
        "cu_total": 1,
        "cu_self_tx": 1,
        "cu_self_rx": 0,
        "satisfaction": -1,
        "num_sta": 0,
        "tx_retries": 0,
        "tx_packets": 0,
        "state": "RUN",
    },
]


def _make_ap_device(mac="28:70:4e:c1:b4:c8"):
    """Create a mock Device representing an AP with radio_table data."""
    device = MagicMock()
    device.mac = mac
    device.raw = {
        "_id": "device_abc123",
        "mac": mac,
        "name": "Test AP",
        "model": "U6-Pro",
        "type": "uap",
        "radio_table": list(SAMPLE_RADIO_TABLE),
        "radio_table_stats": list(SAMPLE_RADIO_TABLE_STATS),
    }
    return device


def _make_switch_device(mac="11:22:33:44:55:66"):
    """Create a mock Device representing a switch (not an AP)."""
    device = MagicMock()
    device.mac = mac
    device.raw = {
        "_id": "device_switch123",
        "mac": mac,
        "name": "Test Switch",
        "model": "USW-24-PoE",
        "type": "usw",
    }
    return device


def _make_udm_device(mac="aa:bb:cc:dd:ee:01"):
    """Create a mock Device representing a UDM/gateway WITH built-in radios (UDR-style)."""
    device = MagicMock()
    device.mac = mac
    device.raw = {
        "_id": "device_udm123",
        "mac": mac,
        "name": "Test UDR",
        "model": "UDR",
        "type": "udm",
        "radio_table": list(UDM_RADIO_TABLE),
        "radio_table_stats": list(UDM_RADIO_TABLE_STATS),
    }
    return device


def _make_radioless_gateway_device(mac="aa:bb:cc:dd:ee:02"):
    """Create a mock Device representing a gateway with no radio hardware (UDM Pro / UXG)."""
    device = MagicMock()
    device.mac = mac
    device.raw = {
        "_id": "device_udmpro123",
        "mac": mac,
        "name": "Test UDM Pro",
        "model": "UDMPRO",
        "type": "udm",
    }
    return device


class TestDeviceManagerGetRadio:
    """Tests for DeviceManager.get_device_radio()."""

    @pytest.fixture
    def mock_connection(self):
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        conn.get_cached = MagicMock(return_value=None)
        conn._update_cache = MagicMock()
        conn._invalidate_cache = MagicMock()
        conn.controller = MagicMock()
        conn.controller.devices = MagicMock()
        conn.controller.devices.update = AsyncMock()
        conn.controller.devices.values = MagicMock(return_value=[])
        conn.ensure_connected = AsyncMock(return_value=True)
        return conn

    @pytest.fixture
    def device_manager(self, mock_connection):
        from unifi_core.network.managers.device_manager import DeviceManager

        return DeviceManager(mock_connection)

    @pytest.mark.asyncio
    async def test_returns_radio_data_for_ap(self, device_manager, mock_connection):
        ap = _make_ap_device()
        mock_connection.controller.devices.values.return_value = [ap]

        result = await device_manager.get_device_radio(ap.mac)

        assert result is not None
        assert result["mac"] == ap.mac
        assert result["name"] == "Test AP"
        assert len(result["radios"]) == 2

        ng_radio = result["radios"][0]
        assert ng_radio["radio"] == "ng"
        assert ng_radio["channel"] == 11
        assert ng_radio["tx_power_mode"] == "medium"
        assert ng_radio["min_rssi"] == -80
        assert ng_radio["current_tx_power"] == 14
        assert ng_radio["cu_total"] == 58
        assert ng_radio["num_sta"] == 1

        na_radio = result["radios"][1]
        assert na_radio["radio"] == "na"
        assert na_radio["tx_power_mode"] == "auto"
        assert na_radio["current_tx_power"] == 23

    @pytest.mark.asyncio
    async def test_returns_none_for_switch(self, device_manager, mock_connection):
        switch = _make_switch_device()
        mock_connection.controller.devices.values.return_value = [switch]

        result = await device_manager.get_device_radio(switch.mac)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_radio_data_for_udm(self, device_manager, mock_connection):
        """A gateway with built-in radios is served like an AP, not rejected on its device type."""
        udm = _make_udm_device()
        mock_connection.controller.devices.values.return_value = [udm]

        result = await device_manager.get_device_radio(udm.mac)

        assert result is not None
        assert result["mac"] == udm.mac
        assert result["name"] == "Test UDR"
        assert len(result["radios"]) == 3

        assert [radio["radio"] for radio in result["radios"]] == ["ng", "na", "6e"]

        sixe_radio = result["radios"][2]
        assert sixe_radio["channel"] == "auto"
        assert sixe_radio["ht"] == 160
        assert sixe_radio["current_channel"] == 37
        assert sixe_radio["current_tx_power"] == 21

    @pytest.mark.asyncio
    async def test_empty_radio_table_still_succeeds(self, device_manager, mock_connection):
        """An empty radio_table stays an empty success, as it was before radios were keyed off the table."""
        ap = _make_ap_device()
        ap.raw["radio_table"] = []
        ap.raw["radio_table_stats"] = []
        mock_connection.controller.devices.values.return_value = [ap]

        result = await device_manager.get_device_radio(ap.mac)

        assert result is not None
        assert result["radios"] == []

    @pytest.mark.asyncio
    async def test_returns_none_for_radioless_gateway(self, device_manager, mock_connection):
        """UDM Pro / UXG-style gateways without radio hardware must return None, not empty success."""
        udm = _make_radioless_gateway_device()
        mock_connection.controller.devices.values.return_value = [udm]

        result = await device_manager.get_device_radio(udm.mac)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_mac(self, device_manager, mock_connection):
        from unifi_core.exceptions import UniFiNotFoundError

        mock_connection.controller.devices.values.return_value = []

        with pytest.raises(UniFiNotFoundError):
            await device_manager.get_device_radio("ff:ff:ff:ff:ff:ff")


class TestDeviceManagerUpdateRadio:
    """Tests for DeviceManager.update_device_radio()."""

    @pytest.fixture
    def mock_connection(self):
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        conn.get_cached = MagicMock(return_value=None)
        conn._update_cache = MagicMock()
        conn._invalidate_cache = MagicMock()
        conn.controller = MagicMock()
        conn.controller.devices = MagicMock()
        conn.controller.devices.update = AsyncMock()
        conn.controller.devices.values = MagicMock(return_value=[])
        conn.ensure_connected = AsyncMock(return_value=True)
        return conn

    @pytest.fixture
    def device_manager(self, mock_connection):
        from unifi_core.network.managers.device_manager import DeviceManager

        return DeviceManager(mock_connection)

    @pytest.mark.asyncio
    async def test_updates_target_radio_only(self, device_manager, mock_connection):
        ap = _make_ap_device()
        mock_connection.controller.devices.values.return_value = [ap]

        result = await device_manager.update_device_radio(ap.mac, "na", {"tx_power_mode": "high"})

        assert result is True
        call_args = mock_connection.request.call_args[0][0]
        assert call_args.method == "put"
        assert "device_abc123" in call_args.path
        sent_table = call_args.data["radio_table"]
        na_entry = next(r for r in sent_table if r["radio"] == "na")
        assert na_entry["tx_power_mode"] == "high"
        ng_entry = next(r for r in sent_table if r["radio"] == "ng")
        assert ng_entry["tx_power_mode"] == "medium"

    @pytest.mark.asyncio
    async def test_update_by_name(self, device_manager, mock_connection):
        """Can match radio by internal name (wifi0/wifi1)."""
        ap = _make_ap_device()
        mock_connection.controller.devices.values.return_value = [ap]

        result = await device_manager.update_device_radio(ap.mac, "wifi0", {"channel": 6})

        assert result is True
        sent_table = mock_connection.request.call_args[0][0].data["radio_table"]
        wifi0 = next(r for r in sent_table if r["name"] == "wifi0")
        assert wifi0["channel"] == 6

    @pytest.mark.asyncio
    async def test_returns_false_for_missing_radio(self, device_manager, mock_connection):
        ap = _make_ap_device()
        mock_connection.controller.devices.values.return_value = [ap]

        result = await device_manager.update_device_radio(ap.mac, "6e", {"channel": 37})

        assert result is False
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_false_for_unknown_device(self, device_manager, mock_connection):
        from unifi_core.exceptions import UniFiNotFoundError

        mock_connection.controller.devices.values.return_value = []

        with pytest.raises(UniFiNotFoundError):
            await device_manager.update_device_radio("ff:ff:ff:ff:ff:ff", "na", {"tx_power_mode": "high"})

    @pytest.mark.asyncio
    async def test_does_not_mutate_original_radio_table(self, device_manager, mock_connection):
        """Ensure deepcopy prevents mutation of the cached device data."""
        ap = _make_ap_device()
        original_mode = ap.raw["radio_table"][1]["tx_power_mode"]
        mock_connection.controller.devices.values.return_value = [ap]

        await device_manager.update_device_radio(ap.mac, "na", {"tx_power_mode": "high"})

        assert ap.raw["radio_table"][1]["tx_power_mode"] == original_mode

    @pytest.mark.asyncio
    async def test_invalidates_cache_on_success(self, device_manager, mock_connection):
        ap = _make_ap_device()
        mock_connection.controller.devices.values.return_value = [ap]

        await device_manager.update_device_radio(ap.mac, "na", {"tx_power_mode": "high"})

        mock_connection._invalidate_cache.assert_called()

    @pytest.mark.asyncio
    async def test_handles_api_error(self, device_manager, mock_connection):
        ap = _make_ap_device()
        mock_connection.controller.devices.values.return_value = [ap]
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await device_manager.update_device_radio(ap.mac, "na", {"tx_power_mode": "high"})


class TestUpdateDeviceRadioTool:
    """Tests for the unifi_update_device_radio tool function validation logic."""

    @pytest.mark.asyncio
    async def test_rejects_invalid_radio(self):
        from unifi_network_mcp.tools.devices import update_device_radio

        result = await update_device_radio(mac_address="aa:bb:cc:dd:ee:ff", radio="invalid")

        assert result["success"] is False
        assert "Invalid radio" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_tx_power_without_custom_mode(self):
        from unifi_network_mcp.tools.devices import update_device_radio

        result = await update_device_radio(
            mac_address="aa:bb:cc:dd:ee:ff", radio="na", tx_power=20, tx_power_mode="high"
        )

        assert result["success"] is False
        assert "tx_power_mode is 'custom'" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_min_rssi_without_enabled(self):
        from unifi_network_mcp.tools.devices import update_device_radio

        result = await update_device_radio(mac_address="aa:bb:cc:dd:ee:ff", radio="na", min_rssi=-70)

        assert result["success"] is False
        assert "min_rssi_enabled" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_invalid_tx_power_mode(self):
        from unifi_network_mcp.tools.devices import update_device_radio

        result = await update_device_radio(mac_address="aa:bb:cc:dd:ee:ff", radio="na", tx_power_mode="turbo")

        assert result["success"] is False
        assert "Invalid tx_power_mode" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_invalid_ht(self):
        from unifi_network_mcp.tools.devices import update_device_radio

        result = await update_device_radio(mac_address="aa:bb:cc:dd:ee:ff", radio="na", ht="640")

        assert result["success"] is False
        assert "Invalid ht" in result["error"]

    @pytest.mark.asyncio
    async def test_accepts_internal_radio_name(self):
        """Internal names like wifi0/wifi1 pass validation (reaching 'no updates' check)."""
        from unifi_network_mcp.tools.devices import update_device_radio

        result = await update_device_radio(mac_address="aa:bb:cc:dd:ee:ff", radio="wifi0")

        assert result["success"] is False
        assert "No radio settings" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_no_updates(self):
        from unifi_network_mcp.tools.devices import update_device_radio

        result = await update_device_radio(mac_address="aa:bb:cc:dd:ee:ff", radio="na")

        assert result["success"] is False
        assert "No radio settings" in result["error"]

    @pytest.mark.asyncio
    async def test_preview_mode(self):
        from unifi_network_mcp.tools.devices import update_device_radio

        with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
            mock_dm.get_device_radio = AsyncMock(
                return_value={
                    "mac": "28:70:4e:c1:b4:c8",
                    "name": "Test AP",
                    "model": "U6-Pro",
                    "radios": [
                        {"name": "wifi1", "radio": "na", "tx_power_mode": "auto", "channel": 44},
                    ],
                }
            )
            mock_dm._connection = MagicMock()
            mock_dm._connection.site = "default"

            result = await update_device_radio(
                mac_address="28:70:4e:c1:b4:c8", radio="na", tx_power_mode="high", confirm=False
            )

        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert "warnings" in result
        assert any("restart" in w.lower() for w in result["warnings"])

    @pytest.mark.asyncio
    async def test_confirm_executes_update(self):
        from unifi_network_mcp.tools.devices import update_device_radio

        with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
            mock_dm.get_device_radio = AsyncMock(
                return_value={
                    "mac": "28:70:4e:c1:b4:c8",
                    "name": "Test AP",
                    "model": "U6-Pro",
                    "radios": [
                        {"name": "wifi1", "radio": "na", "tx_power_mode": "auto", "channel": 44},
                    ],
                }
            )
            mock_dm.update_device_radio = AsyncMock(return_value=True)
            mock_dm._connection = MagicMock()
            mock_dm._connection.site = "default"

            result = await update_device_radio(
                mac_address="28:70:4e:c1:b4:c8", radio="na", tx_power_mode="high", confirm=True
            )

        assert result["success"] is True
        mock_dm.update_device_radio.assert_called_once_with("28:70:4e:c1:b4:c8", "na", {"tx_power_mode": "high"})


class TestGetDeviceRadioTool:
    """Tests for the unifi_get_device_radio tool function."""

    @pytest.mark.asyncio
    async def test_returns_radio_data(self):
        from unifi_network_mcp.tools.devices import get_device_radio

        with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
            mock_dm.get_device_radio = AsyncMock(
                return_value={
                    "mac": "28:70:4e:c1:b4:c8",
                    "name": "Test AP",
                    "model": "U6-Pro",
                    "radios": [{"radio": "na", "channel": 44}],
                }
            )
            mock_dm._connection = MagicMock()
            mock_dm._connection.site = "default"

            result = await get_device_radio(mac_address="28:70:4e:c1:b4:c8")

        assert result["success"] is True
        assert result["name"] == "Test AP"
        assert len(result["radios"]) == 1

    @pytest.mark.asyncio
    async def test_returns_error_for_non_ap(self):
        from unifi_network_mcp.tools.devices import get_device_radio

        with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
            mock_dm.get_device_radio = AsyncMock(return_value=None)
            mock_dm._connection = MagicMock()
            mock_dm._connection.site = "default"

            result = await get_device_radio(mac_address="11:22:33:44:55:66")

        assert result["success"] is False
        assert "does not have radios" in result["error"]
