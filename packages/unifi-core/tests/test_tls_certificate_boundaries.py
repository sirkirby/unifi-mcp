"""A failed certificate check never carries its details out of any controller request path.

``aiohttp.ServerFingerprintMismatch`` names the controller host and port and both
fingerprints, and aiounifi, uiprotect and py-unifi-access each wrap an aiohttp
``ClientError`` in their own exception with the controller URL and that text.
Every controller session therefore carries
:func:`unifi_core.tls.certificate_safe_middleware`, which replaces the failure
below the SDKs. These tests drive the real SDKs and managers over a session whose
connector fails the way a stale pin does, on a TEST-NET address, and check what
reaches the caller and the log.
"""

import logging
import traceback
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from unifi_core.access.managers.connection_manager import AccessUnavailableError
from unifi_core.exceptions import UniFiAuthError
from unifi_core.tls import (
    CertificateVerificationError,
    certificate_failure,
    certificate_safe_middleware,
    safe_error_text,
)

HOST = "198.51.100.7"
PORT = 8443
EXPECTED = b"\xaa" * 32
RECEIVED = b"\xbb" * 32
FINGERPRINT_MARKERS = [
    EXPECTED.hex(),
    RECEIVED.hex(),
    EXPECTED.hex().upper(),
    RECEIVED.hex().upper(),
    repr(EXPECTED),
    repr(RECEIVED),
]
DETAIL_MARKERS = [HOST, str(PORT), *FINGERPRINT_MARKERS]


def _mismatch() -> aiohttp.ServerFingerprintMismatch:
    return aiohttp.ServerFingerprintMismatch(EXPECTED, RECEIVED, HOST, PORT)


class _StalePinConnector(aiohttp.TCPConnector):
    """Fails every connection the way aiohttp does when a pinned certificate changes."""

    async def _create_connection(self, req, traces, timeout):
        raise _mismatch()


def _rendered(caplog) -> str:
    formatter = logging.Formatter("%(message)s")
    return "\n".join(formatter.format(record) for record in caplog.records)


def _assert_absent(text: str, markers: list[str] = DETAIL_MARKERS) -> None:
    for marker in markers:
        assert marker not in text


def _assert_safe(error: BaseException, env_prefix: str) -> None:
    assert isinstance(error, CertificateVerificationError)
    assert "ServerFingerprintMismatch" in str(error)
    assert f"UNIFI_{env_prefix}_SSL_FINGERPRINT" in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    _assert_absent(str(error))


def test_markers_would_catch_the_raw_error():
    assert any(marker in str(_mismatch()) for marker in DETAIL_MARKERS)


class TestMiddleware:
    async def test_replaces_a_failed_check(self):
        async with aiohttp.ClientSession(
            connector=_StalePinConnector(), middlewares=(certificate_safe_middleware(env_prefix="NETWORK"),)
        ) as session:
            with pytest.raises(CertificateVerificationError) as excinfo:
                await session.get(f"https://{HOST}:{PORT}/")
        _assert_safe(excinfo.value, "NETWORK")

    async def test_does_not_carry_the_exception_a_caller_is_handling(self):
        """A caller's fallback runs inside its ``except``; a traceback must not render what that caught."""
        async with aiohttp.ClientSession(
            connector=_StalePinConnector(), middlewares=(certificate_safe_middleware(env_prefix="NETWORK"),)
        ) as session:
            with pytest.raises(CertificateVerificationError) as excinfo:
                try:
                    raise RuntimeError("earlier response details")
                except RuntimeError:
                    await session.get(f"https://{HOST}:{PORT}/")
        assert "earlier response details" not in "".join(traceback.format_exception(excinfo.value))

    async def test_other_failures_pass_through(self):
        class Refused(aiohttp.TCPConnector):
            async def _create_connection(self, req, traces, timeout):
                raise aiohttp.ClientConnectionError("refused")

        async with aiohttp.ClientSession(
            connector=Refused(), middlewares=(certificate_safe_middleware(env_prefix="NETWORK"),)
        ) as session:
            with pytest.raises(aiohttp.ClientConnectionError, match="refused"):
                await session.get(f"https://{HOST}:{PORT}/")

    def test_safe_error_text_leaves_other_errors_alone(self):
        error = RuntimeError("boom")
        assert safe_error_text(error, env_prefix="NETWORK") is error
        _assert_absent(str(safe_error_text(_mismatch(), env_prefix="NETWORK")))


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


