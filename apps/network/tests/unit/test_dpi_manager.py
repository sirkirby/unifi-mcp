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
        conn.host = "192.168.1.1"
        conn.port = 443
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
    async def test_get_dpi_applications_no_api_key(self, dpi_manager_no_key):
        """Test get_dpi_applications returns empty when no API key."""
        result = await dpi_manager_no_key.get_dpi_applications()

        assert result["data"] == []
        assert result["totalCount"] == 0

    @pytest.mark.asyncio
    async def test_get_dpi_applications_uses_cache(self, dpi_manager, mock_connection):
        """Test get_dpi_applications returns cached data."""
        cached = {"data": [{"id": 1, "name": "Cached"}], "totalCount": 1}
        mock_connection.get_cached.return_value = cached

        result = await dpi_manager.get_dpi_applications()

        assert result == cached

    @pytest.mark.asyncio
    async def test_get_dpi_applications_search_filters_client_side(self, dpi_manager, mock_connection):
        """Test search filtering happens client-side."""
        # Mock the integration API response
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

            result = await dpi_manager.get_dpi_applications(search="slack")

        assert len(result["data"]) == 1
        assert result["data"][0]["name"] == "Slack"
        assert result.get("filtered_from") == 3

    @pytest.mark.asyncio
    async def test_get_dpi_applications_search_case_insensitive(self, dpi_manager):
        """Test search is case-insensitive."""
        api_response = {
            "data": [{"id": 1, "name": "Telegram"}],
            "totalCount": 1,
            "offset": 0,
            "limit": 100,
        }

        with patch.object(dpi_manager, "_request_integration_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = api_response

            result = await dpi_manager.get_dpi_applications(search="TELEGRAM")

        assert len(result["data"]) == 1

    # ---- get_dpi_categories ----

    @pytest.mark.asyncio
    async def test_get_dpi_categories_no_api_key(self, dpi_manager_no_key):
        """Test get_dpi_categories returns empty when no API key."""
        result = await dpi_manager_no_key.get_dpi_categories()

        assert result["data"] == []
        assert result["totalCount"] == 0

    @pytest.mark.asyncio
    async def test_get_dpi_categories_uses_cache(self, dpi_manager, mock_connection):
        """Test get_dpi_categories returns cached data."""
        cached = {"data": [{"id": 0, "name": "IM"}], "totalCount": 1}
        mock_connection.get_cached.return_value = cached

        result = await dpi_manager.get_dpi_categories()

        assert result == cached

    # ---- get_full_dpi_catalog ----

    @pytest.mark.asyncio
    async def test_get_full_dpi_catalog_paginates_applications_and_includes_categories(self, dpi_manager):
        async def fake_request(path, params=None):
            if path == "/v1/dpi/categories":
                if params["offset"] == "0":
                    return {
                        "data": [{"id": 3, "name": "File sharing"}, {"id": 4, "name": "Media streaming"}],
                        "totalCount": 3,
                    }
                if params["offset"] == "2":
                    return {"data": [{"id": 5, "name": "Email"}], "totalCount": 3}
            if params["offset"] == "0":
                return {
                    "data": [{"id": 262274, "name": "Spotify"}, {"id": 262334, "name": "Netflix"}],
                    "totalCount": 3,
                }
            if params["offset"] == "2":
                return {"data": [{"id": 262344, "name": "YouTube"}], "totalCount": 3}
            raise AssertionError(f"Unexpected request: {path} {params}")

        with patch.object(dpi_manager, "_request_integration_api", side_effect=fake_request):
            result = await dpi_manager.get_full_dpi_catalog()

        assert result == {
            "applications": [
                {"id": 262274, "name": "Spotify"},
                {"id": 262334, "name": "Netflix"},
                {"id": 262344, "name": "YouTube"},
            ],
            "categories": [
                {"id": 3, "name": "File sharing"},
                {"id": 4, "name": "Media streaming"},
                {"id": 5, "name": "Email"},
            ],
        }

    @pytest.mark.asyncio
    async def test_get_full_dpi_catalog_does_not_cache_partial_pages(self, dpi_manager, mock_connection):
        async def fake_request(path, params=None):
            if path == "/v1/dpi/categories":
                return {"data": [{"id": 4, "name": "Media streaming"}], "totalCount": 1}
            if params["offset"] == "0":
                return {"data": [{"id": 262274, "name": "Spotify"}], "totalCount": 2}
            return None

        with (
            patch.object(dpi_manager, "_request_integration_api", side_effect=fake_request),
            pytest.raises(RuntimeError, match="incomplete DPI application catalogue"),
        ):
            await dpi_manager.get_full_dpi_catalog()

        mock_connection._update_cache.assert_not_called()

    # ---- _request_integration_api ----

    @pytest.mark.asyncio
    async def test_request_integration_api_builds_correct_url(self, dpi_manager, mock_auth, mock_connection):
        """Test _request_integration_api builds the correct URL."""
        mock_connection.verify_ssl = True
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
        assert call_args.kwargs["ssl"] is True
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_integration_api_non_200_returns_none(self, dpi_manager, mock_auth):
        """Test _request_integration_api returns None on non-200 response."""
        mock_resp = AsyncMock()
        mock_resp.status = 401

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_ctx)
        mock_session.close = AsyncMock()

        mock_auth.get_api_key_session.return_value = mock_session

        result = await dpi_manager._request_integration_api("/v1/dpi/applications")

        assert result is None

    @pytest.mark.asyncio
    async def test_request_integration_api_no_key_returns_none(self, dpi_manager_no_key):
        """Test _request_integration_api returns None when no API key configured."""
        result = await dpi_manager_no_key._request_integration_api("/v1/dpi/applications")

        assert result is None
