"""Tests for Dynamic DNS management in DynamicDnsManager.

Tests list, get, create, update, delete over the V1 ``/rest/dynamicdns``
endpoint. Mirrors ``test_dns_manager.py`` but for the V1 REST resource.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from unifi_core.exceptions import UniFiNotFoundError


class TestDynamicDnsManager:
    """Tests for DynamicDnsManager methods."""

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
    def ddns_manager(self, mock_connection):
        """Create a DynamicDnsManager with mocked connection."""
        from unifi_core.network.managers.dynamic_dns_manager import DynamicDnsManager

        return DynamicDnsManager(mock_connection)

    # ---- List ----

    @pytest.mark.asyncio
    async def test_list_returns_list(self, ddns_manager, mock_connection):
        """list_dynamic_dns returns list of entry dicts."""
        entries = [
            {"_id": "d1", "host_name": "home.example.com", "service": "dyndns", "interface": "wan"},
            {"_id": "d2", "host_name": "alt.example.com", "service": "noip", "interface": "wan2"},
        ]
        mock_connection.request.return_value = entries

        result = await ddns_manager.list_dynamic_dns()

        assert len(result) == 2
        assert result[0]["host_name"] == "home.example.com"
        assert mock_connection.request.call_args[0][0].path == "/rest/dynamicdns"

    @pytest.mark.asyncio
    async def test_list_uses_cache(self, ddns_manager, mock_connection):
        """list_dynamic_dns returns cached data without hitting the controller."""
        cached = [{"_id": "d1", "host_name": "cached.example.com"}]
        mock_connection.get_cached.return_value = cached

        result = await ddns_manager.list_dynamic_dns()

        assert result == cached
        mock_connection.request.assert_not_called()

    # ---- Get ----

    @pytest.mark.asyncio
    async def test_get_found(self, ddns_manager, mock_connection):
        """get_dynamic_dns returns the entry when found (list-and-filter)."""
        entries = [
            {"_id": "d1", "host_name": "home.example.com"},
            {"_id": "d2", "host_name": "other.example.com"},
        ]
        mock_connection.request.return_value = entries

        result = await ddns_manager.get_dynamic_dns("d1")

        assert result is not None
        assert result["host_name"] == "home.example.com"

    # ---- Update ----

    @pytest.mark.asyncio
    async def test_update_success(self, ddns_manager, mock_connection):
        """update_dynamic_dns uses fetch-merge-put and preserves unpassed fields."""
        existing = [
            {"_id": "d1", "host_name": "home.example.com", "service": "dyndns", "login": "user", "interface": "wan"}
        ]
        # First call: list (for get_dynamic_dns), second call: PUT
        mock_connection.request.side_effect = [existing, {}]

        result = await ddns_manager.update_dynamic_dns("d1", {"service": "noip"})

        assert result["_id"] == "d1"
        assert result["service"] == "noip"  # updated
        assert result["login"] == "user"  # preserved
        assert result["host_name"] == "home.example.com"  # preserved
        put_call = mock_connection.request.call_args_list[1]
        put_req = put_call[0][0]
        assert put_req.method == "put"
        assert "d1" in put_req.path

    # ---- Delete ----

    @pytest.mark.asyncio
    async def test_delete_success(self, ddns_manager, mock_connection):
        """delete_dynamic_dns sends DELETE and invalidates cache."""
        mock_connection.request.return_value = {}

        result = await ddns_manager.delete_dynamic_dns("d1")

        assert result is True
        api_req = mock_connection.request.call_args[0][0]
        assert api_req.method == "delete"
        assert "d1" in api_req.path
        mock_connection._invalidate_cache.assert_called_once()

    # ---- Errors ----

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method, args",
        [
            ("list_dynamic_dns", ()),
            ("create_dynamic_dns", ({"host_name": "fail.example.com"},)),
            ("update_dynamic_dns", ("d1", {"service": "noip"})),
            ("delete_dynamic_dns", ("d1",)),
        ],
    )
    async def test_controller_errors_propagate(self, ddns_manager, mock_connection, method, args):
        mock_connection.request.side_effect = Exception("Failed")

        with pytest.raises(Exception):
            await getattr(ddns_manager, method)(*args)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method, args, listing",
        [
            ("get_dynamic_dns", ("nonexistent",), [{"_id": "d1"}]),
            ("update_dynamic_dns", ("nonexistent", {"service": "noip"}), []),
        ],
    )
    async def test_not_found_raises(self, ddns_manager, mock_connection, method, args, listing):
        """Get and update raise UniFiNotFoundError when the id is absent."""
        mock_connection.request.return_value = listing

        with pytest.raises(UniFiNotFoundError):
            await getattr(ddns_manager, method)(*args)

    # ---- API Path Verification ----

    @pytest.mark.asyncio
    async def test_create_uses_post(self, ddns_manager, mock_connection):
        """create_dynamic_dns POSTs to /rest/dynamicdns, returns the entry, invalidates cache."""
        mock_connection.request.return_value = {"_id": "new"}

        result = await ddns_manager.create_dynamic_dns({"host_name": "test.example.com", "service": "dyndns"})

        api_req = mock_connection.request.call_args[0][0]
        assert api_req.method == "post"
        assert api_req.path == "/rest/dynamicdns"
        assert result["_id"] == "new"
        mock_connection._invalidate_cache.assert_called_once()
