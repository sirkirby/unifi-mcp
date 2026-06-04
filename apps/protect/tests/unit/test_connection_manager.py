"""Tests for ProtectConnectionManager."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unifi_core.protect.managers.connection_manager import ProtectConnectionManager


@pytest.fixture
def cm():
    """Create a ProtectConnectionManager with test params."""
    return ProtectConnectionManager(
        host="192.168.1.1",
        username="admin",
        password="secret",
        port=443,
        site="default",
        verify_ssl=False,
        api_key="test-api-key",
    )


class TestInit:
    def test_stores_connection_params(self, cm):
        assert cm.host == "192.168.1.1"
        assert cm.username == "admin"
        assert cm.password == "secret"
        assert cm.port == 443
        assert cm.site == "default"
        assert cm.verify_ssl is False
        assert cm._api_key == "test-api-key"

    def test_initial_state(self, cm):
        assert cm._client is None
        assert cm._api_session is None
        assert cm._ws_unsub is None
        assert cm._initialized is False
        assert cm.is_connected is False

    def test_default_api_key_none(self):
        cm = ProtectConnectionManager(host="h", username="u", password="p")
        assert cm._api_key is None


class TestClientProperty:
    def test_raises_when_not_initialized(self, cm):
        from unifi_core.exceptions import UniFiConnectionError

        with pytest.raises(UniFiConnectionError, match="not initialized"):
            _ = cm.client

    def test_returns_client_when_initialized(self, cm):
        mock_client = MagicMock()
        cm._client = mock_client
        cm._initialized = True
        assert cm.client is mock_client


class TestIsConnected:
    def test_false_when_not_initialized(self, cm):
        assert cm.is_connected is False

    def test_false_when_client_none(self, cm):
        cm._initialized = True
        cm._client = None
        assert cm.is_connected is False

    def test_delegates_to_is_authenticated(self, cm):
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        cm._client = mock_client
        cm._initialized = True
        assert cm.is_connected is True
        mock_client.is_authenticated.assert_called_once()

    def test_false_when_is_authenticated_raises(self, cm):
        mock_client = MagicMock()
        mock_client.is_authenticated.side_effect = Exception("boom")
        cm._client = mock_client
        cm._initialized = True
        assert cm.is_connected is False


class TestApiSession:
    @pytest.mark.asyncio
    async def test_creates_session_with_api_key(self, cm):
        session = cm.api_session
        assert session is not None
        assert not session.closed
        # Verify the API key header was set
        assert session.headers.get("X-API-Key") == "test-api-key"
        await session.close()

    @pytest.mark.asyncio
    async def test_creates_session_without_api_key(self):
        cm = ProtectConnectionManager(host="h", username="u", password="p")
        session = cm.api_session
        assert session is not None
        assert "X-API-Key" not in session.headers
        await session.close()

    @pytest.mark.asyncio
    async def test_returns_same_session(self, cm):
        s1 = cm.api_session
        s2 = cm.api_session
        assert s1 is s2
        await s1.close()


class TestInitialize:
    @pytest.mark.asyncio
    async def test_successful_initialization(self, cm):
        mock_client = MagicMock()
        mock_client.update = AsyncMock()

        with patch(
            "unifi_core.protect.managers.connection_manager.ProtectApiClient",
            return_value=mock_client,
        ) as protect_client:
            result = await cm.initialize()

        assert result is True
        assert cm._initialized is True
        assert cm._client is mock_client
        protect_client.assert_called_once_with(
            host="192.168.1.1",
            port=443,
            username="admin",
            password="secret",
            api_key="test-api-key",
            verify_ssl=False,
        )
        mock_client.update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_true_when_already_initialized(self, cm):
        cm._initialized = True
        cm._client = MagicMock()

        result = await cm.initialize()
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_persistent_failure(self, cm):
        mock_client = MagicMock()
        mock_client.update = AsyncMock(side_effect=ConnectionError("down"))

        with (
            patch(
                "unifi_core.protect.managers.connection_manager.ProtectApiClient",
                return_value=mock_client,
            ),
            patch(
                "unifi_core.protect.managers.connection_manager.retry_with_backoff",
                side_effect=ConnectionError("down after retries"),
            ),
        ):
            result = await cm.initialize()

        assert result is False
        assert cm._initialized is False


class TestClose:
    @pytest.mark.asyncio
    async def test_close_cleans_up_all_resources(self, cm):
        mock_client = MagicMock()
        mock_client.async_disconnect_ws = AsyncMock()
        mock_client.close_session = AsyncMock()
        cm._client = mock_client
        cm._initialized = True

        mock_unsub = MagicMock()
        cm._ws_unsub = mock_unsub

        await cm.close()

        mock_unsub.assert_called_once()
        mock_client.async_disconnect_ws.assert_awaited_once()
        mock_client.close_session.assert_awaited_once()
        assert cm._client is None
        assert cm._initialized is False
        assert cm._ws_unsub is None

    @pytest.mark.asyncio
    async def test_close_on_fresh_instance(self, cm):
        # Should not raise
        await cm.close()
        assert cm._initialized is False

    @pytest.mark.asyncio
    async def test_close_handles_ws_unsub_error(self, cm):
        cm._ws_unsub = MagicMock(side_effect=RuntimeError("unsub error"))
        cm._client = MagicMock()
        cm._client.async_disconnect_ws = AsyncMock()
        cm._client.close_session = AsyncMock()
        cm._initialized = True

        # Should not raise despite the unsub error
        await cm.close()
        assert cm._ws_unsub is None


class TestStartWebsocket:
    @pytest.mark.asyncio
    async def test_start_websocket_with_callback(self, cm):
        mock_client = MagicMock()
        mock_unsub = MagicMock()
        mock_client.subscribe_websocket.return_value = mock_unsub
        cm._client = mock_client
        cm._initialized = True

        callback = MagicMock()
        await cm.start_websocket(callback=callback)

        mock_client.subscribe_websocket.assert_called_once_with(callback)
        assert cm._ws_unsub is mock_unsub

    @pytest.mark.asyncio
    async def test_start_websocket_default_callback(self, cm):
        mock_client = MagicMock()
        mock_unsub = MagicMock()
        mock_client.subscribe_websocket.return_value = mock_unsub
        cm._client = mock_client
        cm._initialized = True

        await cm.start_websocket()

        mock_client.subscribe_websocket.assert_called_once()
        # The callback should be a function (the default no-op logger)
        cb_arg = mock_client.subscribe_websocket.call_args[0][0]
        assert callable(cb_arg)

    @pytest.mark.asyncio
    async def test_start_websocket_raises_when_not_initialized(self, cm):
        from unifi_core.exceptions import UniFiConnectionError

        with pytest.raises(UniFiConnectionError, match="not initialized"):
            await cm.start_websocket()
