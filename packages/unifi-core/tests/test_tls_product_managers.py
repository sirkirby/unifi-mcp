"""Protect and Access connection managers carry the same TLS setting as Network."""

import logging
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

FINGERPRINT = "CD" * 32
API_PIN = "EF" * 32


def _connector_ssl(session: aiohttp.ClientSession):
    return session.connector._ssl


class TestProtect:
    @pytest.fixture
    def manager_cls(self):
        pytest.importorskip("uiprotect")
        from unifi_core.protect.managers.connection_manager import ProtectConnectionManager

        return ProtectConnectionManager

    async def test_off_by_default_and_silent(self, manager_cls, caplog):
        """A library consumer gets no warning naming variables it may not read; the servers warn at startup."""
        with caplog.at_level(logging.WARNING):
            manager = manager_cls("192.0.2.1", "admin", "secret")
        assert manager.ssl is False
        assert manager._client_tls_options() == {"verify_ssl": False}
        assert manager.support_status()["tls_verification_enabled"] is False
        assert caplog.records == []

    @pytest.mark.parametrize(
        "kwargs", [{}, {"verify_ssl": True}, {"ssl_fingerprint": FINGERPRINT}], ids=["off", "verified", "pinned"]
    )
    async def test_client_keeps_the_sdk_retry_limit(self, manager_cls, kwargs):
        """Without it uiprotect retries the login POST on a 429."""
        from unifi_core.protect.managers.connection_manager import SDK_MAX_RETRIES

        manager = manager_cls("192.0.2.1", "admin", "secret", **kwargs)
        client = MagicMock()
        client.update = AsyncMock()
        with patch(
            "unifi_core.protect.managers.connection_manager.ProtectApiClient", return_value=client
        ) as client_cls:
            await manager._connect_once()
        built = client_cls.call_args.kwargs
        try:
            assert built["max_retries"] == SDK_MAX_RETRIES
        finally:
            for name in ("session", "public_api_session"):
                if name in built:
                    await built[name].close()

    async def test_verification_on(self, manager_cls):
        manager = manager_cls("192.0.2.1", "admin", "secret", verify_ssl=True)
        assert manager.ssl is True
        options = manager._client_tls_options()
        try:
            assert options["verify_ssl"] is True
            # Supplied even when not pinned, so their middleware can replace a
            # failed CA check before uiprotect wraps its text in NvrError.
            for name in ("session", "public_api_session"):
                assert _connector_ssl(options[name]) is True
                assert len(options[name]._middlewares) == 1
        finally:
            await options["session"].close()
            await options["public_api_session"].close()
        assert manager.support_status()["tls_verification_enabled"] is True

    async def test_pin_reaches_both_sdk_sessions(self, manager_cls):
        manager = manager_cls("192.0.2.1", "admin", "secret", verify_ssl=False, ssl_fingerprint=FINGERPRINT)
        options = manager._client_tls_options()
        try:
            # verify_ssl=True stops uiprotect adding a per-request ssl=False.
            assert options["verify_ssl"] is True
            for name in ("session", "public_api_session"):
                pin = _connector_ssl(options[name])
                assert isinstance(pin, aiohttp.Fingerprint)
                assert pin.fingerprint == bytes.fromhex(FINGERPRINT)
        finally:
            await options["session"].close()
            await options["public_api_session"].close()
        assert manager.support_status()["tls_verification_enabled"] is True

    async def test_pinned_sessions_close_when_the_client_cannot_be_built(self, manager_cls):
        manager = manager_cls("192.0.2.1", "admin", "secret", ssl_fingerprint=FINGERPRINT)
        built = {}
        original = manager._client_tls_options

        def capture():
            built.update(original())
            return built

        with (
            patch.object(manager, "_client_tls_options", capture),
            patch(
                "unifi_core.protect.managers.connection_manager.ProtectApiClient",
                side_effect=RuntimeError("bad arguments"),
            ),
        ):
            with pytest.raises(RuntimeError):
                await manager._connect_once()
        assert built["session"].closed and built["public_api_session"].closed

    def test_malformed_fingerprint_fails_at_construction(self, manager_cls):
        with pytest.raises(ValueError, match="SHA-256"):
            manager_cls("192.0.2.1", "admin", "secret", ssl_fingerprint="abc")


