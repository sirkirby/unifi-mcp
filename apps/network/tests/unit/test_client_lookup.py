"""Tests for the client IP lookup functionality.

This module tests get_client_by_ip method in ClientManager.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestGetClientByIP:
    """Tests for get_client_by_ip."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock ConnectionManager."""
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        conn.get_cached = MagicMock(return_value=None)
        conn._update_cache = MagicMock()
        conn._invalidate_cache = MagicMock()
        conn.controller = MagicMock()
        conn.controller.clients = MagicMock()
        conn.controller.clients.update = AsyncMock()
        conn.controller.clients.values = MagicMock(return_value=[])
        conn.controller.clients_all = MagicMock()
        conn.controller.clients_all.update = AsyncMock()
        conn.controller.clients_all.values = MagicMock(return_value=[])
        conn.ensure_connected = AsyncMock(return_value=True)

        # ConnectionManager.refresh_handler() is how the managers refresh a
        # handler collection now; delegate to the same ``update()`` these
        # tests already stub so their setup keeps its meaning.
        async def _refresh_handler(name, _c=conn):
            return await getattr(_c.controller, name).update()

        conn.refresh_handler = _refresh_handler
        return conn

    @pytest.fixture
    def client_manager(self, mock_connection):
        """Create a ClientManager with mocked connection."""
        from unifi_core.network.managers.client_manager import ClientManager

        return ClientManager(mock_connection)

    @pytest.fixture
    def mock_client(self):
        """Create a mock client object with Client model properties."""
        client = MagicMock()
        client.mac = "aa:bb:cc:dd:ee:ff"
        client.ip = "192.168.1.100"
        client.name = "test-pc"
        client.hostname = "test-device"
        client.blocked = False
        client.raw = {
            "_id": "client123",
            "mac": "aa:bb:cc:dd:ee:ff",
            "ip": "192.168.1.100",
            "hostname": "test-device",
            "name": "test-pc",
        }
        return client

    @pytest.mark.asyncio
    async def test_lookup_ip_found_online(self, client_manager, mock_connection, mock_client):
        """Test successful IP lookup from online clients."""
        mock_connection.controller.clients.values.return_value = [mock_client]

        result = await client_manager.get_client_by_ip("192.168.1.100")

        assert result is mock_client

    @pytest.mark.asyncio
    async def test_lookup_ip_found_in_all_clients(self, client_manager, mock_connection, mock_client):
        """Test IP lookup falls back to all clients when not found online."""
        mock_connection.controller.clients.values.return_value = []
        mock_connection.controller.clients_all.values.return_value = [mock_client]

        result = await client_manager.get_client_by_ip("192.168.1.100")

        assert result is mock_client

    @pytest.mark.asyncio
    async def test_lookup_ip_not_found(self, client_manager, mock_connection):
        """Test returns None when IP not found."""
        mock_connection.controller.clients.values.return_value = []
        mock_connection.controller.clients_all.values.return_value = []

        result = await client_manager.get_client_by_ip("10.0.0.99")

        assert result is None

    @pytest.mark.asyncio
    async def test_lookup_ip_invalid_format(self, client_manager):
        """Test returns None for malformed IP address."""
        result = await client_manager.get_client_by_ip("not-an-ip")
        assert result is None

        result = await client_manager.get_client_by_ip("192.168.1")
        assert result is None

        result = await client_manager.get_client_by_ip("")
        assert result is None

    @pytest.mark.asyncio
    async def test_lookup_ip_prefers_online_over_historical(self, client_manager, mock_connection):
        """Test that online clients are returned over historical ones."""
        online_client = MagicMock()
        online_client.ip = "192.168.1.100"
        online_client.mac = "aa:aa:aa:aa:aa:aa"

        historical_client = MagicMock()
        historical_client.ip = "192.168.1.100"
        historical_client.mac = "bb:bb:bb:bb:bb:bb"

        mock_connection.controller.clients.values.return_value = [online_client]
        mock_connection.controller.clients_all.values.return_value = [historical_client]

        result = await client_manager.get_client_by_ip("192.168.1.100")

        assert result is online_client

    @pytest.mark.asyncio
    async def test_lookup_ip_matches_last_ip_of_offline_client(self, client_manager, mock_connection):
        """Historical /rest/user records report the address as last_ip, not ip."""
        offline_client = MagicMock()
        offline_client.mac = "aa:bb:cc:00:00:01"
        offline_client.raw = {"mac": "aa:bb:cc:00:00:01", "last_ip": "192.0.2.127", "last_seen": 100}

        mock_connection.controller.clients.values.return_value = []
        mock_connection.controller.clients_all.values.return_value = [offline_client]

        result = await client_manager.get_client_by_ip("192.0.2.127")

        assert result is offline_client

    @pytest.mark.asyncio
    async def test_lookup_ip_prefers_most_recently_seen_historical_client(self, client_manager, mock_connection):
        """When several offline clients once held the address, return the freshest."""
        older = MagicMock()
        older.raw = {"mac": "aa:bb:cc:00:00:01", "last_ip": "192.0.2.33", "last_seen": 100}
        newer = MagicMock()
        newer.raw = {"mac": "aa:bb:cc:00:00:02", "last_ip": "192.0.2.33", "last_seen": 200}

        mock_connection.controller.clients.values.return_value = []
        mock_connection.controller.clients_all.values.return_value = [older, newer]

        result = await client_manager.get_client_by_ip("192.0.2.33")

        assert result is newer
