"""Tests for the DpiManager class.

This module tests DPI application and category lookup operations.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestDpiManager:
    """Tests for the DpiManager class."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock ConnectionManager."""
        conn = MagicMock()
        conn.site = "default"
        conn.host = "192.0.2.1"
        conn.port = 443
        conn.tls_env_prefix = "NETWORK"
        conn.get_cached = MagicMock(return_value=None)
        conn._update_cache = MagicMock()
        return conn

    @pytest.fixture
    def mock_auth(self):
        """Create a mock UniFiAuth."""
        auth = MagicMock()
        auth.has_api_key = True
        auth.get_api_key_session = AsyncMock()
        return auth

    @pytest.fixture
    def mock_auth_no_key(self):
        """Create a mock UniFiAuth without API key."""
        auth = MagicMock()
        auth.has_api_key = False
        return auth

    @pytest.fixture
    def dpi_manager(self, mock_connection, mock_auth):
        """Create a DpiManager with mocked connection and auth."""
        from unifi_core.network.managers.dpi_manager import DpiManager

        return DpiManager(mock_connection, mock_auth)

    @pytest.fixture
    def dpi_manager_no_key(self, mock_connection, mock_auth_no_key):
        """Create a DpiManager without API key."""
        from unifi_core.network.managers.dpi_manager import DpiManager

        return DpiManager(mock_connection, mock_auth_no_key)

    # ---- get_dpi_applications ----

    @pytest.mark.asyncio
    async def test_get_dpi_applications_no_api_key(self, dpi_manager_no_key, mock_connection):
        """A missing key is an error, not an empty catalog."""
        from unifi_core.exceptions import UniFiAuthError

        with pytest.raises(UniFiAuthError, match="UNIFI_NETWORK_API_KEY"):
            await dpi_manager_no_key.get_dpi_applications()
        mock_connection._update_cache.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_dpi_applications_uses_cache(self, dpi_manager, mock_connection):
        """Test get_dpi_applications returns cached data."""
        cached = {"data": [{"id": 1, "name": "Cached"}], "totalCount": 1}
        mock_connection.get_cached.return_value = cached

        result = await dpi_manager.get_dpi_applications()

        assert result == cached

    @pytest.mark.asyncio
    @pytest.mark.parametrize("search", ["slack", "SLACK"])
    async def test_get_dpi_applications_search_filters_client_side(self, dpi_manager, search):
        """Search is case-insensitive and applied client-side."""
        api_response = {
            "data": [
                {"id": 1, "name": "Slack"},
                {"id": 2, "name": "Telegram"},
                {"id": 3, "name": "WhatsApp"},
            ],
            "totalCount": 3,
            "offset": 0,
            "limit": 100,
        }

        with patch.object(dpi_manager, "_request_integration_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = api_response

            result = await dpi_manager.get_dpi_applications(search=search)

        assert [app["name"] for app in result["data"]] == ["Slack"]
        assert result.get("filtered_from") == 3

    # ---- get_dpi_categories ----

    @pytest.mark.asyncio
    async def test_get_dpi_categories_no_api_key(self, dpi_manager_no_key, mock_connection):
        """A missing key is an error, not an empty catalog."""
        from unifi_core.exceptions import UniFiAuthError

        with pytest.raises(UniFiAuthError, match="UNIFI_NETWORK_API_KEY"):
            await dpi_manager_no_key.get_dpi_categories()
        mock_connection._update_cache.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_dpi_categories_uses_cache(self, dpi_manager, mock_connection):
        """Test get_dpi_categories returns cached data."""
        cached = {"data": [{"id": 0, "name": "IM"}], "totalCount": 1}
        mock_connection.get_cached.return_value = cached

        result = await dpi_manager.get_dpi_categories()

        assert result == cached

    # ---- _request_integration_api ----

    @pytest.mark.asyncio
    async def test_request_integration_api_builds_correct_url(self, dpi_manager, mock_auth):
        """Test _request_integration_api builds the correct URL."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"data": []})

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_ctx)
        mock_session.close = AsyncMock()

        mock_auth.get_api_key_session.return_value = mock_session

        await dpi_manager._request_integration_api("/v1/dpi/applications")

        mock_session.get.assert_called_once()
        call_args = mock_session.get.call_args
        assert "/proxy/network/integration/v1/dpi/applications" in call_args[0][0]
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status", "error_name", "phrase"),
        [
            (401, "UniFiAuthError", "rejected the configured API key"),
            (403, "UniFiPermissionError", "lacks permission"),
            (404, "UniFiOperationError", "does not serve"),
            (500, "UniFiOperationError", "(HTTP 500)."),
        ],
    )
    async def test_request_integration_api_non_200_raises(self, dpi_manager, mock_auth, status, error_name, phrase):
        """A non-200 answer raises with fixed text instead of reading as an empty catalog."""
        import unifi_core.exceptions as exceptions

        mock_resp = AsyncMock()
        mock_resp.status = status
        mock_resp.text = AsyncMock(return_value="controller-only body 192.0.2.1")

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_ctx)
        mock_session.close = AsyncMock()

        mock_auth.get_api_key_session.return_value = mock_session

        with pytest.raises(getattr(exceptions, error_name)) as excinfo:
            await dpi_manager._request_integration_api("/v1/dpi/applications")

        text = str(excinfo.value)
        assert text.startswith(f"DPI catalog request failed (HTTP {status}).")
        assert phrase in text
        assert "192.0.2.1" not in text and "/proxy/" not in text
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_integration_api_non_object_body_raises(self, dpi_manager, mock_auth):
        from unifi_core.exceptions import UniFiMalformedResponseError

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=["not", "an", "object"])
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_ctx)
        mock_session.close = AsyncMock()
        mock_auth.get_api_key_session.return_value = mock_session

        with pytest.raises(UniFiMalformedResponseError):
            await dpi_manager._request_integration_api("/v1/dpi/applications")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("prefix", "names_variables"),
        [("NETWORK", True), (None, False)],
    )
    async def test_missing_key_message_names_the_setting_only_for_its_reader(
        self, mock_connection, mock_auth_no_key, prefix, names_variables
    ):
        """The MCP server reads UNIFI_* variables; the API server, which shares
        this manager, keeps the key on the controller record."""
        from unifi_core.exceptions import UniFiAuthError
        from unifi_core.network.managers.dpi_manager import DpiManager

        mock_connection.tls_env_prefix = prefix
        manager = DpiManager(mock_connection, mock_auth_no_key)

        with pytest.raises(UniFiAuthError) as excinfo:
            await manager._request_integration_api("/v1/dpi/applications")

        text = str(excinfo.value)
        assert "Network API key" in text and "Settings → Control Plane → Integrations" in text
        assert ("UNIFI_NETWORK_API_KEY (or UNIFI_API_KEY on the UNIFI_HOST console)" in text) is names_variables
        assert "UNIFI_" in text if names_variables else "controller's configuration" in text
        assert "192.0.2.1" not in text
