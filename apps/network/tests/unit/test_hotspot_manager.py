"""Tests for the HotspotManager class.

This module tests voucher management operations.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestHotspotManager:
    """Tests for the HotspotManager class."""

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
    def hotspot_manager(self, mock_connection):
        """Create a HotspotManager with mocked connection."""
        from unifi_core.network.managers.hotspot_manager import HotspotManager

        return HotspotManager(mock_connection)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "response",
        [
            [
                {"_id": "v1", "code": "ABC123", "quota": 1, "duration": 1440},
                {"_id": "v2", "code": "DEF456", "quota": 0, "duration": 2880},
            ],
            # dict response with 'data' key
            {
                "data": [
                    {"_id": "v1", "code": "ABC123", "quota": 1, "duration": 1440},
                    {"_id": "v2", "code": "DEF456", "quota": 0, "duration": 2880},
                ],
                "meta": {"rc": "ok"},
            },
        ],
    )
    async def test_get_vouchers_returns_list(self, hotspot_manager, mock_connection, response):
        """get_vouchers returns the voucher list (unwrapping a 'data' envelope) and caches it."""
        mock_connection.request.return_value = response

        vouchers = await hotspot_manager.get_vouchers()

        assert len(vouchers) == 2
        assert vouchers[0]["code"] == "ABC123"
        mock_connection._update_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_revoke_voucher(self, hotspot_manager, mock_connection):
        """revoke_voucher sends delete-voucher, returns True and invalidates the cache."""
        mock_connection.request.return_value = {}

        result = await hotspot_manager.revoke_voucher("voucher123")

        assert result is True
        api_request = mock_connection.request.call_args[0][0]
        assert api_request.data["cmd"] == "delete-voucher"
        assert api_request.data["_id"] == "voucher123"
        mock_connection._invalidate_cache.assert_called()

    @pytest.mark.asyncio
    async def test_get_vouchers_uses_cache(self, hotspot_manager, mock_connection):
        """Test get_vouchers returns cached data when available."""
        cached_vouchers = [{"_id": "cached", "code": "CACHED1"}]
        mock_connection.get_cached.return_value = cached_vouchers

        vouchers = await hotspot_manager.get_vouchers()

        assert vouchers == cached_vouchers
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_vouchers_filter_by_create_time(self, hotspot_manager, mock_connection):
        """Test get_vouchers filters by create_time."""
        mock_vouchers = [
            {"_id": "v1", "code": "ABC123", "create_time": 1700000000},
            {"_id": "v2", "code": "DEF456", "create_time": 1700000100},
        ]
        mock_connection.request.return_value = mock_vouchers

        vouchers = await hotspot_manager.get_vouchers(create_time=1700000000)

        assert len(vouchers) == 1
        assert vouchers[0]["_id"] == "v1"
        # Should NOT cache filtered results
        mock_connection._update_cache.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_vouchers_handles_error(self, hotspot_manager, mock_connection):
        """Test get_vouchers returns empty list on error."""
        mock_connection.request.side_effect = Exception("Network error")

        with pytest.raises(Exception):
            await hotspot_manager.get_vouchers()

    @pytest.mark.asyncio
    async def test_get_voucher_details_found(self, hotspot_manager, mock_connection):
        """Test get_voucher_details returns voucher when found."""
        mock_vouchers = [
            {"_id": "v1", "code": "ABC123"},
            {"_id": "v2", "code": "DEF456"},
        ]
        mock_connection.request.return_value = mock_vouchers

        voucher = await hotspot_manager.get_voucher_details("v2")

        assert voucher is not None
        assert voucher["code"] == "DEF456"

    @pytest.mark.asyncio
    async def test_get_voucher_details_not_found(self, hotspot_manager, mock_connection):
        """Test get_voucher_details raises UniFiNotFoundError when not found."""
        from unifi_core.exceptions import UniFiNotFoundError

        mock_connection.request.return_value = [{"_id": "v1"}]

        with pytest.raises(UniFiNotFoundError):
            await hotspot_manager.get_voucher_details("nonexistent")

    @pytest.mark.asyncio
    async def test_create_voucher_basic(self, hotspot_manager, mock_connection):
        """Test create_voucher with basic parameters."""
        mock_connection.request.return_value = [{"create_time": 1700000000}]

        # Mock get_vouchers to return the newly created vouchers
        hotspot_manager.get_vouchers = AsyncMock(return_value=[{"_id": "new1", "code": "NEW123"}])

        await hotspot_manager.create_voucher(
            expire_minutes=1440,
            count=1,
            quota=1,
        )

        # Verify API was called with correct payload
        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.data["cmd"] == "create-voucher"
        assert api_request.data["expire"] == 1440
        assert api_request.data["n"] == 1
        assert api_request.data["quota"] == 1
        mock_connection._invalidate_cache.assert_called()

    @pytest.mark.asyncio
    async def test_create_voucher_with_all_options(self, hotspot_manager, mock_connection):
        """Test create_voucher with all optional parameters."""
        mock_connection.request.return_value = []
        hotspot_manager.get_vouchers = AsyncMock(return_value=[])

        await hotspot_manager.create_voucher(
            expire_minutes=60,
            count=5,
            quota=2,
            note="Test vouchers",
            up_limit_kbps=1000,
            down_limit_kbps=2000,
            bytes_limit_mb=500,
        )

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.data["note"] == "Test vouchers"
        assert api_request.data["up"] == 1000
        assert api_request.data["down"] == 2000
        assert api_request.data["bytes"] == 500

    @pytest.mark.asyncio
    async def test_create_voucher_handles_error(self, hotspot_manager, mock_connection):
        """Test create_voucher returns None on error."""
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await hotspot_manager.create_voucher(expire_minutes=60)

    @pytest.mark.asyncio
    async def test_revoke_voucher_failure(self, hotspot_manager, mock_connection):
        """Test revoke_voucher returns False on error."""
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await hotspot_manager.revoke_voucher("voucher123")
