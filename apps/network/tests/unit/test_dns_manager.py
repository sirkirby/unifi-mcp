"""Tests for DNS record management in DnsManager.

Tests list, get, create, update, delete DNS records.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from unifi_core.exceptions import UniFiNotFoundError


class TestDnsManager:
    """Tests for DnsManager methods."""

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
    def dns_manager(self, mock_connection):
        """Create a DnsManager with mocked connection."""
        from unifi_core.network.managers.dns_manager import DnsManager

        return DnsManager(mock_connection)

    # ---- List DNS Records ----

    @pytest.mark.asyncio
    async def test_list_dns_records_returns_list(self, dns_manager, mock_connection):
        """Test list_dns_records returns list of record dicts."""
        records = [
            {"_id": "r1", "key": "host.example.com", "value": "10.0.0.1", "record_type": "A"},
            {"_id": "r2", "key": "alias.example.com", "value": "host.example.com", "record_type": "CNAME"},
        ]
        mock_connection.request.return_value = records

        result = await dns_manager.list_dns_records()

        assert len(result) == 2
        assert result[0]["key"] == "host.example.com"
        assert mock_connection.request.call_args[0][0].path == "/static-dns"

    @pytest.mark.asyncio
    async def test_list_dns_records_uses_cache(self, dns_manager, mock_connection):
        """Test list_dns_records uses cache when available."""
        cached = [{"_id": "r1", "key": "cached.example.com"}]
        mock_connection.get_cached.return_value = cached

        result = await dns_manager.list_dns_records()

        assert result == cached
        mock_connection.request.assert_not_called()

    # ---- Get DNS Record ----

    @pytest.mark.asyncio
    async def test_get_dns_record_found(self, dns_manager, mock_connection):
        """Test get_dns_record returns record when found."""
        records = [
            {"_id": "r1", "key": "host.example.com", "value": "10.0.0.1"},
            {"_id": "r2", "key": "other.example.com", "value": "10.0.0.2"},
        ]
        mock_connection.request.return_value = records

        result = await dns_manager.get_dns_record("r1")

        assert result is not None
        assert result["key"] == "host.example.com"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method, args, listing",
        [
            ("get_dns_record", ("nonexistent",), [{"_id": "r1"}]),
            ("update_dns_record", ("nonexistent", {"value": "10.0.0.2"}), []),
        ],
    )
    async def test_not_found_raises(self, dns_manager, mock_connection, method, args, listing):
        """Get and update raise UniFiNotFoundError when the record id is absent."""
        mock_connection.request.return_value = listing

        with pytest.raises(UniFiNotFoundError):
            await getattr(dns_manager, method)(*args)

    # ---- Update DNS Record ----

    @pytest.mark.asyncio
    async def test_update_dns_record_success(self, dns_manager, mock_connection):
        """Test update_dns_record uses fetch-merge-put and returns merged record."""
        existing = [{"_id": "r1", "key": "host.example.com", "value": "10.0.0.1", "record_type": "A"}]
        # First call: list (for get_dns_record), second call: PUT
        mock_connection.request.side_effect = [existing, {}]

        result = await dns_manager.update_dns_record("r1", {"value": "10.0.0.2"})

        assert result["_id"] == "r1"
        assert result["value"] == "10.0.0.2"
        assert result["key"] == "host.example.com"
        # Verify PUT was called with merged data
        put_call = mock_connection.request.call_args_list[1]
        put_req = put_call[0][0]
        assert put_req.method == "put"
        assert "r1" in put_req.path

    # ---- Delete DNS Record ----

    @pytest.mark.asyncio
    async def test_delete_dns_record_success(self, dns_manager, mock_connection):
        """Test delete_dns_record sends DELETE request."""
        mock_connection.request.return_value = {}

        result = await dns_manager.delete_dns_record("r1")

        assert result is True
        call_args = mock_connection.request.call_args
        api_req = call_args[0][0]
        assert api_req.method == "delete"
        assert "r1" in api_req.path
        mock_connection._invalidate_cache.assert_called_once()

    # ---- Error propagation ----

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method, args",
        [
            ("list_dns_records", ()),
            ("create_dns_record", ({"key": "fail.example.com"},)),
            ("update_dns_record", ("r1", {"value": "10.0.0.2"})),
            ("delete_dns_record", ("r1",)),
        ],
    )
    async def test_controller_errors_propagate(self, dns_manager, mock_connection, method, args):
        mock_connection.request.side_effect = Exception("Failed")

        with pytest.raises(Exception):
            await getattr(dns_manager, method)(*args)

    # ---- API Path Verification ----

    @pytest.mark.asyncio
    async def test_create_uses_post(self, dns_manager, mock_connection):
        """create_dns_record POSTs to /static-dns, returns the record, invalidates cache."""
        mock_connection.request.return_value = {"_id": "new"}

        result = await dns_manager.create_dns_record({"key": "test", "value": "10.0.0.1", "record_type": "A"})

        api_req = mock_connection.request.call_args[0][0]
        assert api_req.method == "post"
        assert api_req.path == "/static-dns"
        assert result["_id"] == "new"
        mock_connection._invalidate_cache.assert_called_once()
