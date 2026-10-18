from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import aiohttp
import pytest
from aiohttp import web
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


CONTROLLER_URL = "https://controller.test:443"


@asynccontextmanager
async def _serve(handler):
    """Serve *handler* on a loopback port; each server is its own origin."""
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        await runner.cleanup()


class TestUniFiAuthApiKeySession:
    @pytest.mark.asyncio
    async def test_api_key_is_not_a_session_default_header(self):
        auth = UniFiAuth(api_key="my-api-key")
        session = await auth.get_api_key_session(CONTROLLER_URL)
        try:
            assert isinstance(session, aiohttp.ClientSession)
            # Default headers are re-sent on every redirect hop.
            assert "X-API-Key" not in session.headers
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_api_key_is_sent_to_controller_origin(self):
        async def controller(request):
            return web.json_response({"key": request.headers.get("X-API-Key")})

        async with _serve(controller) as controller_url:
            auth = UniFiAuth(api_key="my-api-key")
            async with await auth.get_api_key_session(controller_url) as session:
                async with session.get(f"{controller_url}/proxy/network/integration/v1/sites") as resp:
                    assert (await resp.json()) == {"key": "my-api-key"}

    @pytest.mark.asyncio
    async def test_cross_origin_redirect_never_reaches_other_host(self):
        received = []

        async def other_host(request):
            received.append(dict(request.headers))
            return web.json_response({})

        async with _serve(other_host) as other_url:

            async def controller(request):
                raise web.HTTPFound(f"{other_url}/collect")

            async with _serve(controller) as controller_url:
                auth = UniFiAuth(api_key="my-api-key")
                async with await auth.get_api_key_session(controller_url) as session:
                    with pytest.raises(UniFiAuthError, match="cannot leave the configured controller"):
                        async with session.get(f"{controller_url}/proxy/network/integration/v1/sites"):
                            pass

        assert received == []

    @pytest.mark.asyncio
    async def test_same_origin_redirect_keeps_api_key(self):
        async def controller(request):
            if request.path == "/old":
                raise web.HTTPFound("/new")
            return web.json_response({"key": request.headers.get("X-API-Key")})

        async with _serve(controller) as controller_url:
            auth = UniFiAuth(api_key="my-api-key")
            async with await auth.get_api_key_session(controller_url) as session:
                async with session.get(f"{controller_url}/old") as resp:
                    assert (await resp.json()) == {"key": "my-api-key"}

    @pytest.mark.asyncio
    async def test_request_to_other_origin_is_refused_before_sending(self):
        received = []

        async def other_host(request):
            received.append(request.path)
            return web.json_response({})

        async with _serve(other_host) as other_url:
            auth = UniFiAuth(api_key="my-api-key")
            async with await auth.get_api_key_session(CONTROLLER_URL) as session:
                with pytest.raises(UniFiAuthError, match="cannot leave the configured controller"):
                    async with session.get(f"{other_url}/collect"):
                        pass

        assert received == []

    @pytest.mark.asyncio
    async def test_caller_middlewares_run_before_key_is_attached(self):
        seen = []

        async def record(request, handler):
            seen.append(request.headers.get("X-API-Key"))
            return await handler(request)

        async def controller(request):
            return web.json_response({"key": request.headers.get("X-API-Key")})

        async with _serve(controller) as controller_url:
            auth = UniFiAuth(api_key="my-api-key")
            async with await auth.get_api_key_session(controller_url, middlewares=(record,)) as session:
                async with session.get(f"{controller_url}/x") as resp:
                    assert (await resp.json()) == {"key": "my-api-key"}

        assert seen == [None]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("controller_url", ["controller.test", "/proxy/network", "ftp://controller.test"])
    async def test_rejects_non_http_controller_url(self, controller_url):
        auth = UniFiAuth(api_key="my-api-key")
        with pytest.raises(UniFiAuthError, match="absolute http"):
            await auth.get_api_key_session(controller_url)

    @pytest.mark.asyncio
    async def test_get_api_key_session_raises_when_not_configured(self):
        auth = UniFiAuth()
        with pytest.raises(UniFiAuthError, match="API key authentication not configured"):
            await auth.get_api_key_session(CONTROLLER_URL)


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
        session = await auth.get_session(AuthMethod.API_KEY_ONLY, CONTROLLER_URL)
        try:
            assert isinstance(session, aiohttp.ClientSession)
            assert "X-API-Key" not in session.headers
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_get_session_api_key_requires_controller_url(self):
        auth = UniFiAuth(api_key="test-key")
        with pytest.raises(UniFiAuthError, match="require the controller URL"):
            await auth.get_session(AuthMethod.API_KEY_ONLY)

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
        session = await auth.get_session(AuthMethod.EITHER, CONTROLLER_URL)
        try:
            # Should prefer API key when both are available
            assert isinstance(session, aiohttp.ClientSession)
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
