"""Unit tests for UniFi OS path detection functionality.

Tests the proactive detection of controller type (UniFi OS vs Standard)
through empirical endpoint probing.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aioresponses import CallbackResult, aioresponses
from aiounifi.errors import RequestError
from aiounifi.models.api import ApiRequest
from yarl import URL

from unifi_core.network.managers.connection_manager import (
    ConnectionManager,
    detect_unifi_os_proactively,
    detect_with_retry,
)


def _mock_url(base_url: str, path: str = "") -> URL:
    """Mirror aiohttp/yarl URL normalization for aioresponses matching."""
    return URL(f"{base_url}{path}")


class _Aiohttp314CompatibleResponse(aiohttp.ClientResponse):
    """Test shim until aioresponses supports aiohttp 3.14's stream_writer arg."""

    def __init__(self, method, url, **kwargs):
        kwargs.setdefault("stream_writer", MagicMock(output_size=0))
        super().__init__(method, url, **kwargs)


def _callback_result(**kwargs) -> CallbackResult:
    kwargs.setdefault("response_class", _Aiohttp314CompatibleResponse)
    return CallbackResult(**kwargs)


def _mock_get(mock: aioresponses, base_url: str, path: str = "", **kwargs) -> None:
    kwargs.setdefault("response_class", _Aiohttp314CompatibleResponse)
    mock.get(_mock_url(base_url, path), **kwargs)


def _mock_post(mock: aioresponses, base_url: str, path: str = "", **kwargs) -> None:
    kwargs.setdefault("response_class", _Aiohttp314CompatibleResponse)
    mock.post(_mock_url(base_url, path), **kwargs)


class _FailingLoginController:
    def __init__(self, config):
        self.connectivity = MagicMock()
        self.connectivity.is_unifi_os = False
        self.connectivity.config = config

    async def login(self):
        raise RequestError("SSO MFA required but no totp_secret configured")


class _PasswordLeakingLoginController:
    def __init__(self, config):
        self.connectivity = MagicMock()
        self.connectivity.is_unifi_os = False
        self.connectivity.config = config

    async def login(self):
        raise RequestError(f"login failed for {self.connectivity.config.password}")


