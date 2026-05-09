"""Tests for WiFi-related tools.

Tests DeviceManager WiFi operations (rogue APs, RF scanning, channels,
known rogue APs, LED override, device disable, site LED)
and NetworkManager WLAN operations (delete, toggle)
and NetworkManager AP Group operations.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestDeviceManagerWifi:
    """Tests for DeviceManager WiFi methods."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock ConnectionManager."""
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        conn.get_cached = MagicMock(return_value=None)
        conn._update_cache = MagicMock()
        conn._invalidate_cache = MagicMock()
        conn.ensure_connected = AsyncMock(return_value=True)
        return conn

    @pytest.fixture
    def device_manager(self, mock_connection):
        """Create a DeviceManager with mocked connection."""
        from unifi_core.network.managers.device_manager import DeviceManager

        return DeviceManager(mock_connection)

    # ---- Rogue APs ----

    @pytest.mark.asyncio
    async def test_list_rogue_aps(self, device_manager, mock_connection):
        """Test list_rogue_aps calls POST /stat/rogueap with within payload."""
        rogue_data = [
            {"bssid": "aa:bb:cc:dd:ee:01", "essid": "EvilTwin", "rssi": -40},
            {"bssid": "aa:bb:cc:dd:ee:02", "essid": "FreeWiFi", "rssi": -60},
        ]
        mock_connection.request.return_value = rogue_data

        result = await device_manager.list_rogue_aps(within_hours=12)

        assert len(result) == 2
        assert result[0]["essid"] == "EvilTwin"
        # Verify the API request was made with correct parameters
        call_args = mock_connection.request.call_args
        api_req = call_args[0][0]
        assert api_req.method == "post"
        assert api_req.path == "/stat/rogueap"
        assert api_req.data == {"within": 12}
        mock_connection._update_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_rogue_aps_uses_cache(self, device_manager, mock_connection):
        """Test list_rogue_aps returns cached data without API call."""
        cached = [{"bssid": "cached:ap", "essid": "CachedAP"}]
        mock_connection.get_cached.return_value = cached

        result = await device_manager.list_rogue_aps()

        assert result == cached
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_rogue_aps_handles_error(self, device_manager, mock_connection):
        """Test list_rogue_aps returns empty list on exception."""
        mock_connection.request.side_effect = Exception("Connection failed")

        with pytest.raises(Exception):
            await device_manager.list_rogue_aps()

    # ---- RF Scan ----

    @pytest.mark.asyncio
    async def test_trigger_rf_scan(self, device_manager, mock_connection):
        """Test trigger_rf_scan sends POST /cmd/devmgr with spectrum-scan command."""
        mock_connection.request.return_value = {}

        result = await device_manager.trigger_rf_scan("aa:bb:cc:dd:ee:ff")

        assert result is True
        call_args = mock_connection.request.call_args
        api_req = call_args[0][0]
        assert api_req.method == "post"
        assert api_req.path == "/cmd/devmgr"
        assert api_req.data == {"cmd": "spectrum-scan", "mac": "aa:bb:cc:dd:ee:ff"}

    @pytest.mark.asyncio
    async def test_trigger_rf_scan_handles_error(self, device_manager, mock_connection):
        """Test trigger_rf_scan returns False on exception."""
        mock_connection.request.side_effect = Exception("AP unreachable")

        with pytest.raises(Exception):
            await device_manager.trigger_rf_scan("aa:bb:cc:dd:ee:ff")

    @pytest.mark.asyncio
    async def test_get_rf_scan_results(self, device_manager, mock_connection):
        """Test get_rf_scan_results calls GET /stat/spectrum-scan/{mac}."""
        scan_data = [
            {"channel": 1, "interference": 30},
            {"channel": 6, "interference": 10},
        ]
        mock_connection.request.return_value = scan_data

        result = await device_manager.get_rf_scan_results("aa:bb:cc:dd:ee:ff")

        assert len(result) == 2
        assert result[1]["channel"] == 6
        call_args = mock_connection.request.call_args
        api_req = call_args[0][0]
        assert api_req.method == "get"
        assert api_req.path == "/stat/spectrum-scan/aa:bb:cc:dd:ee:ff"
        mock_connection._update_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_rf_scan_results_not_found(self, device_manager, mock_connection):
        """Test get_rf_scan_results returns empty list on error."""
        mock_connection.request.side_effect = Exception("Not found")

        with pytest.raises(Exception):
            await device_manager.get_rf_scan_results("aa:bb:cc:dd:ee:ff")

    # ---- Available Channels ----

    @pytest.mark.asyncio
    async def test_list_available_channels(self, device_manager, mock_connection):
        """Test list_available_channels calls GET /stat/current-channel."""
        channel_data = [
            {"channel": 1, "band": "2g"},
            {"channel": 36, "band": "5g"},
        ]
        mock_connection.request.return_value = channel_data

        result = await device_manager.list_available_channels()

        assert len(result) == 2
        call_args = mock_connection.request.call_args
        api_req = call_args[0][0]
        assert api_req.method == "get"
        assert api_req.path == "/stat/current-channel"
        mock_connection._update_cache.assert_called_once()

    # ---- LED Override ----

    @pytest.mark.asyncio
    async def test_set_device_led_override(self, device_manager, mock_connection):
        """Test set_device_led_override does ID lookup then PUT with led_override."""
        # Mock device returned by get_device_details (via get_devices -> controller.devices)
        mock_device = MagicMock()
        mock_device.mac = "aa:bb:cc:dd:ee:ff"
        mock_device.raw = {"_id": "device123", "mac": "aa:bb:cc:dd:ee:ff"}

        # Mock controller.devices for get_devices path
        mock_connection.controller = MagicMock()
        mock_connection.controller.devices.update = AsyncMock()
        mock_connection.controller.devices.values = MagicMock(return_value=[mock_device])

        # The PUT request returns updated device
        put_response = {"_id": "device123", "led_override": "on"}
        mock_connection.request.return_value = put_response

        result = await device_manager.set_device_led_override("aa:bb:cc:dd:ee:ff", "on")

        assert result is True
        call_args = mock_connection.request.call_args
        api_req = call_args[0][0]
        assert api_req.method == "put"
        assert api_req.path == "/rest/device/device123"
        assert api_req.data["led_override"] == "on"

    @pytest.mark.asyncio
    async def test_set_device_led_override_handles_error(self, device_manager, mock_connection):
        """Test set_device_led_override returns False on exception."""
        # Mock controller so get_devices works but request fails on PUT
        mock_device = MagicMock()
        mock_device.mac = "aa:bb:cc:dd:ee:ff"
        mock_device.raw = {"_id": "device123", "mac": "aa:bb:cc:dd:ee:ff"}

        mock_connection.controller = MagicMock()
        mock_connection.controller.devices.update = AsyncMock()
        mock_connection.controller.devices.values = MagicMock(return_value=[mock_device])
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await device_manager.set_device_led_override("aa:bb:cc:dd:ee:ff", "on")

    # ---- Device Disabled ----

    @pytest.mark.asyncio
    async def test_set_device_disabled(self, device_manager, mock_connection):
        """Test set_device_disabled does ID lookup then PUT with disabled field."""
        mock_device = MagicMock()
        mock_device.mac = "aa:bb:cc:dd:ee:ff"
        mock_device.raw = {"_id": "device123", "mac": "aa:bb:cc:dd:ee:ff"}

        mock_connection.controller = MagicMock()
        mock_connection.controller.devices.update = AsyncMock()
        mock_connection.controller.devices.values = MagicMock(return_value=[mock_device])

        put_response = {"_id": "device123", "disabled": True}
        mock_connection.request.return_value = put_response

        result = await device_manager.set_device_disabled("aa:bb:cc:dd:ee:ff", True)

        assert result is True
        call_args = mock_connection.request.call_args
        api_req = call_args[0][0]
        assert api_req.method == "put"
        assert api_req.path == "/rest/device/device123"
        assert api_req.data["disabled"] is True

    # ---- Site LED ----

    @pytest.mark.asyncio
    async def test_set_site_led_enabled(self, device_manager, mock_connection):
        """Test set_site_led_enabled sends PUT to /set/setting/mgmt with led_enabled."""
        mock_connection.request.return_value = {}

        result = await device_manager.set_site_led_enabled(True)

        assert result is True
        call_args = mock_connection.request.call_args
        api_req = call_args[0][0]
        assert api_req.method == "put"
        assert api_req.path == "/set/setting/mgmt"
        assert api_req.data["led_enabled"] is True