@pytest.fixture
def network_manager():
    from unifi_core.network.managers.connection_manager import ConnectionManager

    return ConnectionManager(
        HOST, "admin", "secret", port=PORT, ssl_fingerprint=EXPECTED.hex(), tls_env_prefix="NETWORK"
    )


class TestNetworkDetection:
    """The detection probes are public and may be handed a session without the middleware."""

    async def test_pre_login_probe_logs_fixed_text(self, caplog):
        from unifi_core.network.managers.connection_manager import detect_unifi_os_pre_login

        async with aiohttp.ClientSession(connector=_StalePinConnector()) as session:
            with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
                assert await detect_unifi_os_pre_login(session, "https://unifi.test", ssl=True) is None
        assert "ServerFingerprintMismatch" in _rendered(caplog)
        _assert_absent(_rendered(caplog))

    async def test_post_login_probe_logs_fixed_text(self, caplog):
        from unifi_core.network.managers.connection_manager import detect_unifi_os_proactively

        async with aiohttp.ClientSession(connector=_StalePinConnector()) as session:
            with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
                assert await detect_unifi_os_proactively(session, "https://unifi.test", ssl=True) is None
        assert "ServerFingerprintMismatch" in _rendered(caplog)
        _assert_absent(_rendered(caplog))

    async def test_retry_wrapper_logs_fixed_text(self, caplog):
        from unifi_core.network.managers.connection_manager import detect_with_retry

        async with aiohttp.ClientSession(connector=_StalePinConnector()) as session:
            with (
                patch("unifi_core.network.managers.connection_manager.asyncio.sleep", AsyncMock()),
                caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"),
            ):
                await detect_with_retry(session, "https://unifi.test", max_retries=2, pre_login=True, ssl=True)
        _assert_absent(_rendered(caplog))

    async def test_exported_pre_login_helper_logs_fixed_text(self, caplog):
        from unifi_core import detect_controller_type_pre_login

        with (
            patch("aiohttp.client.TCPConnector", _StalePinConnector),
            caplog.at_level(logging.DEBUG, logger="unifi_core.detection"),
        ):
            assert await detect_controller_type_pre_login(HOST, PORT, ssl_fingerprint=EXPECTED.hex()) is None
        assert "ServerFingerprintMismatch" in _rendered(caplog)
        assert "UNIFI_" not in _rendered(caplog)
        _assert_absent(_rendered(caplog))


