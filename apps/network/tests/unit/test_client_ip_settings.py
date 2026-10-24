"""Tests for the client IP settings functionality.

This module tests the set_client_ip_settings method in ClientManager.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestClientIPSettings:
    """Tests for client IP settings operations."""

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
        """Create a mock client object."""
        client = MagicMock()
        client.mac = "aa:bb:cc:dd:ee:ff"
        client.raw = {
            "_id": "client123",
            "mac": "aa:bb:cc:dd:ee:ff",
            "hostname": "test-device",
            "noted": True,
        }
        return client

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            pytest.param(
                {"use_fixedip": True, "fixed_ip": "192.168.1.100"},
                {"use_fixedip": True, "fixed_ip": "192.168.1.100"},
                id="fixed-ip",
            ),
            pytest.param(
                {"fixed_ip": "192.168.1.100"},
                {"use_fixedip": True, "fixed_ip": "192.168.1.100"},
                id="fixed-ip-only-ip-auto-enables",
            ),
            pytest.param({"use_fixedip": False}, {"use_fixedip": False, "fixed_ip": ""}, id="disable-fixed-ip"),
            pytest.param(
                {"local_dns_record_enabled": True, "local_dns_record": "mydevice.local"},
                {"local_dns_record_enabled": True, "local_dns_record": "mydevice.local"},
                id="local-dns",
            ),
            pytest.param(
                {"local_dns_record": "mydevice.local"},
                {"local_dns_record_enabled": True, "local_dns_record": "mydevice.local"},
                id="local-dns-only-hostname-auto-enables",
            ),
            pytest.param(
                {"local_dns_record_enabled": False},
                {"local_dns_record_enabled": False, "local_dns_record": ""},
                id="disable-local-dns",
            ),
            pytest.param(
                {
                    "use_fixedip": True,
                    "fixed_ip": "192.168.1.100",
                    "local_dns_record_enabled": True,
                    "local_dns_record": "mydevice.local",
                },
                {
                    "use_fixedip": True,
                    "fixed_ip": "192.168.1.100",
                    "local_dns_record_enabled": True,
                    "local_dns_record": "mydevice.local",
                },
                id="both-ip-and-dns",
            ),
        ],
    )
    async def test_sends_expected_settings(self, client_manager, mock_connection, mock_client, kwargs, expected):
        mock_connection.controller.clients_all.values.return_value = [mock_client]
        mock_connection.request.return_value = {}

        result = await client_manager.set_client_ip_settings(client_mac="aa:bb:cc:dd:ee:ff", **kwargs)

        assert result is True
        api_request = mock_connection.request.call_args[0][0]
        for key, value in expected.items():
            assert api_request.data[key] == value
        mock_connection._invalidate_cache.assert_called()

    @pytest.mark.asyncio
    async def test_client_not_found(self, client_manager, mock_connection):
        """Test raises UniFiNotFoundError when client missing."""
        from unifi_core.exceptions import UniFiNotFoundError

        mock_connection.controller.clients_all.values.return_value = []

        with pytest.raises(UniFiNotFoundError):
            await client_manager.set_client_ip_settings(
                client_mac="xx:xx:xx:xx:xx:xx",
                fixed_ip="192.168.1.100",
            )

    @pytest.mark.asyncio
    async def test_no_settings_provided(self, client_manager, mock_connection, mock_client):
        """Test returns False when no settings provided."""
        mock_connection.controller.clients_all.values.return_value = [mock_client]

        result = await client_manager.set_client_ip_settings(
            client_mac="aa:bb:cc:dd:ee:ff",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_marks_unnoted_client_as_noted(self, client_manager, mock_connection):
        """Test marks unnoted client as noted before setting IP."""
        unnoted_client = MagicMock()
        unnoted_client.mac = "aa:bb:cc:dd:ee:ff"
        unnoted_client.raw = {
            "_id": "client123",
            "mac": "aa:bb:cc:dd:ee:ff",
            "hostname": "test-device",
            "noted": False,  # Client is not noted
        }
        mock_connection.controller.clients_all.values.return_value = [unnoted_client]
        mock_connection.request.return_value = {}

        await client_manager.set_client_ip_settings(
            client_mac="aa:bb:cc:dd:ee:ff",
            fixed_ip="192.168.1.100",
        )

        # get_client_details first probes /stat/sta (active clients) before falling
        # back to /rest/user, so we see: GET /stat/sta, PUT note=True, PUT fixed_ip.
        # Assert the noted request is among them rather than position-indexing.
        write_requests = [
            call[0][0]
            for call in mock_connection.request.call_args_list
            if getattr(call[0][0], "data", None) is not None
        ]
        assert any(r.data.get("noted") is True for r in write_requests)
        assert any(r.data.get("use_fixedip") is True for r in write_requests)

    @pytest.mark.asyncio
    async def test_handles_api_error(self, client_manager, mock_connection, mock_client):
        """Test returns False on API error."""
        mock_connection.controller.clients_all.values.return_value = [mock_client]
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await client_manager.set_client_ip_settings(
                client_mac="aa:bb:cc:dd:ee:ff",
                fixed_ip="192.168.1.100",
            )

    @pytest.mark.asyncio
    async def test_client_missing_id(self, client_manager, mock_connection):
        """Test returns False when client has no _id."""
        client_without_id = MagicMock()
        client_without_id.mac = "aa:bb:cc:dd:ee:ff"
        client_without_id.raw = {
            "mac": "aa:bb:cc:dd:ee:ff",
            # No _id field
        }
        mock_connection.controller.clients_all.values.return_value = [client_without_id]

        result = await client_manager.set_client_ip_settings(
            client_mac="aa:bb:cc:dd:ee:ff",
            fixed_ip="192.168.1.100",
        )
        assert result is False