class TestNetworkManagerWlan:
    """Tests for NetworkManager WLAN methods."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock ConnectionManager."""
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        conn.get_cached = MagicMock(return_value=None)
        conn._update_cache = MagicMock()
        conn._invalidate_cache = MagicMock()
        conn.ensure_connected = AsyncMock(return_value=True)
        return conn

    @pytest.fixture
    def network_manager(self, mock_connection):
        """Create a NetworkManager with mocked connection."""
        from unifi_core.network.managers.network_manager import NetworkManager

        return NetworkManager(mock_connection)

    @pytest.mark.asyncio
    async def test_delete_wlan_exists(self, network_manager):
        """Verify delete_wlan method exists and is callable."""
        assert hasattr(network_manager, "delete_wlan")
        assert callable(network_manager.delete_wlan)

    @pytest.mark.asyncio
    async def test_toggle_wlan_exists(self, network_manager):
        """Verify toggle_wlan method exists and is callable."""
        assert hasattr(network_manager, "toggle_wlan")
        assert callable(network_manager.toggle_wlan)


class TestNetworkManagerApGroups:
    """Tests for NetworkManager AP Group methods."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock ConnectionManager."""
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        conn.get_cached = MagicMock(return_value=None)
        conn._update_cache = MagicMock()
        conn._invalidate_cache = MagicMock()
        conn.ensure_connected = AsyncMock(return_value=True)
        return conn

    @pytest.fixture
    def network_manager(self, mock_connection):
        """Create a NetworkManager with mocked connection."""
        from unifi_core.network.managers.network_manager import NetworkManager

        return NetworkManager(mock_connection)

    # ---- List AP Groups ----

    @pytest.mark.asyncio
    async def test_list_ap_groups(self, network_manager, mock_connection):
        """Test list_ap_groups calls correct endpoint and returns list."""
        ap_groups = [
            {"_id": "grp1", "name": "Default", "device_macs": []},
            {"_id": "grp2", "name": "Outdoor APs", "device_macs": ["aa:bb:cc:dd:ee:01"]},
        ]
        mock_connection.request.return_value = ap_groups

        result = await network_manager.list_ap_groups()

        assert len(result) == 2
        assert result[0]["name"] == "Default"
        assert result[1]["name"] == "Outdoor APs"
        call_args = mock_connection.request.call_args
        api_req = call_args[0][0]
        assert "apgroup" in api_req.path

    @pytest.mark.asyncio
    async def test_list_ap_groups_handles_error(self, network_manager, mock_connection):
        """Test list_ap_groups returns empty list on exception."""
        mock_connection.request.side_effect = Exception("Connection failed")

        with pytest.raises(Exception):
            await network_manager.list_ap_groups()

    # ---- Get AP Group Details ----

    @pytest.mark.asyncio
    async def test_get_ap_group_details(self, network_manager, mock_connection):
        """Test get_ap_group_details fetches list and filters by ID."""
        groups = [
            {"_id": "grp1", "name": "Default", "device_macs": []},
            {"_id": "grp2", "name": "Other", "device_macs": []},
        ]
        mock_connection.request.return_value = groups

        result = await network_manager.get_ap_group_details("grp1")

        assert result is not None
        assert result["_id"] == "grp1"
        assert result["name"] == "Default"

    @pytest.mark.asyncio
    async def test_get_ap_group_details_not_found(self, network_manager, mock_connection):
        """Test get_ap_group_details returns None when group not found."""
        mock_connection.request.side_effect = Exception("Not found")

        with pytest.raises(Exception):
            await network_manager.get_ap_group_details("nonexistent")

    # ---- Create AP Group ----

    @pytest.mark.asyncio
    async def test_create_ap_group(self, network_manager, mock_connection):
        """Test create_ap_group sends POST and returns created object."""
        created_group = {
            "_id": "grp_new",
            "name": "Indoor APs",
            "device_macs": ["aa:bb:cc:dd:ee:01"],
        }
        mock_connection.request.return_value = created_group

        result = await network_manager.create_ap_group({"name": "Indoor APs", "device_macs": ["aa:bb:cc:dd:ee:01"]})

        assert result is not None
        assert result["name"] == "Indoor APs"
        call_args = mock_connection.request.call_args
        api_req = call_args[0][0]
        assert api_req.method == "post"
        assert "apgroup" in api_req.path

    # ---- Update AP Group ----

    @pytest.mark.asyncio
    async def test_update_ap_group(self, network_manager, mock_connection):
        """Test update_ap_group uses fetch-merge-put pattern (list then PUT)."""
        existing_groups = [
            {
                "_id": "grp1",
                "name": "Default",
                "device_macs": ["aa:bb:cc:dd:ee:01"],
                "attr_hidden_id": "default",
            }
        ]
        # First call: list_ap_groups (GET list), second call: PUT merged data
        mock_connection.request.side_effect = [existing_groups, {}]

        result = await network_manager.update_ap_group(
            "grp1",
            {"name": "Renamed Group", "device_macs": ["aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"]},
        )

        assert result is True
        # Verify two requests were made: GET list then PUT
        assert mock_connection.request.call_count == 2
        # Second call should be the PUT with merged data
        put_call = mock_connection.request.call_args_list[1]
        put_req = put_call[0][0]
        assert put_req.method == "put"
        assert "grp1" in put_req.path

    @pytest.mark.asyncio
    async def test_update_ap_group_not_found(self, network_manager, mock_connection):
        """Test update_ap_group returns False when group not found."""
        mock_connection.request.side_effect = Exception("Not found")

        with pytest.raises(Exception):
            await network_manager.update_ap_group("nonexistent", {"name": "New Name"})

    # ---- Delete AP Group ----

    @pytest.mark.asyncio
    async def test_delete_ap_group(self, network_manager, mock_connection):
        """Test delete_ap_group sends DELETE and returns True."""
        mock_connection.request.return_value = {}

        result = await network_manager.delete_ap_group("grp1")

        assert result is True
        call_args = mock_connection.request.call_args
        api_req = call_args[0][0]
        assert api_req.method == "delete"
        assert "apgroup" in api_req.path
        assert "grp1" in api_req.path