class TestNetworkRequests:
    async def test_manager_session_replaces_the_failure(self, network_manager):
        with patch("aiohttp.TCPConnector", _StalePinConnector):
            session = network_manager._new_session()
        try:
            with pytest.raises(CertificateVerificationError) as excinfo:
                await session.get(f"https://{HOST}:{PORT}/api/self/sites")
        finally:
            await session.close()
        _assert_safe(excinfo.value, "NETWORK")

    async def test_ordinary_request_raises_fixed_text_through_aiounifi(self, network_manager, caplog):
        from aiounifi.controller import Controller
        from aiounifi.models.api import ApiRequest
        from aiounifi.models.configuration import Configuration

        with patch("aiohttp.TCPConnector", _StalePinConnector):
            session = network_manager._new_session()
        network_manager.controller = Controller(
            Configuration(
                session, HOST, username="admin", password="secret", port=PORT, ssl_context=network_manager.ssl
            )
        )
        network_manager.ensure_connected = AsyncMock(return_value=True)
        try:
            with caplog.at_level(logging.DEBUG):
                with pytest.raises(CertificateVerificationError) as excinfo:
                    await network_manager.request(ApiRequest(method="get", path="/stat/sta"))
        finally:
            await session.close()
        # Not aiounifi's RequestError("Error requesting data from <url>: <mismatch>").
        _assert_safe(excinfo.value, "NETWORK")
        _assert_absent(_rendered(caplog))

    async def test_initialize_records_fixed_text(self, network_manager, caplog):
        with (
            patch("aiohttp.TCPConnector", _StalePinConnector),
            patch("unifi_core.network.managers.connection_manager.asyncio.sleep", AsyncMock()),
            caplog.at_level(logging.DEBUG),
        ):
            network_manager._max_retries = 1
            try:
                assert await network_manager.initialize() is False
                error = network_manager.last_connection_error
            finally:
                await network_manager.cleanup()
        assert "UNIFI_NETWORK_SSL_FINGERPRINT" in str(error)
        _assert_absent(str(error))
        # The connect-progress lines name the configured host by design; the
        # failure itself must add nothing from the certificate check.
        _assert_absent(_rendered(caplog), FINGERPRINT_MARKERS)
        assert "ServerFingerprintMismatch" in _rendered(caplog)

    @pytest.mark.parametrize("controller_type", ["proxy", "auto"])
    async def test_key_only_initialize_records_fixed_text(self, monkeypatch, caplog, controller_type):
        from unifi_core.auth import UniFiAuth
        from unifi_core.network.managers.connection_manager import ConnectionManager

        monkeypatch.setenv("UNIFI_CONTROLLER_TYPE", controller_type)
        manager = ConnectionManager(
            HOST,
            "",
            "",
            port=PORT,
            ssl_fingerprint=EXPECTED.hex(),
            auth=UniFiAuth(api_key="synthetic-key"),
            tls_env_prefix="NETWORK",
        )
        with patch("aiohttp.client.TCPConnector", _StalePinConnector), caplog.at_level(logging.DEBUG):
            try:
                assert await manager.initialize() is False
                error = manager.last_connection_error
            finally:
                await manager.cleanup()
        assert "UNIFI_NETWORK_SSL_FINGERPRINT" in str(error)
        _assert_absent(str(error))
        assert "UNIFI_NETWORK_SSL_FINGERPRINT" in _rendered(caplog)
        _assert_absent(_rendered(caplog))

    async def test_integration_request_raises_fixed_text(self, caplog):
        from unifi_core.auth import UniFiAuth
        from unifi_core.network.managers.connection_manager import ConnectionManager

        manager = ConnectionManager(
            HOST,
            "",
            "",
            port=PORT,
            ssl_fingerprint=EXPECTED.hex(),
            auth=UniFiAuth(api_key="synthetic-key"),
            tls_env_prefix="NETWORK",
        )
        with patch("aiohttp.client.TCPConnector", _StalePinConnector), caplog.at_level(logging.DEBUG):
            with pytest.raises(CertificateVerificationError) as excinfo:
                await manager.request_integration("/v1/sites")
        _assert_safe(excinfo.value, "NETWORK")
        _assert_absent(_rendered(caplog))


class TestNetworkWrappersKeepTheRemediation:
    """Wrappers that hide unsafe failures must let this one through: its text is fixed and tells the user what to do."""

    async def test_public_inventory(self, caplog):
        from unifi_core.auth import UniFiAuth
        from unifi_core.network.managers.connection_manager import ConnectionManager

        manager = ConnectionManager(
            HOST,
            "",
            "",
            port=PORT,
            ssl_fingerprint=EXPECTED.hex(),
            auth=UniFiAuth(api_key="synthetic-key"),
            tls_env_prefix="NETWORK",
        )
        with patch("aiohttp.client.TCPConnector", _StalePinConnector), caplog.at_level(logging.DEBUG):
            with pytest.raises(CertificateVerificationError) as excinfo:
                await manager.public_inventory("devices")
        _assert_safe(excinfo.value, "NETWORK")
        _assert_absent(_rendered(caplog))

    async def test_collection_refresh(self, network_manager):
        network_manager._refresh_handler_with_reauthentication = AsyncMock(
            side_effect=certificate_failure(_mismatch(), env_prefix="NETWORK")
        )
        with pytest.raises(CertificateVerificationError) as excinfo:
            await network_manager.refresh_handler("clients")
        assert "UNIFI_NETWORK_SSL_FINGERPRINT" in str(excinfo.value)
        _assert_absent(str(excinfo.value))

    async def test_settings_request(self, network_manager):
        from aiounifi.models.api import ApiRequest

        network_manager._request_with_reauthentication = AsyncMock(
            side_effect=certificate_failure(_mismatch(), env_prefix="NETWORK")
        )
        with pytest.raises(CertificateVerificationError) as excinfo:
            await network_manager.request(ApiRequest(method="get", path="/get/setting/mgmt"))
        assert "UNIFI_NETWORK_SSL_FINGERPRINT" in str(excinfo.value)
        _assert_absent(str(excinfo.value))

    async def test_other_refresh_failures_stay_hidden(self, network_manager):
        from aiounifi.errors import RequestError

        network_manager._refresh_handler_with_reauthentication = AsyncMock(side_effect=RuntimeError(f"secret {HOST}"))
        with pytest.raises(RequestError) as excinfo:
            await network_manager.refresh_handler("clients")
        assert HOST not in str(excinfo.value)


