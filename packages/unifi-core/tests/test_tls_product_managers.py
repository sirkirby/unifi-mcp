"""Protect and Access connection managers carry the same TLS setting as Network."""

import logging
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

FINGERPRINT = "CD" * 32


def _connector_ssl(session: aiohttp.ClientSession):
    return session.connector._ssl


class TestProtect:
    @pytest.fixture
    def manager_cls(self):
        pytest.importorskip("uiprotect")
        from unifi_core.protect.managers.connection_manager import ProtectConnectionManager

        return ProtectConnectionManager

    async def test_defaults_to_verified(self, manager_cls):
        manager = manager_cls("192.0.2.1", "admin", "secret")
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

    def test_disabled_is_passed_through_and_warned(self, manager_cls, caplog):
        with caplog.at_level(logging.WARNING):
            manager = manager_cls("192.0.2.1", "admin", "secret", verify_ssl=False)
        assert manager._client_tls_options() == {"verify_ssl": False}
        assert manager.support_status()["tls_verification_enabled"] is False
        assert any("UNIFI_PROTECT_SSL_FINGERPRINT" in r.getMessage() for r in caplog.records)

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

    def test_defaults_to_verified(self, manager_cls):
        manager = manager_cls("192.0.2.1", "admin", "secret")
        assert manager._ssl_context is True
        assert manager.support_status()["tls_verification_enabled"] is True

    def test_disabled_keeps_the_unverified_context_and_warns(self, manager_cls, caplog):
        with caplog.at_level(logging.WARNING):
            manager = manager_cls("192.0.2.1", "admin", "secret", verify_ssl=False)
        assert isinstance(manager._ssl_context, ssl.SSLContext)
        assert manager._ssl_context.verify_mode == ssl.CERT_NONE
        assert manager.support_status()["tls_verification_enabled"] is False
        assert any("UNIFI_ACCESS_SSL_FINGERPRINT" in r.getMessage() for r in caplog.records)

    def test_pin(self, manager_cls):
        manager = manager_cls("192.0.2.1", "admin", "secret", verify_ssl=False, ssl_fingerprint=FINGERPRINT)
        assert isinstance(manager._ssl_context, aiohttp.Fingerprint)
        assert manager.support_status()["tls_verification_enabled"] is True

    async def test_api_client_path_is_pinned_through_its_session(self, manager_cls):
        pytest.importorskip("unifi_access_api")
        manager = manager_cls("192.0.2.1", "", "", verify_ssl=False, api_key="key", ssl_fingerprint=FINGERPRINT)
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

    def test_certificate_failure_is_named_in_the_unreachable_message(self, manager_cls):
        manager = manager_cls("192.0.2.1", "admin", "secret")
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

        manager = manager_cls(host, "admin", "secret", api_key="key", ssl_fingerprint=FINGERPRINT)
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
