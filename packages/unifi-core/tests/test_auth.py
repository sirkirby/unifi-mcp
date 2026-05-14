from unittest.mock import AsyncMock

import aiohttp
import pytest
from unifi_core.auth import AuthMethod, UniFiAuth
from unifi_core.exceptions import UniFiAuthError


class TestAuthMethod:
    def test_enum_values(self):
        assert AuthMethod.LOCAL_ONLY.value == "local_only"
        assert AuthMethod.API_KEY_ONLY.value == "api_key_only"
        assert AuthMethod.EITHER.value == "either"

    def test_from_string_valid(self):
        assert AuthMethod.from_string("local_only") == AuthMethod.LOCAL_ONLY
        assert AuthMethod.from_string("api_key_only") == AuthMethod.API_KEY_ONLY
        assert AuthMethod.from_string("either") == AuthMethod.EITHER

    def test_from_string_none_defaults_to_local(self):
        assert AuthMethod.from_string(None) == AuthMethod.LOCAL_ONLY

    def test_from_string_unknown_defaults_to_local(self):
        assert AuthMethod.from_string("unknown") == AuthMethod.LOCAL_ONLY
        assert AuthMethod.from_string("") == AuthMethod.LOCAL_ONLY


class TestUniFiAuthProperties:
    def test_has_api_key_true(self):
        auth = UniFiAuth(api_key="test-key")
        assert auth.has_api_key is True

    def test_has_api_key_false_when_none(self):
        auth = UniFiAuth(api_key=None)
        assert auth.has_api_key is False

    def test_has_api_key_false_when_empty(self):
        auth = UniFiAuth(api_key="")
        assert auth.has_api_key is False

    def test_has_local_true(self):
        provider = AsyncMock()
        auth = UniFiAuth(local_provider=provider)
        assert auth.has_local is True

    def test_has_local_false_when_none(self):
        auth = UniFiAuth()
        assert auth.has_local is False

    def test_set_local_provider(self):
        auth = UniFiAuth()
        assert auth.has_local is False
        provider = AsyncMock()
        auth.set_local_provider(provider)
        assert auth.has_local is True


class TestUniFiAuthApiKeySession:
    @pytest.mark.asyncio
    async def test_get_api_key_session_creates_session_with_header(self):
        auth = UniFiAuth(api_key="my-api-key")
        session = await auth.get_api_key_session()
        try:
            assert isinstance(session, aiohttp.ClientSession)
            # Check that the default headers contain the API key
            assert session.headers.get("X-API-Key") == "my-api-key"
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_get_api_key_session_raises_when_not_configured(self):
        auth = UniFiAuth()
        with pytest.raises(UniFiAuthError, match="API key authentication not configured"):
            await auth.get_api_key_session()


class TestUniFiAuthLocalSession:
    @pytest.mark.asyncio
    async def test_get_local_session_delegates_to_provider(self):
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        provider = AsyncMock()
        provider.get_session = AsyncMock(return_value=mock_session)
        auth = UniFiAuth(local_provider=provider)
        session = await auth.get_local_session()
        assert session is mock_session
        provider.get_session.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_local_session_raises_when_not_configured(self):
        auth = UniFiAuth()
        with pytest.raises(UniFiAuthError, match="Local authentication not configured"):
            await auth.get_local_session()


class TestUniFiAuthGetSession:
    @pytest.mark.asyncio
    async def test_get_session_api_key_only(self):
        auth = UniFiAuth(api_key="test-key")
        session = await auth.get_session(AuthMethod.API_KEY_ONLY)
        try:
            assert session.headers.get("X-API-Key") == "test-key"
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_get_session_local_only(self):
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        provider = AsyncMock()
        provider.get_session = AsyncMock(return_value=mock_session)
        auth = UniFiAuth(local_provider=provider)
        session = await auth.get_session(AuthMethod.LOCAL_ONLY)
        assert session is mock_session

    @pytest.mark.asyncio
    async def test_get_session_either_prefers_api_key(self):
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        provider = AsyncMock()
        provider.get_session = AsyncMock(return_value=mock_session)
        auth = UniFiAuth(api_key="test-key", local_provider=provider)
        session = await auth.get_session(AuthMethod.EITHER)
        try:
            # Should prefer API key when both are available
            assert isinstance(session, aiohttp.ClientSession)
            assert session.headers.get("X-API-Key") == "test-key"
            provider.get_session.assert_not_awaited()
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_get_session_either_falls_back_to_local(self):
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        provider = AsyncMock()
        provider.get_session = AsyncMock(return_value=mock_session)
        auth = UniFiAuth(local_provider=provider)
        session = await auth.get_session(AuthMethod.EITHER)
        assert session is mock_session
        provider.get_session.assert_awaited_once()