class TestConsumerWithoutTheVariables:
    """The API server builds these managers from its own ``verify_tls`` and reads no ``UNIFI_*`` setting."""

    async def test_network_error_names_no_variables(self):
        from unifi_core.network.managers.connection_manager import ConnectionManager

        manager = ConnectionManager(HOST, "admin", "secret", port=PORT, verify_ssl=True)
        with patch("aiohttp.TCPConnector", _StalePinConnector):
            session = manager._new_session()
        try:
            with pytest.raises(CertificateVerificationError) as excinfo:
                await session.get(f"https://{HOST}:{PORT}/")
        finally:
            await session.close()
        assert "UNIFI_" not in str(excinfo.value)
        _assert_absent(str(excinfo.value))

    def test_access_message_names_no_variables(self):
        from unifi_core.access.managers.connection_manager import AccessConnectionManager

        manager = AccessConnectionManager(HOST, "admin", "secret", port=PORT, verify_ssl=True)
        manager._path_failures = [_mismatch()]
        assert "UNIFI_" not in manager._unreachable_message()

    async def test_protect_session_names_no_variables(self):
        pytest.importorskip("uiprotect")
        from unifi_core.protect.managers.connection_manager import ProtectConnectionManager

        manager = ProtectConnectionManager(HOST, "admin", "secret", port=PORT, verify_ssl=True)
        with patch("aiohttp.TCPConnector", _StalePinConnector):
            options = manager._client_tls_options()
        try:
            with pytest.raises(CertificateVerificationError) as excinfo:
                await options["session"].get(f"https://{HOST}:{PORT}/")
        finally:
            await options["session"].close()
            await options["public_api_session"].close()
        assert "UNIFI_" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------


@pytest.fixture
def access_manager():
    from unifi_core.access.managers.connection_manager import AccessConnectionManager

    return AccessConnectionManager(
        HOST,
        "admin",
        "secret",
        port=PORT,
        api_key="key",
        ssl_fingerprint=EXPECTED.hex(),
        api_ssl_fingerprint=EXPECTED.hex(),
        tls_env_prefix="ACCESS",
    )


def _access_session(manager) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(connector=_StalePinConnector(), middlewares=manager._session_middlewares())


