"""Tests for the ClientGroupManager class.

This module tests client group (network member group) operations.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

CALLS = [
    lambda m: m.get_client_groups(),
    lambda m: m.get_client_group_by_id("g1"),
    lambda m: m.create_client_group({"name": "Test", "members": [], "type": "CLIENTS"}),
    lambda m: m.update_client_group("g1", {"name": "Test"}),
    lambda m: m.delete_client_group("g1"),
]


class TestClientGroupManager:
    """Tests for the ClientGroupManager class."""

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
    def client_group_manager(self, mock_connection):
        """Create a ClientGroupManager with mocked connection."""
        from unifi_core.network.managers.client_group_manager import ClientGroupManager

        return ClientGroupManager(mock_connection)

    # ---- get_client_groups ----

    @pytest.mark.asyncio
    async def test_get_client_groups_returns_list(self, client_group_manager, mock_connection):
        """Test get_client_groups returns a list of groups."""
        mock_groups = [
            {"id": "g1", "name": "Kids Everything", "type": "CLIENTS", "members": ["aa:bb:cc:dd:ee:ff"]},
            {"id": "g2", "name": "Adults", "type": "CLIENTS", "members": ["11:22:33:44:55:66"]},
        ]
        mock_connection.request.return_value = mock_groups

        groups = await client_group_manager.get_client_groups()

        assert len(groups) == 2
        assert groups[0]["name"] == "Kids Everything"
        mock_connection._update_cache.assert_called_once()
        assert mock_connection.request.call_args[0][0].path == "/network-members-groups"

    @pytest.mark.asyncio
    async def test_get_client_groups_uses_cache(self, client_group_manager, mock_connection):
        """Test get_client_groups returns cached data when available."""
        cached = [{"id": "cached", "name": "Cached Group"}]
        mock_connection.get_cached.return_value = cached

        groups = await client_group_manager.get_client_groups()

        assert groups == cached
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("call", CALLS)
    async def test_not_connected_raises(self, client_group_manager, mock_connection, call):
        """Every manager operation raises when not connected, without sending a request."""
        mock_connection.ensure_connected.return_value = False

        with pytest.raises(ConnectionError, match="Not connected to controller"):
            await call(client_group_manager)

        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("call", CALLS)
    async def test_api_error_propagates(self, client_group_manager, mock_connection, call):
        """API errors propagate from every manager operation."""
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception, match="API error"):
            await call(client_group_manager)

    @pytest.mark.asyncio
    async def test_get_client_groups_handles_dict_response(self, client_group_manager, mock_connection):
        """Test get_client_groups handles dict response with data key."""
        mock_connection.request.return_value = {"data": [{"id": "g1", "name": "Group"}]}

        groups = await client_group_manager.get_client_groups()

        assert len(groups) == 1

    # ---- get_client_group_by_id ----

    @pytest.mark.asyncio
    async def test_get_client_group_by_id_found(self, client_group_manager, mock_connection):
        """Test get_client_group_by_id returns group when found."""
        mock_connection.request.return_value = {"id": "g1", "name": "Test Group", "members": []}

        group = await client_group_manager.get_client_group_by_id("g1")

        assert group is not None
        assert group["name"] == "Test Group"
        assert mock_connection.request.call_args[0][0].path == "/network-members-group/g1"

    # ---- create_client_group ----

    @pytest.mark.asyncio
    async def test_create_client_group_success(self, client_group_manager, mock_connection):
        """Test create_client_group with valid data."""
        group_data = {
            "name": "New Group",
            "members": ["aa:bb:cc:dd:ee:ff"],
            "type": "CLIENTS",
        }
        mock_connection.request.return_value = {"id": "new1", **group_data}

        result = await client_group_manager.create_client_group(group_data)

        assert result is not None
        assert result["id"] == "new1"
        mock_connection._invalidate_cache.assert_called()
        api_request = mock_connection.request.call_args[0][0]
        assert api_request.path == "/network-members-group"
        assert api_request.method == "post"

    @pytest.mark.asyncio
    async def test_create_client_group_missing_required_keys(self, client_group_manager, mock_connection):
        """Test create_client_group returns None when required keys are missing."""
        result = await client_group_manager.create_client_group({"name": "Incomplete"})

        assert result is None
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_client_group_handles_data_wrapper(self, client_group_manager, mock_connection):
        """Test create_client_group handles response with data key."""
        mock_connection.request.return_value = {"data": {"id": "new1", "name": "Test"}}

        result = await client_group_manager.create_client_group(
            {
                "name": "Test",
                "members": [],
                "type": "CLIENTS",
            }
        )

        assert result == {"id": "new1", "name": "Test"}

    # ---- update_client_group ----

    @pytest.mark.asyncio
    async def test_update_client_group_fetches_and_merges(self, client_group_manager, mock_connection):
        """Test update_client_group fetches current group, merges, PUTs full object."""
        existing_group = {
            "id": "g1",
            "name": "IoT Devices",
            "members": ["aa:bb:cc:dd:ee:ff"],
            "type": "CLIENTS",
        }
        mock_connection.request.side_effect = [
            existing_group,  # GET
            {},  # PUT
        ]

        result = await client_group_manager.update_client_group("g1", {"name": "Smart Home Devices"})

        assert result["name"] == "Smart Home Devices"
        put_call = mock_connection.request.call_args_list[1]
        put_request = put_call[0][0]
        assert put_request.method == "put"
        assert put_request.path == "/network-members-group/g1"
        mock_connection._invalidate_cache.assert_called()
        assert put_request.data["name"] == "Smart Home Devices"
        assert put_request.data["members"] == ["aa:bb:cc:dd:ee:ff"]
        assert put_request.data["type"] == "CLIENTS"

    @pytest.mark.asyncio
    async def test_update_client_group_not_found(self, client_group_manager, mock_connection):
        """Test update_client_group raises UniFiNotFoundError when group missing."""
        from unifi_core.exceptions import UniFiNotFoundError

        # First call: by-id GET → None; second call: list fallback also empty.
        mock_connection.request.side_effect = [None, []]

        with pytest.raises(UniFiNotFoundError):
            await client_group_manager.update_client_group("nonexistent", {"name": "Test"})

    @pytest.mark.asyncio
    async def test_update_client_group_empty_update(self, client_group_manager, mock_connection):
        """Test update_client_group with empty data returns existing without PUT."""
        existing = {"id": "g1", "name": "Original"}
        mock_connection.request.return_value = existing

        result = await client_group_manager.update_client_group("g1", {})

        assert result == existing
        # Only the GET (existence check) ran; no PUT.
        assert mock_connection.request.call_count == 1

    # ---- delete_client_group ----

    @pytest.mark.asyncio
    async def test_delete_client_group_success(self, client_group_manager, mock_connection):
        """Test delete_client_group with valid ID."""
        mock_connection.request.return_value = {}

        result = await client_group_manager.delete_client_group("g1")

        assert result is True
        mock_connection._invalidate_cache.assert_called()
        api_request = mock_connection.request.call_args[0][0]
        assert api_request.path == "/network-members-group/g1"
        assert api_request.method == "delete"

    # ---- API path verification ----