class TestAccess:
    @pytest.fixture
    def manager_cls(self):
        from unifi_core.access.managers.connection_manager import AccessConnectionManager

        return AccessConnectionManager

    def test_off_by_default_and_silent(self, manager_cls, caplog):
        """A library consumer gets no warning naming variables it may not read; the servers warn at startup."""
        with caplog.at_level(logging.WARNING):
            manager = manager_cls("192.0.2.1", "admin", "secret")
        assert isinstance(manager._ssl_context, ssl.SSLContext)
        assert manager._ssl_context.verify_mode == ssl.CERT_NONE
        assert manager.support_status()["tls_verification_enabled"] is False
        assert caplog.records == []

    def test_verification_on(self, manager_cls):
        manager = manager_cls("192.0.2.1", "admin", "secret", verify_ssl=True)
        assert manager._ssl_context is True
        assert manager.support_status()["tls_verification_enabled"] is True

    def test_pin(self, manager_cls):
        manager = manager_cls("192.0.2.1", "admin", "secret", verify_ssl=False, ssl_fingerprint=FINGERPRINT)
        assert isinstance(manager._ssl_context, aiohttp.Fingerprint)
        assert manager.support_status()["tls_verification_enabled"] is True

    async def test_api_client_path_is_pinned_through_its_session(self, manager_cls):
        pytest.importorskip("unifi_access_api")
        manager = manager_cls("192.0.2.1", "", "", verify_ssl=False, api_key="key", api_ssl_fingerprint=FINGERPRINT)
        client = MagicMock()
        client.authenticate = AsyncMock()
        with patch("unifi_access_api.UnifiAccessApiClient", return_value=client) as client_cls:
            await manager._try_api_client()
        kwargs = client_cls.call_args.kwargs
        try:
            assert kwargs["verify_ssl"] is True
            assert isinstance(_connector_ssl(kwargs["session"]), aiohttp.Fingerprint)
        finally:
            await kwargs["session"].close()

    async def test_each_path_is_pinned_with_its_own_fingerprint(self, manager_cls):
        """The console presents different certificates on 443 and 12445."""
        pytest.importorskip("unifi_access_api")
        manager = manager_cls(
            "192.0.2.1", "admin", "secret", api_key="key", ssl_fingerprint=FINGERPRINT, api_ssl_fingerprint=API_PIN
        )
        client = MagicMock()
        client.authenticate = AsyncMock()
        with (
            patch("unifi_access_api.UnifiAccessApiClient", return_value=client),
            patch.object(manager, "_proxy_login", AsyncMock()),
        ):
            await manager._try_api_client()
            await manager._try_proxy_session()
        try:
            assert _connector_ssl(manager._api_session).fingerprint == bytes.fromhex(API_PIN)
            assert _connector_ssl(manager._proxy_session).fingerprint == bytes.fromhex(FINGERPRINT)
        finally:
            await manager._api_session.close()
            await manager._proxy_session.close()

    async def test_developer_request_sends_the_developer_pin(self, manager_cls):
        """A per-request pin overrides the session's, so the proxy pin here would fail a healthy path."""
        manager = manager_cls(
            "192.0.2.1", "admin", "secret", api_key="key", ssl_fingerprint=FINGERPRINT, api_ssl_fingerprint=API_PIN
        )
        response = MagicMock(status=200)
        response.json = AsyncMock(return_value={"code": "SUCCESS", "data": []})
        response.text = AsyncMock(return_value='{"code": "SUCCESS", "data": []}')
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock(closed=False)
        session.request = MagicMock(return_value=context)
        manager._api_session = session
        manager._api_client = MagicMock()
        manager._api_client_available = True
        manager._initialized = True
        await manager.developer_request("GET", "/visitors", operation="List visitors")
        assert session.request.call_args.kwargs["ssl"].fingerprint == bytes.fromhex(API_PIN)

    def test_malformed_developer_pin_fails_at_construction(self, manager_cls):
        with pytest.raises(ValueError, match="SHA-256"):
            manager_cls("192.0.2.1", "admin", "secret", api_ssl_fingerprint="abc")

    async def test_developer_path_is_refused_beside_a_pinned_proxy_path(self, manager_cls):
        """Falling back to no check would send the token where the operator asked for a pin."""
        pytest.importorskip("unifi_access_api")
        manager = manager_cls(
            "192.0.2.1", "admin", "secret", api_key="key", ssl_fingerprint=FINGERPRINT, tls_env_prefix="ACCESS"
        )
        with patch("unifi_access_api.UnifiAccessApiClient") as client_cls:
            await manager._try_api_client()
        client_cls.assert_not_called()
        assert manager._api_session is None
        assert not manager.has_api_client
        note = manager._certificate_failure_note()
        assert "12445" in note
        assert "UNIFI_ACCESS_API_SSL_FINGERPRINT" in note
        assert manager.support_status()["developer_api_attempt"]["status"] == "failed"

    async def test_proxy_path_is_refused_beside_a_pinned_developer_path(self, manager_cls):
        """Falling back to no check would send the admin password where the operator asked for a pin."""
        manager = manager_cls(
            "192.0.2.1", "admin", "secret", api_key="key", api_ssl_fingerprint=FINGERPRINT, tls_env_prefix="ACCESS"
        )
        login = AsyncMock()
        with patch.object(manager, "_proxy_login", login):
            await manager._try_proxy_session()
        login.assert_not_awaited()
        assert manager._proxy_session is None
        assert not manager.has_proxy
        note = manager._certificate_failure_note()
        assert "443" in note
        assert "UNIFI_ACCESS_SSL_FINGERPRINT" in note

    def test_verification_covers_a_path_with_no_pin(self, manager_cls):
        """Not refused: CA verification is a check, and it fails on its own if the certificate is untrusted."""
        manager = manager_cls("192.0.2.1", "admin", "secret", verify_ssl=True, ssl_fingerprint=FINGERPRINT)
        assert manager._api_ssl_context is True
        assert manager._unpinned_beside_a_pin(manager._api_ssl_context, manager.ssl_fingerprint) is False

    def test_no_pins_leaves_both_paths_as_they_were(self, manager_cls):
        manager = manager_cls("192.0.2.1", "admin", "secret", api_key="key")
        assert manager._ssl_context is manager._api_ssl_context
        assert manager._ssl_context.verify_mode == ssl.CERT_NONE
        assert manager._unpinned_beside_a_pin(manager._api_ssl_context, manager.ssl_fingerprint) is False
        assert manager._unpinned_beside_a_pin(manager._ssl_context, manager.api_ssl_fingerprint) is False

    @pytest.mark.parametrize(
        ("kwargs", "enabled"),
        [
            ({}, False),
            ({"verify_ssl": True}, True),
            ({"ssl_fingerprint": FINGERPRINT}, True),
            ({"api_ssl_fingerprint": FINGERPRINT}, True),
        ],
    )
    def test_support_status_reports_whether_anything_is_checked(self, manager_cls, kwargs, enabled):
        """A path with no check beside a pinned one is refused, so no live path goes unchecked."""
        manager = manager_cls("192.0.2.1", "admin", "secret", **kwargs)
        assert manager.support_status()["tls_verification_enabled"] is enabled

    def test_certificate_failure_is_named_in_the_unreachable_message(self, manager_cls):
        manager = manager_cls("192.0.2.1", "admin", "secret", tls_env_prefix="ACCESS")
        manager._path_failures = [aiohttp.ServerFingerprintMismatch(b"\x00" * 32, b"\x01" * 32, "192.0.2.1", 443)]
        assert "UNIFI_ACCESS_SSL_FINGERPRINT" in manager._unreachable_message()
        manager._path_failures = [aiohttp.ClientConnectionError("refused")]
        assert "FINGERPRINT" not in manager._unreachable_message()

    async def test_certificate_failures_are_logged_without_their_details(self, manager_cls, caplog):
        # A pin mismatch's text names the host, port and both fingerprints;
        # the per-path logs must carry only the exception class.
        pytest.importorskip("unifi_access_api")
        host = "198.51.100.7"
        mismatch = aiohttp.ServerFingerprintMismatch(b"\xaa" * 32, b"\xbb" * 32, host, 8443)
        detail_markers = [host, "8443", "aa" * 32, "bb" * 32, "AA" * 32, "BB" * 32]
        assert any(marker in str(mismatch) for marker in detail_markers)

        manager = manager_cls(
            host,
            "admin",
            "secret",
            api_key="key",
            ssl_fingerprint=FINGERPRINT,
            api_ssl_fingerprint=FINGERPRINT,
            tls_env_prefix="ACCESS",
        )
        client = MagicMock()
        client.authenticate = AsyncMock(side_effect=mismatch)

        async def failing_login():
            raise mismatch

        with caplog.at_level(logging.WARNING):
            with patch("unifi_access_api.UnifiAccessApiClient", return_value=client):
                await manager._try_api_client()
            with patch.object(manager, "_proxy_login", side_effect=failing_login):
                await manager._try_proxy_session()

        path_logs = [r.getMessage() for r in caplog.records if "non-fatal" in r.getMessage()]
        assert len(path_logs) == 2
        for message in path_logs:
            assert "ServerFingerprintMismatch" in message
            for marker in detail_markers:
                assert marker not in message
        assert "UNIFI_ACCESS_SSL_FINGERPRINT" in manager._unreachable_message()
