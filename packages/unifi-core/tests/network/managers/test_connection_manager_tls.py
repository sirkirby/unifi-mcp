"""Network ConnectionManager TLS: one setting for every request, including the pre-login probes."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aiounifi.errors import RequestError
from unifi_core.network.managers.connection_manager import (
    ConnectionManager,
    detect_unifi_os_pre_login,
    detect_unifi_os_proactively,
    detect_with_retry,
)
from unifi_core.tls import ssl_setting

FINGERPRINT = "AB" * 32
MODULE = "unifi_core.network.managers.connection_manager"


class _RecordingSession:
    """Answers every GET with ``status`` and records the ``ssl`` each request asked for."""

    def __init__(self, status=200, body=None):
        self.ssl_values = []
        self._status = status
        self._body = body if body is not None else {"data": []}

    def get(self, url, **kwargs):
        self.ssl_values.append(kwargs.get("ssl", "<unset>"))
        response = MagicMock(status=self._status, headers={})
        response.json = AsyncMock(return_value=self._body)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=False)
        return context


PINNED = ssl_setting(True, FINGERPRINT)


def _comparable(setting):
    """aiohttp.Fingerprint has no __eq__; compare pins by digest."""
    return setting.fingerprint if isinstance(setting, aiohttp.Fingerprint) else setting


class TestProbesHonourTheSetting:
    @pytest.mark.parametrize("setting", [True, False, PINNED])
    async def test_pre_login_probe(self, setting):
        session = _RecordingSession()
        assert await detect_unifi_os_pre_login(session, "https://192.0.2.1:443", ssl=setting) is True
        assert session.ssl_values == [setting]

    @pytest.mark.parametrize("setting", [True, False, PINNED])
    async def test_post_login_probes(self, setting):
        session = _RecordingSession()
        await detect_unifi_os_proactively(session, "https://192.0.2.1:443", ssl=setting)
        assert session.ssl_values == [setting, setting]

    @pytest.mark.parametrize("pre_login", [True, False])
    async def test_retry_wrapper_forwards_it(self, pre_login):
        session = _RecordingSession()
        await detect_with_retry(session, "https://192.0.2.1:443", max_retries=1, pre_login=pre_login, ssl=PINNED)
        assert session.ssl_values and all(value is PINNED for value in session.ssl_values)

    async def test_probes_verify_when_not_told_otherwise(self):
        session = _RecordingSession()
        await detect_unifi_os_pre_login(session, "https://192.0.2.1:443")
        await detect_unifi_os_proactively(session, "https://192.0.2.1:443")
        assert session.ssl_values == [True, True, True]

    @pytest.mark.parametrize(
        ("verify_ssl", "fingerprint", "expected"),
        [(True, None, True), (False, None, False), (True, FINGERPRINT, PINNED), (False, FINGERPRINT, PINNED)],
    )
    async def test_initialize_passes_the_manager_setting_to_detection(self, verify_ssl, fingerprint, expected):
        manager = ConnectionManager(
            "192.0.2.1", "admin", "secret", verify_ssl=verify_ssl, ssl_fingerprint=fingerprint, max_retries=1
        )
        controller = MagicMock()
        controller.connectivity = MagicMock(is_unifi_os=False)
        controller.login = AsyncMock(side_effect=RequestError("stop after detection"))
        detect = AsyncMock(return_value=False)
        with (
            patch(f"{MODULE}.Controller", return_value=controller) as controller_cls,
            patch("unifi_core.network.controller_type.resolve_controller_type", return_value="auto"),
            patch(f"{MODULE}.detect_with_retry", detect),
        ):
            assert await manager.initialize() is False
        assert _comparable(detect.await_args.kwargs["ssl"]) == _comparable(expected)
        assert _comparable(controller_cls.call_args.kwargs["config"].ssl_context) == _comparable(expected)
        await manager.cleanup()


class TestManagerSetting:
    def test_defaults_to_verified(self):
        manager = ConnectionManager("192.0.2.1", "admin", "secret")
        assert manager.ssl is True
        assert manager.support_status()["tls_verification_enabled"] is True

    def test_fingerprint_pins_and_counts_as_verified(self):
        manager = ConnectionManager("192.0.2.1", "admin", "secret", verify_ssl=False, ssl_fingerprint=FINGERPRINT)
        assert isinstance(manager.ssl, aiohttp.Fingerprint)
        assert manager.support_status()["tls_verification_enabled"] is True

    def test_malformed_fingerprint_fails_at_construction(self):
        with pytest.raises(ValueError, match="SHA-256"):
            ConnectionManager("192.0.2.1", "admin", "secret", ssl_fingerprint="not-a-fingerprint")

    def test_warns_at_startup_only_when_disabled(self, caplog):
        with caplog.at_level(logging.WARNING, logger="unifi-network-mcp"):
            ConnectionManager("192.0.2.1", "admin", "secret")
            ConnectionManager("192.0.2.1", "admin", "secret", verify_ssl=False, ssl_fingerprint=FINGERPRINT)
            assert not [r for r in caplog.records if "verification is disabled" in r.getMessage()]
            ConnectionManager("192.0.2.1", "admin", "secret", verify_ssl=False)
        assert [r for r in caplog.records if "verification is disabled" in r.getMessage()]

    def test_certificate_failure_gets_fixed_guidance(self):
        manager = ConnectionManager("192.0.2.1", "admin", "secret")
        mismatch = aiohttp.ServerFingerprintMismatch(b"\x00" * 32, b"\x01" * 32, "192.0.2.1", 443)
        try:
            try:
                raise mismatch
            except aiohttp.ClientError:
                raise RequestError("Error requesting data from https://192.0.2.1") from None
        except RequestError as wrapped:
            message = manager._record_connection_error(wrapped)
        assert "UNIFI_NETWORK_SSL_FINGERPRINT" in message
        assert "192.0.2.1" not in message