class TestAccessRequests:
    async def test_proxy_request_raises_fixed_text(self, access_manager, caplog):
        access_manager._proxy_session = _access_session(access_manager)
        access_manager._proxy_available = True
        try:
            with caplog.at_level(logging.DEBUG):
                with pytest.raises(CertificateVerificationError) as excinfo:
                    await access_manager.proxy_request("GET", "credentials")
        finally:
            await access_manager._proxy_session.close()
        _assert_safe(excinfo.value, "ACCESS")
        _assert_absent(_rendered(caplog))

    async def test_developer_request_raises_fixed_text(self, access_manager, caplog):
        access_manager._api_session = _access_session(access_manager)
        access_manager._api_client = MagicMock()
        access_manager._api_client_available = True
        try:
            with caplog.at_level(logging.DEBUG):
                with pytest.raises(CertificateVerificationError) as excinfo:
                    await access_manager.developer_request(
                        "GET", "/api/v1/developer/visitors", operation="List visitors"
                    )
        finally:
            await access_manager._api_session.close()
        _assert_safe(excinfo.value, "ACCESS")
        _assert_absent(_rendered(caplog))

    async def test_sdk_client_raises_fixed_text(self, access_manager):
        from unifi_access_api import UnifiAccessApiClient

        session = _access_session(access_manager)
        client = UnifiAccessApiClient(host=f"https://{HOST}:{PORT}", api_token="key", session=session, verify_ssl=True)
        try:
            with pytest.raises(CertificateVerificationError) as excinfo:
                await client.get_doors()
        finally:
            await session.close()
        # Not py-unifi-access's ApiSSLError(str(mismatch)).
        _assert_safe(excinfo.value, "ACCESS")

    @staticmethod
    async def _connect(manager, *, developer=None, proxy=None):
        """Initialize with each path's login outcome, so one path can fail while the other connects."""
        client = MagicMock()
        client.authenticate = AsyncMock(side_effect=developer)
        with (
            patch("unifi_access_api.UnifiAccessApiClient", return_value=client),
            patch.object(manager, "_proxy_login", AsyncMock(side_effect=proxy)),
        ):
            assert await manager.initialize() is True

    async def test_developer_path_failure_does_not_blame_the_token(self, access_manager, caplog):
        with caplog.at_level(logging.WARNING):
            await self._connect(access_manager, developer=certificate_failure(_mismatch(), env_prefix="ACCESS"))
        try:
            with pytest.raises(CertificateVerificationError) as excinfo:
                await access_manager.developer_request("GET", "/visitors", operation="List visitors")
            message = str(excinfo.value)
            assert "SSL_FINGERPRINT" in message
            assert "12445" in message
            assert "API token" not in message
            assert "12445" in _rendered(caplog)
            _assert_absent(message, FINGERPRINT_MARKERS)
        finally:
            await access_manager.close()

    async def test_visitor_tool_route_does_not_blame_the_token(self, access_manager):
        """Visitors are the main users of the developer path, and reach it through their own manager."""
        from unifi_core.access.managers.visitor_manager import VisitorManager

        await self._connect(access_manager, developer=certificate_failure(_mismatch(), env_prefix="ACCESS"))
        try:
            with pytest.raises(CertificateVerificationError) as excinfo:
                await VisitorManager(access_manager).list_visitors()
            message = str(excinfo.value)
            assert "SSL_FINGERPRINT" in message
            assert "12445" in message
            assert "API token" not in message
        finally:
            await access_manager.close()

    async def test_proxy_path_failure_is_named(self, access_manager):
        await self._connect(access_manager, proxy=certificate_failure(_mismatch(), env_prefix="ACCESS"))
        try:
            with pytest.raises(AccessUnavailableError) as excinfo:
                await access_manager.proxy_request("GET", "credentials")
            message = str(excinfo.value)
            assert "UNIFI_ACCESS_SSL_FINGERPRINT" in message
            assert str(PORT) in message
            _assert_absent(message, FINGERPRINT_MARKERS)
        finally:
            await access_manager.close()

    async def test_a_rejected_login_does_not_hide_the_other_paths_certificate(self, access_manager):
        failure = certificate_failure(_mismatch(), env_prefix="ACCESS", pin_variable="UNIFI_ACCESS_API_SSL_FINGERPRINT")
        access_manager._path_failures = [failure]
        access_manager._api_certificate_failure = str(failure)
        message = access_manager._rejected_message()
        assert "12445" in message
        assert "UNIFI_ACCESS_API_SSL_FINGERPRINT" in message
        _assert_absent(message, FINGERPRINT_MARKERS)

    async def test_a_rejected_token_still_gets_the_token_advice(self, access_manager):
        await self._connect(access_manager, developer=RuntimeError("rejected"))
        try:
            with pytest.raises(UniFiAuthError, match="API token"):
                await access_manager.developer_request("GET", "/visitors", operation="List visitors")
        finally:
            await access_manager.close()

    async def test_a_later_clean_attempt_forgets_the_failure(self, access_manager):
        await self._connect(access_manager, proxy=certificate_failure(_mismatch(), env_prefix="ACCESS"))
        assert "FINGERPRINT" in str(access_manager.unavailable_error("Proxy session is not available"))
        client = MagicMock()
        client.authenticate = AsyncMock()
        with (
            patch("unifi_access_api.UnifiAccessApiClient", return_value=client),
            patch.object(access_manager, "_proxy_login", AsyncMock(side_effect=RuntimeError("rejected"))),
        ):
            await access_manager._connect_once()
        try:
            assert "FINGERPRINT" not in str(access_manager.unavailable_error("Proxy session is not available"))
        finally:
            await access_manager.close()

    async def test_both_sessions_carry_the_middleware(self, access_manager):
        with patch("aiohttp.TCPConnector", _StalePinConnector), patch("unifi_access_api.UnifiAccessApiClient") as cls:
            cls.return_value.authenticate = AsyncMock()
            access_manager._proxy_login = AsyncMock()
            await access_manager._try_api_client()
            await access_manager._try_proxy_session()
        try:
            with pytest.raises(CertificateVerificationError) as developer:
                await access_manager._api_session.get(f"https://{HOST}:{PORT}/")
            with pytest.raises(CertificateVerificationError) as proxy:
                await access_manager._proxy_session.get(f"https://{HOST}:{PORT}/")
            # Each path's error names the variable that pins that path.
            assert "UNIFI_ACCESS_API_SSL_FINGERPRINT" in str(developer.value)
            assert "UNIFI_ACCESS_SSL_FINGERPRINT" in str(proxy.value)
        finally:
            await access_manager._api_session.close()
            await access_manager._proxy_session.close()


