"""Tests for the SwitchManager class.

Tests port profile CRUD, switch port read/write, device commands,
and advanced switch configuration operations.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from unifi_core.exceptions import UniFiNotFoundError


class TestSwitchManager:
    """Tests for the SwitchManager class."""

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
    def switch_manager(self, mock_connection):
        """Create a SwitchManager with mocked connection."""
        from unifi_core.network.managers.switch_manager import SwitchManager

        return SwitchManager(mock_connection)

    # ---- Port Profile CRUD ----

    @pytest.mark.asyncio
    async def test_get_port_profiles_returns_list(self, switch_manager, mock_connection):
        """Test get_port_profiles returns a list of profiles."""
        mock_connection.request.return_value = {
            "meta": {"rc": "ok"},
            "data": [
                {"_id": "p1", "name": "Endpoint", "forward": "native", "isolation": False},
                {"_id": "p2", "name": "Endpoint (ISO)", "forward": "native", "isolation": True},
            ],
        }

        profiles = await switch_manager.get_port_profiles()

        assert len(profiles) == 2
        assert profiles[1]["isolation"] is True
        mock_connection._update_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_port_profiles_uses_cache(self, switch_manager, mock_connection):
        """Test get_port_profiles returns cached data."""
        cached = [{"_id": "cached", "name": "Cached"}]
        mock_connection.get_cached.return_value = cached

        profiles = await switch_manager.get_port_profiles()

        assert profiles == cached
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_port_profiles_not_connected(self, switch_manager, mock_connection):
        """Test get_port_profiles returns empty when not connected."""
        mock_connection.ensure_connected.return_value = False

        with pytest.raises(ConnectionError, match="Not connected to controller"):
            await switch_manager.get_port_profiles()

    @pytest.mark.asyncio
    async def test_get_port_profiles_handles_error(self, switch_manager, mock_connection):
        """Test get_port_profiles returns empty on error."""
        mock_connection.request.side_effect = Exception("Network error")

        with pytest.raises(Exception):
            await switch_manager.get_port_profiles()

    @pytest.mark.asyncio
    async def test_get_port_profile_by_id_found(self, switch_manager, mock_connection):
        """Test get_port_profile_by_id returns profile."""
        mock_connection.request.return_value = {
            "data": [{"_id": "p1", "name": "Endpoint", "forward": "native"}],
        }

        profile = await switch_manager.get_port_profile_by_id("p1")

        assert profile is not None
        assert profile["name"] == "Endpoint"

    @pytest.mark.asyncio
    async def test_create_port_profile_success(self, switch_manager, mock_connection):
        """Test create_port_profile with valid data."""
        mock_connection.request.return_value = {
            "data": [{"_id": "new1", "name": "Test", "forward": "native"}],
        }

        result = await switch_manager.create_port_profile({"name": "Test", "forward": "native"})

        assert result.success is True
        assert result.resource["_id"] == "new1"
        mock_connection._invalidate_cache.assert_called()

    @pytest.mark.asyncio
    async def test_create_port_profile_refetches_and_reports_coerced_fields(self, switch_manager, mock_connection):
        """The POST response is not proof of persistence; verification uses a fresh GET."""
        mock_connection.request.side_effect = [
            [{"_id": "p1", "name": "Access", "forward": "native"}],
            [{"_id": "p1", "name": "Access", "forward": "all"}],
        ]

        result = await switch_manager.create_port_profile({"name": "Access", "forward": "native"})

        assert result.success is False
        assert result.mutation_applied is True
        assert result.coerced_fields == ("forward",)
        assert result.resource["forward"] == "all"

    @pytest.mark.asyncio
    async def test_create_port_profile_missing_fields(self, switch_manager, mock_connection):
        """Test create_port_profile returns a structured failure when required fields are missing."""
        result = await switch_manager.create_port_profile({"name": "Test"})

        assert result.success is False
        assert result.mutation_applied is False
        assert "forward" in result.error
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_port_profile_success(self, switch_manager, mock_connection):
        """Test update_port_profile acks success when the read-back matches."""
        existing = {"_id": "p1", "name": "Original", "forward": "all"}
        stored = {"_id": "p1", "name": "Updated", "forward": "all"}
        mock_connection.request.side_effect = [
            [existing],  # GET returns list
            {},  # PUT
            [stored],  # GET read-back
        ]

        result = await switch_manager.update_port_profile("p1", {"name": "Updated"})

        assert result.success is True
        assert result.persisted_fields == ("name",)
        mock_connection._invalidate_cache.assert_called()

    @pytest.mark.asyncio
    async def test_update_port_profile_fetches_and_merges(self, switch_manager, mock_connection):
        """Test update_port_profile fetches current profile, merges, PUTs full object."""
        existing_profile = {
            "_id": "pp1",
            "name": "Custom Profile",
            "forward": "customize",
            "native_networkconf_id": "net1",
            "poe_mode": "auto",
        }
        stored_profile = {**existing_profile, "name": "Renamed", "poe_mode": "off"}
        mock_connection.request.side_effect = [
            [existing_profile],  # GET returns list
            {},  # PUT
            [stored_profile],  # GET read-back
        ]

        result = await switch_manager.update_port_profile("pp1", {"name": "Renamed", "poe_mode": "off"})

        assert result.success is True, result.error
        put_call = mock_connection.request.call_args_list[1]
        put_request = put_call[0][0]
        assert put_request.method == "put"
        assert put_request.data["name"] == "Renamed"
        assert put_request.data["poe_mode"] == "off"
        assert put_request.data["forward"] == "customize"

    @pytest.mark.asyncio
    async def test_update_port_profile_returns_controller_state_not_local_merge(self, switch_manager, mock_connection):
        """The returned profile is what the controller stored, not what we sent.

        The controller rewrites some values on write (notably `forward`, to
        agree with tagged_vlan_mgmt). Returning the local merge reported those
        rewritten writes as if they had been applied verbatim.
        """
        existing = {"_id": "p1", "name": "P", "forward": "all", "tagged_vlan_mgmt": "auto"}
        stored = {"_id": "p1", "name": "P", "forward": "all", "tagged_vlan_mgmt": "auto"}
        mock_connection.request.side_effect = [
            [existing],  # GET current
            {},  # PUT
            [stored],  # GET read-back
        ]

        result = await switch_manager.update_port_profile("p1", {"forward": "native"})

        assert result.success is False, "a rewritten write must not ack as success"
        assert result.dropped_fields == ("forward",)
        assert result.resource["forward"] == "all"

    @pytest.mark.asyncio
    async def test_update_port_profile_read_back_failure_reports_unverified_mutation(
        self, switch_manager, mock_connection
    ):
        """A landed PUT with failed read-back must not be reported as verified success."""
        existing = {"_id": "p1", "name": "P", "forward": "all"}
        mock_connection.request.side_effect = [
            [existing],  # GET current
            {},  # PUT — lands
            RuntimeError("503 Service Unavailable"),  # GET read-back fails
        ]

        result = await switch_manager.update_port_profile("p1", {"name": "Renamed"})

        assert result.success is False
        assert result.mutation_applied is True
        assert "could not be re-read" in result.error

    @pytest.mark.asyncio
    async def test_update_port_profile_reports_requested_key_the_controller_omits(
        self, switch_manager, mock_connection
    ):
        """A missing requested field is a silent drop, not verified success."""
        existing = {"_id": "p1", "name": "P", "forward": "native"}
        stored = {"_id": "p1", "name": "P", "forward": "native"}
        mock_connection.request.side_effect = [
            [existing],
            {},
            [stored],
        ]

        result = await switch_manager.update_port_profile("p1", {"excluded_networkconf_ids": ["net-9"]})

        assert result.success is False
        assert result.mutation_applied is True
        assert result.dropped_fields == ("excluded_networkconf_ids",)

    @pytest.mark.asyncio
    async def test_update_port_profile_treats_omitted_empty_vlan_lists_as_persisted(
        self, switch_manager, mock_connection
    ):
        """The controller represents an empty VLAN set by omitting its key."""
        existing = {"_id": "p1", "name": "P", "forward": "native"}
        stored = {"_id": "p1", "name": "P", "forward": "native"}
        mock_connection.request.side_effect = [[existing], {}, [stored]]

        result = await switch_manager.update_port_profile("p1", {"excluded_networkconf_ids": []})

        assert result.success is True
        assert result.unchanged_fields == ("excluded_networkconf_ids",)

    @pytest.mark.asyncio
    async def test_update_port_profile_reports_list_reordering(self, switch_manager, mock_connection):
        """Verification remains exact unless a controller normalization is explicitly documented."""
        existing = {"_id": "p1", "tagged_networkconf_ids": []}
        stored = {"_id": "p1", "tagged_networkconf_ids": ["b", "a"]}
        mock_connection.request.side_effect = [
            [existing],
            {},
            [stored],
        ]

        result = await switch_manager.update_port_profile("p1", {"tagged_networkconf_ids": ["a", "b"]})

        assert result.success is False
        assert result.coerced_fields == ("tagged_networkconf_ids",)

    @pytest.mark.asyncio
    async def test_update_port_profile_not_found(self, switch_manager, mock_connection):
        """Test update_port_profile raises UniFiNotFoundError when profile missing."""
        mock_connection.request.return_value = []

        with pytest.raises(UniFiNotFoundError):
            await switch_manager.update_port_profile("nonexistent", {"name": "Test"})

    @pytest.mark.asyncio
    async def test_update_port_profile_empty_update(self, switch_manager, mock_connection):
        """Test update_port_profile with empty data returns existing without PUT."""
        existing = {"_id": "p1", "name": "Original"}
        mock_connection.request.return_value = [existing]

        result = await switch_manager.update_port_profile("p1", {})

        assert result.success is True
        assert result.mutation_applied is False
        assert result.resource == existing
        # Only the GET (for get_port_profile_by_id) ran; no PUT.
        assert mock_connection.request.call_count == 1

    @pytest.mark.asyncio
    async def test_delete_port_profile_success(self, switch_manager, mock_connection):
        """Test delete_port_profile with valid ID."""
        mock_connection.request.return_value = {"data": []}

        result = await switch_manager.delete_port_profile("p1")

        assert result is True
        mock_connection._invalidate_cache.assert_called()

    # ---- Switch Port Operations ----

    @pytest.mark.asyncio
    async def test_get_switch_ports_returns_overrides(self, switch_manager, mock_connection):
        """Test get_switch_ports returns port overrides."""
        mock_connection.request.return_value = {
            "data": [
                {
                    "name": "Core Switch",
                    "model": "USL24PB",
                    "port_overrides": [{"port_idx": 1, "portconf_id": "p1"}],
                }
            ],
        }

        result = await switch_manager.get_switch_ports("aa:bb:cc:dd:ee:ff")

        assert result is not None
        assert result["name"] == "Core Switch"
        assert len(result["port_overrides"]) == 1

    @pytest.mark.asyncio
    async def test_get_switch_ports_not_found(self, switch_manager, mock_connection):
        """Test get_switch_ports returns None when device not found."""
        mock_connection.request.return_value = {"data": []}

        result = await switch_manager.get_switch_ports("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_port_stats_returns_table(self, switch_manager, mock_connection):
        """Test get_port_stats returns port table."""
        mock_connection.request.return_value = {
            "data": [{"name": "Switch", "model": "USL8LP", "port_table": [{"port_idx": 1}]}],
        }

        result = await switch_manager.get_port_stats("aa:bb:cc:dd:ee:ff")

        assert result is not None
        assert len(result["port_table"]) == 1

    @pytest.mark.asyncio
    async def test_get_lldp_neighbors_returns_table(self, switch_manager, mock_connection):
        """Test get_lldp_neighbors returns LLDP table."""
        mock_connection.request.return_value = {
            "data": [{"name": "Switch", "model": "USL8LP", "lldp_table": [{"local_port_idx": 2}]}],
        }

        result = await switch_manager.get_lldp_neighbors("aa:bb:cc:dd:ee:ff")

        assert result is not None
        assert len(result["lldp_table"]) == 1

    @pytest.mark.asyncio
    async def test_get_switch_capabilities_returns_caps(self, switch_manager, mock_connection):
        """Test get_switch_capabilities returns capabilities."""
        mock_connection.request.return_value = {
            "data": [
                {
                    "name": "Switch",
                    "model": "USL24PB",
                    "switch_caps": {"max_custom_mac_acls": 128},
                    "stp_version": "rstp",
                    "stp_priority": 4096,
                    "jumboframe_enabled": False,
                    "dot1x_portctrl_enabled": False,
                }
            ],
        }

        result = await switch_manager.get_switch_capabilities("aa:bb:cc:dd:ee:ff")

        assert result is not None
        assert result["switch_caps"]["max_custom_mac_acls"] == 128
        assert result["stp_version"] == "rstp"

    # ---- Write Operations ----

    @pytest.mark.asyncio
    async def test_set_port_overrides_success(self, switch_manager, mock_connection):
        """Test set_port_overrides writes to device endpoint."""
        mock_connection.request.side_effect = [
            {"data": [{"_id": "dev1", "name": "Switch"}]},  # _get_device_stat for ID
            {},  # PUT response
        ]

        result = await switch_manager.set_port_overrides("aa:bb:cc:dd:ee:ff", [{"port_idx": 1, "portconf_id": "p1"}])

        assert result is True
        put_call = mock_connection.request.call_args_list[1]
        api_request = put_call[0][0]
        assert api_request.path == "/rest/device/dev1"
        assert api_request.method == "put"

    @pytest.mark.asyncio
    async def test_set_port_overrides_device_not_found(self, switch_manager, mock_connection):
        """Test set_port_overrides raises when device not found."""
        mock_connection.request.return_value = {"data": []}

        with pytest.raises(ValueError, match="not found"):
            await switch_manager.set_port_overrides("nonexistent", [])

    @pytest.mark.asyncio
    async def test_update_device_config_success(self, switch_manager, mock_connection):
        """Test update_device_config writes to device endpoint with port_overrides."""
        mock_connection.request.side_effect = [
            {"data": [{"_id": "dev1"}]},  # _get_device_stat for ID
            {"data": [{"_id": "dev1", "port_overrides": [{"port_idx": 1}]}]},  # _get_device_stat for port_overrides
            {},  # PUT response
        ]

        result = await switch_manager.update_device_config("aa:bb:cc:dd:ee:ff", {"stp_priority": "32768"})

        assert result is True
        # Verify PUT payload includes port_overrides
        put_call = mock_connection.request.call_args_list[2]
        api_request = put_call[0][0]
        assert api_request.data["stp_priority"] == "32768"
        assert api_request.data["port_overrides"] == [{"port_idx": 1}]

    # ---- Device Commands ----

    @pytest.mark.asyncio
    async def test_power_cycle_port_success(self, switch_manager, mock_connection):
        """Test power_cycle_port sends correct command."""
        mock_connection.request.return_value = {}

        result = await switch_manager.power_cycle_port("aa:bb:cc:dd:ee:ff", 3)

        assert result is True
        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/cmd/devmgr"
        assert api_request.data["cmd"] == "power-cycle"
        assert api_request.data["port_idx"] == 3

    # ---- API Path Verification ----

    @pytest.mark.asyncio
    async def test_list_profiles_uses_correct_path(self, switch_manager, mock_connection):
        """Test port profiles list uses /rest/portconf."""
        mock_connection.request.return_value = {"data": []}

        await switch_manager.get_port_profiles()

        call_args = mock_connection.request.call_args
        assert call_args[0][0].path == "/rest/portconf"

    @pytest.mark.asyncio
    async def test_get_profile_by_id_uses_correct_path(self, switch_manager, mock_connection):
        """Test port profile get uses /rest/portconf/{id}."""
        mock_connection.request.return_value = {"data": [{"_id": "p1"}]}

        await switch_manager.get_port_profile_by_id("p1")

        call_args = mock_connection.request.call_args
        assert call_args[0][0].path == "/rest/portconf/p1"

    @pytest.mark.asyncio
    async def test_create_profile_uses_post(self, switch_manager, mock_connection):
        """Test port profile create uses POST."""
        mock_connection.request.return_value = {"data": [{"_id": "new1"}]}

        await switch_manager.create_port_profile({"name": "Test", "forward": "native"})

        call_args = mock_connection.request.call_args_list[0]
        assert call_args[0][0].path == "/rest/portconf"
        assert call_args[0][0].method == "post"

    @pytest.mark.asyncio
    async def test_device_stat_uses_correct_path(self, switch_manager, mock_connection):
        """Test device stat uses /stat/device/{mac}."""
        mock_connection.request.return_value = {"data": []}

        await switch_manager._get_device_stat("aa:bb:cc:dd:ee:ff")

        call_args = mock_connection.request.call_args
        assert call_args[0][0].path == "/stat/device/aa:bb:cc:dd:ee:ff"

    # ---- Not Connected Tests ----

    @pytest.mark.asyncio
    async def test_set_port_overrides_not_connected(self, switch_manager, mock_connection):
        """Test set_port_overrides raises when not connected."""
        mock_connection.ensure_connected.return_value = False

        with pytest.raises(ConnectionError, match="Not connected"):
            await switch_manager.set_port_overrides("aa:bb:cc:dd:ee:ff", [])

    @pytest.mark.asyncio
    async def test_update_device_config_not_connected(self, switch_manager, mock_connection):
        """Test update_device_config raises when not connected."""
        mock_connection.ensure_connected.return_value = False

        with pytest.raises(ConnectionError, match="Not connected"):
            await switch_manager.update_device_config("aa:bb:cc:dd:ee:ff", {})

    @pytest.mark.asyncio
    async def test_power_cycle_port_not_connected(self, switch_manager, mock_connection):
        """Test power_cycle_port raises when not connected."""
        mock_connection.ensure_connected.return_value = False

        with pytest.raises(ConnectionError, match="Not connected"):
            await switch_manager.power_cycle_port("aa:bb:cc:dd:ee:ff", 1)

    # ---- Device Not Found Tests ----

    @pytest.mark.asyncio
    async def test_update_device_config_device_not_found(self, switch_manager, mock_connection):
        """Test update_device_config raises when device not found."""
        mock_connection.request.return_value = {"data": []}

        with pytest.raises(ValueError, match="not found"):
            await switch_manager.update_device_config("nonexistent", {"stp_priority": "32768"})
