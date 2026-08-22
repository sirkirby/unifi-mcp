"""Tests for the forget client functionality."""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestForgetClient:
    """Tests for ClientManager.forget_client."""

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
        return conn

    @pytest.fixture
    def client_manager(self, mock_connection):
        """Create a ClientManager with mocked connection."""
        from unifi_core.network.managers.client_manager import ClientManager

        return ClientManager(mock_connection)

    @pytest.mark.asyncio
    async def test_forget_client_success(self, client_manager, mock_connection):
        """Test successful forget client call.

        The MAC goes out lowercased. This assertion previously expected the
        caller's string verbatim; MACs are now normalized at the entry point so
        that the lookup and the outgoing command agree, and the controller
        receives the same casing it reports.
        """
        result = await client_manager.forget_client("AA:BB:CC:DD:EE:FF")

        assert result is True
        mock_connection.request.assert_called_once()
        call_args = mock_connection.request.call_args[0][0]
        assert call_args.method == "post"
        assert call_args.path == "/cmd/stamgr"
        assert call_args.data == {"macs": ["aa:bb:cc:dd:ee:ff"], "cmd": "forget-sta"}
        mock_connection._invalidate_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_forget_client_api_error(self, client_manager, mock_connection):
        """Test forget client returns False on API error."""
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await client_manager.forget_client("AA:BB:CC:DD:EE:FF")

    @pytest.mark.asyncio
    async def test_forget_client_invalidates_cache(self, client_manager, mock_connection):
        """Test that cache is invalidated after forgetting a client."""
        await client_manager.forget_client("AA:BB:CC:DD:EE:FF")

        mock_connection._invalidate_cache.assert_called_once_with("clients")
