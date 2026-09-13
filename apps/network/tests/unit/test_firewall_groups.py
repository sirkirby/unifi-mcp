"""Tests for firewall group operations in FirewallManager.

Tests address-group and port-group CRUD via the v1 REST API.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from unifi_core.exceptions import UniFiNotFoundError


class TestFirewallGroups:
    """Tests for firewall group methods in FirewallManager."""

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
    def firewall_manager(self, mock_connection):
        """Create a FirewallManager with mocked connection."""
        from unifi_core.network.managers.firewall_manager import FirewallManager

        return FirewallManager(mock_connection)

    # ---- get_firewall_groups ----

    @pytest.mark.asyncio
    async def test_get_firewall_groups_returns_list(self, firewall_manager, mock_connection):
        """Test get_firewall_groups returns a list of groups."""
        mock_groups = [
            {"_id": "g1", "name": "NAS", "group_type": "address-group", "group_members": ["10.2.0.10"]},
            {"_id": "g2", "name": "File Service", "group_type": "port-group", "group_members": ["137", "445"]},
        ]
        mock_connection.request.return_value = {"meta": {"rc": "ok"}, "data": mock_groups}

        groups = await firewall_manager.get_firewall_groups()

        assert len(groups) == 2
        assert groups[0]["name"] == "NAS"
        mock_connection._update_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_firewall_groups_uses_cache(self, firewall_manager, mock_connection):
        """Test get_firewall_groups returns cached data."""
        cached = [{"_id": "cached", "name": "Cached Group"}]
        mock_connection.get_cached.return_value = cached

        groups = await firewall_manager.get_firewall_groups()

        assert groups == cached
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_firewall_groups_handles_error(self, firewall_manager, mock_connection):
        """Test get_firewall_groups returns empty list on error."""
        mock_connection.request.side_effect = Exception("Network error")

        with pytest.raises(Exception):
            await firewall_manager.get_firewall_groups()

    @pytest.mark.asyncio
    async def test_get_firewall_groups_not_connected(self, firewall_manager, mock_connection):
        """Test get_firewall_groups returns empty list when not connected."""
        mock_connection.ensure_connected.return_value = False

        with pytest.raises(ConnectionError, match="Not connected to controller"):
            await firewall_manager.get_firewall_groups()

    # ---- get_firewall_group_by_id ----

    @pytest.mark.asyncio
    async def test_get_firewall_group_by_id_found(self, firewall_manager, mock_connection):
        """Test get_firewall_group_by_id returns group from v1 data wrapper."""
        mock_connection.request.return_value = {
            "meta": {"rc": "ok"},
            "data": [{"_id": "g1", "name": "NAS", "group_type": "address-group"}],
        }

        group = await firewall_manager.get_firewall_group_by_id("g1")

        assert group is not None
        assert group["name"] == "NAS"

    @pytest.mark.asyncio
    async def test_get_firewall_group_by_id_not_connected(self, firewall_manager, mock_connection):
        """Test get_firewall_group_by_id returns None when not connected."""
        mock_connection.ensure_connected.return_value = False

        with pytest.raises(ConnectionError, match="Not connected to controller"):
            await firewall_manager.get_firewall_group_by_id("g1")

    @pytest.mark.asyncio
    async def test_get_firewall_group_by_id_handles_error(self, firewall_manager, mock_connection):
        """Test get_firewall_group_by_id returns None on error."""
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await firewall_manager.get_firewall_group_by_id("g1")

    @pytest.mark.asyncio
    async def test_get_firewall_group_by_id_empty_data(self, firewall_manager, mock_connection):
        """Test get_firewall_group_by_id returns None when data array is empty."""
        mock_connection.request.return_value = {"meta": {"rc": "ok"}, "data": []}

        group = await firewall_manager.get_firewall_group_by_id("nonexistent")

        assert group is None

    # ---- create_firewall_group ----

    @pytest.mark.asyncio
    async def test_create_firewall_group_success(self, firewall_manager, mock_connection):
        """Test create_firewall_group with valid data."""
        group_data = {
            "name": "New Group",
            "group_type": "address-group",
            "group_members": ["10.0.0.1"],
        }
        mock_connection.request.return_value = {
            "meta": {"rc": "ok"},
            "data": [{"_id": "new1", **group_data}],
        }

        result = await firewall_manager.create_firewall_group(group_data)

        assert result is not None
        assert result["_id"] == "new1"
        mock_connection._invalidate_cache.assert_called()

    @pytest.mark.asyncio
    async def test_create_firewall_group_missing_name(self, firewall_manager, mock_connection):
        """Test create_firewall_group returns None when name is missing."""
        result = await firewall_manager.create_firewall_group({"group_type": "address-group", "group_members": []})

        assert result is None
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_firewall_group_missing_type(self, firewall_manager, mock_connection):
        """Test create_firewall_group returns None when group_type is missing."""
        result = await firewall_manager.create_firewall_group({"name": "Test", "group_members": []})

        assert result is None
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_firewall_group_not_connected(self, firewall_manager, mock_connection):
        """Test create_firewall_group returns None when not connected."""
        mock_connection.ensure_connected.return_value = False

        with pytest.raises(Exception):
            await firewall_manager.create_firewall_group(
                {"name": "Test", "group_type": "address-group", "group_members": []}
            )

    @pytest.mark.asyncio
    async def test_create_firewall_group_handles_error(self, firewall_manager, mock_connection):
        """Test create_firewall_group returns None on error."""
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await firewall_manager.create_firewall_group(
                {"name": "Test", "group_type": "address-group", "group_members": []}
            )

    # ---- update_firewall_group ----

    @pytest.mark.asyncio
    async def test_update_firewall_group_success(self, firewall_manager, mock_connection):
        """A partial update is merged into the complete stored group before PUT."""
        current = {
            "_id": "g1",
            "name": "Original",
            "group_type": "address-group",
            "group_members": ["10.0.0.1"],
            "site_id": "site1",
        }
        mock_connection.request.side_effect = [{"data": [current]}, {}]

        result = await firewall_manager.update_firewall_group("g1", {"name": "Updated"})

        assert result is True
        put_request = mock_connection.request.call_args_list[1].args[0]
        assert put_request.data == {**current, "name": "Updated"}
        mock_connection._invalidate_cache.assert_called()

    @pytest.mark.asyncio
    async def test_update_firewall_group_not_found(self, firewall_manager, mock_connection):
        mock_connection.request.return_value = {"data": []}

        with pytest.raises(UniFiNotFoundError, match="g1"):
            await firewall_manager.update_firewall_group("g1", {"name": "Updated"})

        assert mock_connection.request.await_count == 1

    @pytest.mark.asyncio
    async def test_update_firewall_group_empty_update_is_noop(self, firewall_manager, mock_connection):
        mock_connection.request.return_value = {
            "data": [{"_id": "g1", "name": "Original", "group_type": "address-group", "group_members": []}]
        }

        assert await firewall_manager.update_firewall_group("g1", {}) is True
        assert mock_connection.request.await_count == 1
        mock_connection._invalidate_cache.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_firewall_group_rejects_type_change(self, firewall_manager, mock_connection):
        mock_connection.request.return_value = {
            "data": [{"_id": "g1", "name": "Original", "group_type": "address-group", "group_members": []}]
        }

        with pytest.raises(ValueError, match="cannot be changed"):
            await firewall_manager.update_firewall_group("g1", {"group_type": "port-group"})

        assert mock_connection.request.await_count == 1

    @pytest.mark.asyncio
    async def test_update_firewall_group_not_connected(self, firewall_manager, mock_connection):
        """Test update_firewall_group returns False when not connected."""
        mock_connection.ensure_connected.return_value = False

        with pytest.raises(ConnectionError, match="Not connected to controller"):
            await firewall_manager.update_firewall_group("g1", {"name": "Test"})

    @pytest.mark.asyncio
    async def test_update_firewall_group_handles_error(self, firewall_manager, mock_connection):
        """Test update_firewall_group returns False on error."""
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await firewall_manager.update_firewall_group("g1", {"name": "Test"})

    # ---- delete_firewall_group ----

    @pytest.mark.asyncio
    async def test_delete_firewall_group_success(self, firewall_manager, mock_connection):
        """Test delete_firewall_group with valid ID."""
        mock_connection.request.return_value = {"meta": {"rc": "ok"}, "data": []}

        result = await firewall_manager.delete_firewall_group("g1")

        assert result is True
        mock_connection._invalidate_cache.assert_called()

    @pytest.mark.asyncio
    async def test_delete_firewall_group_not_connected(self, firewall_manager, mock_connection):
        """Test delete_firewall_group returns False when not connected."""
        mock_connection.ensure_connected.return_value = False

        with pytest.raises(ConnectionError, match="Not connected to controller"):
            await firewall_manager.delete_firewall_group("g1")

    @pytest.mark.asyncio
    async def test_delete_firewall_group_handles_error(self, firewall_manager, mock_connection):
        """Test delete_firewall_group returns False on error."""
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await firewall_manager.delete_firewall_group("g1")

    # ---- API path verification ----

    @pytest.mark.asyncio
    async def test_list_uses_correct_path(self, firewall_manager, mock_connection):
        """Test get_firewall_groups calls the correct v1 REST endpoint."""
        mock_connection.request.return_value = {"data": []}

        await firewall_manager.get_firewall_groups()

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/rest/firewallgroup"

    @pytest.mark.asyncio
    async def test_get_by_id_uses_correct_path(self, firewall_manager, mock_connection):
        """Test get_firewall_group_by_id calls the correct endpoint."""
        mock_connection.request.return_value = {"data": [{"_id": "g1"}]}

        await firewall_manager.get_firewall_group_by_id("g1")

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/rest/firewallgroup/g1"

    @pytest.mark.asyncio
    async def test_create_uses_correct_path_and_method(self, firewall_manager, mock_connection):
        """Test create_firewall_group uses POST to the correct endpoint."""
        mock_connection.request.return_value = {"data": [{"_id": "new1"}]}

        await firewall_manager.create_firewall_group(
            {"name": "Test", "group_type": "address-group", "group_members": []}
        )

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/rest/firewallgroup"
        assert api_request.method == "post"

    @pytest.mark.asyncio
    async def test_update_uses_correct_path_and_method(self, firewall_manager, mock_connection):
        """Test update_firewall_group uses PUT to the correct endpoint."""
        mock_connection.request.side_effect = [
            {"data": [{"_id": "g1", "name": "Original", "group_type": "address-group", "group_members": []}]},
            {},
        ]

        await firewall_manager.update_firewall_group("g1", {"name": "Updated"})

        api_request = mock_connection.request.call_args_list[1].args[0]
        assert api_request.path == "/rest/firewallgroup/g1"
        assert api_request.method == "put"

    @pytest.mark.asyncio
    async def test_delete_uses_correct_path_and_method(self, firewall_manager, mock_connection):
        """Test delete_firewall_group uses DELETE to the correct endpoint."""
        mock_connection.request.return_value = {}

        await firewall_manager.delete_firewall_group("g1")

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/rest/firewallgroup/g1"
        assert api_request.method == "delete"