# ---------------------------------------------------------------------------
# Protect
# ---------------------------------------------------------------------------


@pytest.fixture
def protect_client_factory():
    pytest.importorskip("uiprotect")
    from uiprotect import ProtectApiClient
    from unifi_core.protect.managers.connection_manager import ProtectConnectionManager

    def build(**manager_kwargs):
        """The client ``_connect_once`` would build; the caller closes its sessions."""
        manager = ProtectConnectionManager(
            HOST, "admin", "secret", port=PORT, api_key="key", tls_env_prefix="PROTECT", **manager_kwargs
        )
        with patch("aiohttp.TCPConnector", _StalePinConnector):
            options = manager._client_tls_options()
        return manager, ProtectApiClient(HOST, PORT, "admin", "secret", api_key="key", **options)

    return build


class TestProtectRequests:
    @pytest.mark.parametrize(
        "kwargs", [{"ssl_fingerprint": EXPECTED.hex()}, {"verify_ssl": True}], ids=["pinned", "verified"]
    )
    async def test_private_api_request_raises_fixed_text(self, protect_client_factory, kwargs, caplog):
        _, client = protect_client_factory(**kwargs)
        try:
            with caplog.at_level(logging.DEBUG):
                with pytest.raises(CertificateVerificationError) as excinfo:
                    await client.api_request("nvr")
        finally:
            await client.close_session()
            await client.close_public_api_session()
        # Not uiprotect's NvrError("Error requesting data from <host>: <mismatch>").
        _assert_safe(excinfo.value, "PROTECT")
        # uiprotect's own debug log names the request URL; nothing from the
        # failed check may follow it.
        _assert_absent(_rendered(caplog), FINGERPRINT_MARKERS)

    async def test_public_api_request_raises_fixed_text(self, protect_client_factory):
        _, client = protect_client_factory(ssl_fingerprint=EXPECTED.hex())
        try:
            with pytest.raises(CertificateVerificationError) as excinfo:
                await client.api_request("v1/meta/info", public_api=True)
        finally:
            await client.close_session()
            await client.close_public_api_session()
        _assert_safe(excinfo.value, "PROTECT")

    async def test_later_tool_calls_get_the_remediation(self):
        """A tool call finds no client after the failed connect, and only its error reaches the user."""
        pytest.importorskip("uiprotect")
        from unifi_core.exceptions import UniFiConnectionError
        from unifi_core.protect.managers.connection_manager import ProtectConnectionManager

        manager = ProtectConnectionManager(
            HOST, "admin", "secret", port=PORT, ssl_fingerprint=EXPECTED.hex(), tls_env_prefix="PROTECT"
        )
        with patch("aiohttp.TCPConnector", _StalePinConnector), patch("asyncio.sleep", AsyncMock()):
            await manager.initialize()
        with pytest.raises(UniFiConnectionError) as excinfo:
            _ = manager.client
        assert "UNIFI_PROTECT_SSL_FINGERPRINT" in str(excinfo.value)
        assert "reachable" not in str(excinfo.value)
        _assert_absent(str(excinfo.value), FINGERPRINT_MARKERS)

    def test_other_failures_keep_the_reachability_advice(self):
        pytest.importorskip("uiprotect")
        from unifi_core.protect.managers.connection_manager import ProtectConnectionManager

        manager = ProtectConnectionManager(HOST, "admin", "secret", port=PORT, tls_env_prefix="PROTECT")
        manager._connection_failed(aiohttp.ClientConnectionError("refused"))
        message = manager._not_connected_message()
        assert "reachable" in message
        assert "FINGERPRINT" not in message