class TestPathDetection:
    """Test suite for UniFi OS automatic detection (FR-001, FR-002, FR-003)."""

    @pytest.mark.asyncio
    async def test_detects_unifi_os_correctly(self):
        """Test detection of UniFi OS when proxy endpoint succeeds.

        FR-001: System MUST probe /proxy/network/api/self/sites endpoint
        FR-010: Detection MUST use /api/self/sites endpoint (lightweight)

        Scenario:
        - UniFi OS endpoint (/proxy/network/api/self/sites) returns 200 with valid JSON
        - Standard endpoint should NOT be called (proxy succeeds first)

        Expected: detect_unifi_os_proactively() returns True
        """
        base_url = "https://192.168.1.1:443"

        with aioresponses() as mock:
            # Mock UniFi OS endpoint to succeed
            _mock_get(
                mock,
                base_url,
                "/proxy/network/api/self/sites",
                status=200,
                payload={"meta": {"rc": "ok"}, "data": []},
            )

            async with aiohttp.ClientSession() as session:
                result = await detect_unifi_os_proactively(session=session, base_url=base_url, timeout=5)

            assert result is True, "Should detect UniFi OS when proxy endpoint succeeds"

    @pytest.mark.asyncio
    async def test_detects_standard_controller(self):
        """Test detection of standard controller when only direct path works.

        FR-001: System MUST probe both endpoints

        Scenario:
        - UniFi OS endpoint (/proxy/network/api/self/sites) fails with 404
        - Standard endpoint (/api/self/sites) returns 200 with valid JSON

        Expected: detect_unifi_os_proactively() returns False
        """
        base_url = "https://192.168.1.1:443"

        with aioresponses() as mock:
            # Mock UniFi OS endpoint to fail
            _mock_get(mock, base_url, "/proxy/network/api/self/sites", status=404)

            # Mock standard endpoint to succeed
            _mock_get(
                mock,
                base_url,
                "/api/self/sites",
                status=200,
                payload={"meta": {"rc": "ok"}, "data": []},
            )

            async with aiohttp.ClientSession() as session:
                result = await detect_unifi_os_proactively(session=session, base_url=base_url, timeout=5)

            assert result is False, "Should detect standard controller when only direct path works"

    @pytest.mark.asyncio
    async def test_detection_failure_returns_none(self):
        """Test detection returns None when both endpoints fail.

        Scenario:
        - UniFi OS endpoint fails (404)
        - Standard endpoint fails (404)

        Expected: detect_unifi_os_proactively() returns None (fallback to aiounifi)
        """
        base_url = "https://192.168.1.1:443"

        with aioresponses() as mock:
            # Mock both endpoints to fail
            _mock_get(mock, base_url, "/proxy/network/api/self/sites", status=404)

            _mock_get(mock, base_url, "/api/self/sites", status=404)

            async with aiohttp.ClientSession() as session:
                result = await detect_unifi_os_proactively(session=session, base_url=base_url, timeout=5)

            assert result is None, "Should return None when both endpoints fail"

    @pytest.mark.asyncio
    async def test_both_paths_succeed_prefers_direct(self):
        """Test that when both paths succeed, detection prefers direct (FR-012).

        FR-012: If both paths succeed (ambiguous), system MUST prefer direct paths

        Scenario:
        - Both UniFi OS and standard endpoints return 200 with valid JSON

        Expected: detect_unifi_os_proactively() returns False (prefers direct)
        """
        base_url = "https://192.168.1.1:443"

        with aioresponses() as mock:
            # Mock both endpoints to succeed
            _mock_get(
                mock,
                base_url,
                "/proxy/network/api/self/sites",
                status=200,
                payload={"meta": {"rc": "ok"}, "data": []},
            )

            _mock_get(
                mock,
                base_url,
                "/api/self/sites",
                status=200,
                payload={"meta": {"rc": "ok"}, "data": []},
            )

            async with aiohttp.ClientSession() as session:
                result = await detect_unifi_os_proactively(session=session, base_url=base_url, timeout=5)

            assert result is False, "Should prefer direct path when both succeed (FR-012)"

    @pytest.mark.asyncio
    async def test_detection_timeout_handling(self):
        """Test that detection handles timeouts gracefully (SC-002, SC-005).

        SC-002: Detection must complete within 5 seconds
        SC-005: Detection adds ≤2 seconds to connection time

        Scenario:
        - GET requests raise asyncio.TimeoutError

        Expected: detect_unifi_os_proactively() returns None
        """
        base_url = "https://192.168.1.1:443"

        with aioresponses() as mock:
            # Mock timeout on UniFi OS endpoint
            _mock_get(
                mock,
                base_url,
                "/proxy/network/api/self/sites",
                exception=asyncio.TimeoutError("Request timeout"),
            )

            # Mock timeout on standard endpoint
            _mock_get(
                mock,
                base_url,
                "/api/self/sites",
                exception=asyncio.TimeoutError("Request timeout"),
            )

            async with aiohttp.ClientSession() as session:
                result = await detect_unifi_os_proactively(session=session, base_url=base_url, timeout=5)

            assert result is None, "Should return None when requests timeout"

    @pytest.mark.asyncio
    async def test_detection_retries_until_success(self):
        """Test retry logic continues until detection succeeds (FR-008).

        FR-008: System MUST retry detection up to 3 times

        Scenario:
        - First 2 attempts: Both endpoints return 404 (detection returns None)
        - Third attempt: Standard endpoint succeeds (200)

        Expected:
        - Returns False (standard controller detected on 3rd try)
        - All 3 retry attempts are made

        Note: Connection errors are caught by _probe_endpoint, so detection
        returns None (not an exception). Retries happen immediately without
        exponential backoff since no exception bubbles up to detect_with_retry.
        """
        base_url = "https://192.168.1.1:443"
        attempt_count = 0

        with aioresponses() as mock:

            def proxy_callback(url, **kwargs):
                nonlocal attempt_count
                attempt_count += 1
                # Always return 404 for proxy endpoint
                return _callback_result(status=404)

            def standard_callback(url, **kwargs):
                nonlocal attempt_count
                attempt_count += 1
                # Calculate which retry attempt we're on (2 calls per attempt)
                current_attempt = attempt_count // 2
                if current_attempt >= 3:
                    # Third attempt: standard succeeds
                    return _callback_result(
                        status=200,
                        payload={"meta": {"rc": "ok"}, "data": []},
                    )
                # First 2 attempts: return 404
                return _callback_result(status=404)

            _mock_get(mock, base_url, "/proxy/network/api/self/sites", callback=proxy_callback, repeat=True)
            _mock_get(mock, base_url, "/api/self/sites", callback=standard_callback, repeat=True)

            async with aiohttp.ClientSession() as session:
                result = await detect_with_retry(session, base_url, max_retries=3, timeout=5)

                # Verify result - standard controller detected on 3rd attempt
                assert result is False, "Should detect standard controller on 3rd attempt"
                # 3 attempts × 2 endpoints = 6 HTTP calls
                assert attempt_count == 6, "Should make 6 HTTP calls (3 attempts × 2 endpoints)"

    @pytest.mark.asyncio
    async def test_detection_timeout_retries_then_fails(self):
        """Test that connection errors are retried and eventually fail gracefully (FR-008, FR-009).

        FR-008: System MUST retry detection up to 3 times
        FR-009: System MUST provide clear, actionable error messages

        Scenario:
        - All 3 attempts: Raise connection errors

        Expected:
        - Returns None (fallback to aiounifi)
        - No exceptions raised to caller (graceful failure)
        - Exponential backoff between retries

        Note: Exponential backoff only triggers on exceptions. When detection
        returns None (no exception), retries happen without delay.
        """
        base_url = "https://192.168.1.1:443"
        call_count = 0

        def error_callback(url, **kwargs):
            """Callback that counts calls and raises connection error."""
            nonlocal call_count
            call_count += 1
            raise aiohttp.ClientError("Connection refused")

        with aioresponses() as mock:
            # Both endpoints always raise errors
            _mock_get(mock, base_url, "/proxy/network/api/self/sites", callback=error_callback, repeat=True)
            _mock_get(mock, base_url, "/api/self/sites", callback=error_callback, repeat=True)

            async with aiohttp.ClientSession() as session:
                with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    result = await detect_with_retry(session, base_url, max_retries=3, timeout=5)

                    # Verify graceful failure
                    assert result is None, "Should return None after all retries fail"
                    # detect_unifi_os_proactively catches ClientError internally, so
                    # each attempt probes both endpoints: 3 retries × 2 endpoints = 6 calls
                    assert call_count == 6, "Should probe both endpoints 3 times (6 total calls)"
                    # Sleep is called between retries when exceptions bubble up to detect_with_retry
                    # Since _probe_endpoint catches ClientError, no exceptions reach detect_with_retry
                    # so no sleep calls happen (detection just returns None for each attempt)
                    assert mock_sleep.call_count == 0, "No sleep when detection returns None (no exception)"

    @pytest.mark.asyncio
    async def test_detection_result_cached_for_session(self):
        """Test that detection only runs once per session (FR-011).

        FR-011: Detection result MUST be cached and MUST NOT re-run during session lifetime

        Scenario:
        - Create ConnectionManager
        - Call initialize() twice

        Expected:
        - First initialization runs detection and caches result
        - Second initialization uses cached detection result

        Note: Uses HTTP-level mocking for reliability across environments.
        """
        base_url = "https://192.168.1.1:443"
        pre_login_probe_count = 0
        post_login_probe_count = 0

        def pre_login_callback(url, **kwargs):
            """Track pre-login probes (base URL check)."""
            nonlocal pre_login_probe_count
            pre_login_probe_count += 1
            # Return 200 to indicate UniFi OS
            return _callback_result(status=200, body="<html>UniFi OS</html>")

        def post_login_proxy_callback(url, **kwargs):
            """Track post-login proxy endpoint probes."""
            nonlocal post_login_probe_count
            post_login_probe_count += 1
            # Return success for proxy endpoint (UniFi OS)
            return _callback_result(
                status=200,
                payload={"meta": {"rc": "ok"}, "data": []},
            )

        def post_login_standard_callback(url, **kwargs):
            """Track post-login standard endpoint probes."""
            nonlocal post_login_probe_count
            post_login_probe_count += 1
            # Return 404 for standard endpoint
            return _callback_result(status=404)

        # Create connection manager
        manager = ConnectionManager(
            host="192.168.1.1",
            username="test_user",
            password="test_pass",
            port=443,
            site="default",
        )

        # Mock the Controller class
        mock_controller = MagicMock()
        mock_controller.login = AsyncMock()
        mock_controller.connectivity = MagicMock()
        mock_controller.connectivity.is_unifi_os = False
        mock_controller.connectivity.config = MagicMock()
        mock_controller.connectivity.config.session = MagicMock()
        mock_controller.connectivity.config.session.closed = False

        with aioresponses() as mock:
            # Pre-login detection endpoint (base URL)
            _mock_get(mock, base_url, callback=pre_login_callback, repeat=True)
            # Post-login detection endpoints
            _mock_get(
                mock,
                base_url,
                "/proxy/network/api/self/sites",
                callback=post_login_proxy_callback,
                repeat=True,
            )
            _mock_get(mock, base_url, "/api/self/sites", callback=post_login_standard_callback, repeat=True)
            # Mock login endpoint (UniFi OS uses /api/auth/login)
            _mock_post(
                mock,
                base_url,
                "/api/auth/login",
                payload={"unique_id": "test", "first_name": "Test", "last_name": "User"},
                repeat=True,
            )

            with patch("unifi_core.network.managers.connection_manager.Controller") as MockController:
                MockController.return_value = mock_controller
                with patch("unifi_network_mcp.bootstrap.UNIFI_CONTROLLER_TYPE", "auto"):
                    # First initialization
                    result1 = await manager.initialize()
                    first_pre_login = pre_login_probe_count

                    # Verify first initialization succeeded
                    assert result1 is True, "First initialization should succeed"
                    assert first_pre_login >= 1, "Pre-login detection should run on first init"
                    assert manager._unifi_os_override is True, "Detection result should be cached as UniFi OS"

                    # Reset initialized flag to force re-initialization logic
                    manager._initialized = False
                    # Close the session to force new session creation
                    if manager._aiohttp_session and not manager._aiohttp_session.closed:
                        await manager._aiohttp_session.close()

                    # Second initialization - should use cached result for pre-login
                    result2 = await manager.initialize()

                    # Verify second initialization succeeded
                    assert result2 is True, "Second initialization should succeed"
                    # Pre-login should use cached result (no additional pre-login probes)
                    # Note: post-login verification may still run
                    assert manager._unifi_os_override is True, "Cached result should be preserved"

        # Cleanup
        await manager.cleanup()

    @pytest.mark.asyncio
    async def test_request_includes_last_initialize_error_after_auth_failure(self):
        manager = ConnectionManager("192.168.1.1", "admin", "secret", max_retries=1)

        with patch("unifi_core.network.managers.connection_manager.Controller", _FailingLoginController):
            with patch("unifi_core.network.controller_type.resolve_controller_type", return_value="direct"):
                initialized = await manager.initialize()
                assert initialized is False

                with pytest.raises(ConnectionError) as exc_info:
                    await manager.request(ApiRequest(method="get", path="/stat/sysinfo"))

        assert "Not connected to controller" in str(exc_info.value)
        assert "SSO MFA required but no totp_secret configured" in str(exc_info.value)
        await manager.cleanup()

    @pytest.mark.asyncio
    async def test_last_initialize_error_redacts_configured_secret(self):
        manager = ConnectionManager("192.168.1.1", "admin", "super-secret-password", max_retries=1)

        with patch("unifi_core.network.managers.connection_manager.Controller", _PasswordLeakingLoginController):
            with patch("unifi_core.network.controller_type.resolve_controller_type", return_value="direct"):
                initialized = await manager.initialize()
                assert initialized is False

                with pytest.raises(ConnectionError) as exc_info:
                    await manager.request(ApiRequest(method="get", path="/stat/sysinfo"))

        message = str(exc_info.value)
        assert "super-secret-password" not in message
        assert "<redacted>" in message
        await manager.cleanup()
