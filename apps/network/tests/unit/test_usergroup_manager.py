"""Tests for the UsergroupManager class.

This module tests user group (bandwidth profile) operations.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestUsergroupManager:
    """Tests for the UsergroupManager class."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock ConnectionManager."""
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        conn.get_cached = MagicMock(return_value=None)
        conn._update_cache = MagicMock()
        conn._invalidate_cache = MagicMock()
        return conn

    @pytest.fixture
    def usergroup_manager(self, mock_connection):
        """Create a UsergroupManager with mocked connection."""
        from unifi_core.network.managers.usergroup_manager import UsergroupManager

        return UsergroupManager(mock_connection)

    @pytest.mark.asyncio
    async def test_get_usergroups_uses_cache(self, usergroup_manager, mock_connection):
        """Test get_usergroups returns cached data when available."""
        cached_groups = [{"_id": "cached", "name": "Cached Group"}]
        mock_connection.get_cached.return_value = cached_groups

        groups = await usergroup_manager.get_usergroups()

        assert groups == cached_groups
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_usergroups_handles_dict_response(self, usergroup_manager, mock_connection):
        """Test get_usergroups handles dict response with 'data' key."""
        mock_connection.request.return_value = {
            "data": [{"_id": "g1", "name": "Test"}],
            "meta": {"rc": "ok"},
        }

        groups = await usergroup_manager.get_usergroups()

        assert len(groups) == 1
        assert groups[0]["name"] == "Test"
        mock_connection._update_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_usergroups_handles_error(self, usergroup_manager, mock_connection):
        """Test get_usergroups returns empty list on error."""
        mock_connection.request.side_effect = Exception("Network error")

        with pytest.raises(Exception):
            await usergroup_manager.get_usergroups()

    @pytest.mark.asyncio
    async def test_get_usergroup_details_found(self, usergroup_manager, mock_connection):
        """Test get_usergroup_details returns group when found."""
        mock_groups = [
            {"_id": "g1", "name": "Default"},
            {"_id": "g2", "name": "Limited"},
        ]
        mock_connection.request.return_value = mock_groups

        group = await usergroup_manager.get_usergroup_details("g2")

        assert group is not None
        assert group["name"] == "Limited"

    @pytest.mark.asyncio
    async def test_get_usergroup_details_not_found(self, usergroup_manager, mock_connection):
        """Test get_usergroup_details raises UniFiNotFoundError when not found."""
        from unifi_core.exceptions import UniFiNotFoundError

        mock_connection.request.return_value = [{"_id": "g1"}]

        with pytest.raises(UniFiNotFoundError):
            await usergroup_manager.get_usergroup_details("nonexistent")

    @pytest.mark.asyncio
    async def test_create_usergroup_basic(self, usergroup_manager, mock_connection):
        """Test create_usergroup with only name."""
        mock_connection.request.return_value = [{"_id": "new1", "name": "New Group"}]

        await usergroup_manager.create_usergroup(name="New Group")

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.data["name"] == "New Group"
        assert "qos_rate_max_down" not in api_request.data
        mock_connection._invalidate_cache.assert_called()

    @pytest.mark.asyncio
    async def test_create_usergroup_with_limits(self, usergroup_manager, mock_connection):
        """Test create_usergroup with bandwidth limits."""
        mock_connection.request.return_value = [{"_id": "new1", "name": "Limited", "qos_rate_max_down": 10000}]

        await usergroup_manager.create_usergroup(
            name="Limited",
            down_limit_kbps=10000,
            up_limit_kbps=5000,
        )

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.data["qos_rate_max_down"] == 10000
        assert api_request.data["qos_rate_max_up"] == 5000

    @pytest.mark.asyncio
    async def test_create_usergroup_handles_error(self, usergroup_manager, mock_connection):
        """Test create_usergroup returns None on error."""
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await usergroup_manager.create_usergroup(name="Test")

    @pytest.mark.asyncio
    async def test_update_usergroup_success(self, usergroup_manager, mock_connection):
        """Test update_usergroup with valid parameters."""
        # First call returns existing groups (for get_usergroup_details)
        # Second call is the actual update
        mock_connection.request.side_effect = [
            [{"_id": "g1", "name": "Old Name"}],  # get_usergroups
            {},  # update response
        ]

        result = await usergroup_manager.update_usergroup(
            group_id="g1",
            name="New Name",
            down_limit_kbps=5000,
        )

        assert result is True
        # Verify the update call
        update_call = mock_connection.request.call_args_list[1]
        api_request = update_call[0][0]
        assert api_request.data["name"] == "New Name"
        assert api_request.data["qos_rate_max_down"] == 5000
        mock_connection._invalidate_cache.assert_called()

    @pytest.mark.asyncio
    async def test_update_usergroup_not_found(self, usergroup_manager, mock_connection):
        """Test update_usergroup raises UniFiNotFoundError when group missing."""
        from unifi_core.exceptions import UniFiNotFoundError

        mock_connection.request.return_value = []  # No groups

        with pytest.raises(UniFiNotFoundError):
            await usergroup_manager.update_usergroup(
                group_id="nonexistent",
                name="Test",
            )

    @pytest.mark.asyncio
    async def test_update_usergroup_no_updates(self, usergroup_manager, mock_connection):
        """Test update_usergroup returns False when no updates provided."""
        mock_connection.request.return_value = [{"_id": "g1", "name": "Test"}]

        result = await usergroup_manager.update_usergroup(group_id="g1")

        assert result is False

    @pytest.mark.asyncio
    async def test_update_usergroup_handles_error(self, usergroup_manager, mock_connection):
        """Test update_usergroup raises on API error."""
        mock_connection.request.side_effect = [
            [{"_id": "g1", "name": "Test"}],  # get_usergroups succeeds
            Exception("API error"),  # update fails
        ]

        with pytest.raises(Exception, match="API error"):
            await usergroup_manager.update_usergroup(group_id="g1", name="New")
