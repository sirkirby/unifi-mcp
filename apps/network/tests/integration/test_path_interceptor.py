"""Integration tests for UniFi OS path interception functionality.

Tests the integration between ConnectionManager and aiounifi library to verify
that path overrides work correctly when making actual API requests.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aioresponses import aioresponses
from aiounifi.controller import Controller
from aiounifi.models.api import ApiRequest

from unifi_core.network.managers.connection_manager import ConnectionManager


class TestPathInterception:
    """Integration tests for path interception with ConnectionManager."""

    @pytest.mark.asyncio
    async def test_path_interception_unifi_os_mode(self):
        """Verify that when _unifi_os_override = True, all API requests use /proxy/network prefix.

        User Story 1 (Detection) - Validates that detected UniFi OS mode correctly
        applies proxy paths to all API requests.

        Setup:
        - Create ConnectionManager instance
        - Set _unifi_os_override = True
        - Mock controller and request method

        Test:
        - Make a request using ApiRequest
        - Verify is_unifi_os was set to True during request

        Expected:
        - is_unifi_os should be temporarily set to True
        - Request should complete successfully
        """
        manager = ConnectionManager(
            host="192.0.2.1",
            username="test_user",
            password="test_password",
            port=443,
            site="default",
            verify_ssl=False,
        )

        # Create a mock controller
        manager.controller = AsyncMock(spec=Controller)
        manager.controller.connectivity = MagicMock()
        manager.controller.connectivity.is_unifi_os = False  # Initially False
        manager.controller.connectivity.config = MagicMock()
        manager.controller.connectivity.config.session = MagicMock()
        manager.controller.connectivity.config.session.closed = False  # Session is open
        manager._initialized = True
        manager._aiohttp_session = AsyncMock()
        manager._aiohttp_session.closed = False

        # Track is_unifi_os state during request
        is_unifi_os_during_request = []

        async def mock_request_method(api_request):
            """Mock request that captures is_unifi_os state."""
            is_unifi_os_during_request.append(manager.controller.connectivity.is_unifi_os)
            return {"meta": {"rc": "ok"}, "data": [{"test": "data"}]}

        manager.controller.request = mock_request_method

        # Force UniFi OS mode
        manager._unifi_os_override = True

        # Make a request
        request = ApiRequest(method="get", path="/stat/sta")
        result = await manager.request(request)

        # Verify the request succeeded
        assert result is not None, "Request should return data"

        # Verify is_unifi_os was set to True during request
        assert len(is_unifi_os_during_request) == 1, "Should have captured state once"
        assert is_unifi_os_during_request[0] is True, "is_unifi_os should be True during request (override applied)"

        # Verify is_unifi_os was restored to False after request
        assert manager.controller.connectivity.is_unifi_os is False, (
            "is_unifi_os should be restored to original False value after request"
        )

    @pytest.mark.asyncio
    async def test_path_interception_standard_mode(self):
        """Verify that when _unifi_os_override = False, all API requests use /api paths.

        User Story 1 (Detection) - Validates that detected standard controller mode
        correctly uses direct API paths.

        Setup:
        - Create ConnectionManager instance
        - Set _unifi_os_override = False
        - Mock controller and request method

        Test:
        - Make a request using ApiRequest
        - Verify is_unifi_os was set to False during request

        Expected:
        - is_unifi_os should be set to False
        - Request should complete successfully
        """
        manager = ConnectionManager(
            host="192.0.2.1",
            username="test_user",
            password="test_password",
            port=443,
            site="default",
            verify_ssl=False,
        )

        # Create a mock controller
        manager.controller = AsyncMock(spec=Controller)
        manager.controller.connectivity = MagicMock()
        manager.controller.connectivity.is_unifi_os = True  # Initially True
        manager.controller.connectivity.config = MagicMock()
        manager.controller.connectivity.config.session = MagicMock()
        manager.controller.connectivity.config.session.closed = False  # Session is open
        manager._initialized = True
        manager._aiohttp_session = AsyncMock()
        manager._aiohttp_session.closed = False

        # Track is_unifi_os state during request
        is_unifi_os_during_request = []

        async def mock_request_method(api_request):
            """Mock request that captures is_unifi_os state."""
            is_unifi_os_during_request.append(manager.controller.connectivity.is_unifi_os)
            return {"meta": {"rc": "ok"}, "data": [{"test": "data"}]}

        manager.controller.request = mock_request_method

        # Force standard mode
        manager._unifi_os_override = False

        # Make a request
        request = ApiRequest(method="get", path="/stat/sta")
        result = await manager.request(request)

        # Verify the request succeeded
        assert result is not None, "Request should return data"

        # Verify is_unifi_os was set to False during request
        assert len(is_unifi_os_during_request) == 1, "Should have captured state once"
        assert is_unifi_os_during_request[0] is False, "is_unifi_os should be False during request (override applied)"

        # Verify is_unifi_os was restored to True after request
        assert manager.controller.connectivity.is_unifi_os is True, (
            "is_unifi_os should be restored to original True value after request"
        )

    @pytest.mark.asyncio
    async def test_manual_override_proxy(self):
        """Verify that UNIFI_CONTROLLER_TYPE=proxy forces proxy paths without detection.

        User Story 2 (Manual Override) - Validates that manual configuration
        bypasses automatic detection and forces UniFi OS proxy paths.

        Setup:
        - Patch UNIFI_CONTROLLER_TYPE to "proxy"
        - Mock detect_unifi_os_proactively to track if it's called

        Test:
        - Initialize ConnectionManager
        - Verify _unifi_os_override == True
        - Verify detection was NOT called

        Expected:
        - Detection should be skipped entirely
        - _unifi_os_override should be True
        """
        with aioresponses() as mock:
            # Mock successful login
            mock.post(
                "https://192.0.2.1:443/api/auth/login",
                status=200,
                payload={"meta": {"rc": "ok"}, "data": []},
            )

            detection_called = []

            async def mock_detect(*args, **kwargs):
                """Track if detection is called."""
                detection_called.append(True)
                return None

            # Patch the env var (read by resolve_controller_type) and the
            # detection function. Previously this patched a module-level
            # constant in unifi_network_mcp.bootstrap, but connection_manager
            # now reads via unifi_core.network.controller_type.resolve_controller_type
            # which calls os.getenv on each invocation.
            with patch.dict(os.environ, {"UNIFI_CONTROLLER_TYPE": "proxy"}):
                with patch(
                    "unifi_core.network.managers.connection_manager.detect_unifi_os_proactively",
                    mock_detect,
                ):
                    manager = ConnectionManager(
                        host="192.0.2.1",
                        username="test_user",
                        password="test_password",
                        port=443,
                        site="default",
                        verify_ssl=False,
                    )

                    # Initialize
                    await manager.initialize()

                    # Verify manual override was applied
                    assert manager._unifi_os_override is True, (
                        "Should force UniFi OS mode with UNIFI_CONTROLLER_TYPE=proxy"
                    )

                    # Verify detection was NOT called
                    assert len(detection_called) == 0, "Detection should NOT be called when manual override is set"

                    await manager.cleanup()

    @pytest.mark.asyncio
    async def test_manual_override_direct(self):
        """Verify that UNIFI_CONTROLLER_TYPE=direct forces direct paths without detection.

        User Story 2 (Manual Override) - Validates that manual configuration
        bypasses automatic detection and forces standard/direct API paths.

        Setup:
        - Patch UNIFI_CONTROLLER_TYPE to "direct"
        - Mock detect_unifi_os_proactively to track if it's called

        Test:
        - Initialize ConnectionManager
        - Verify _unifi_os_override == False
        - Verify detection was NOT called

        Expected:
        - Detection should be skipped entirely
        - _unifi_os_override should be False
        """
        with aioresponses() as mock:
            # Mock successful login
            mock.post(
                "https://192.0.2.1:443/api/login",
                status=200,
                payload={"meta": {"rc": "ok"}, "data": []},
            )

            detection_called = []

            async def mock_detect(*args, **kwargs):
                """Track if detection is called."""
                detection_called.append(True)
                return None

            # See note on the proxy variant above — patch the env var, not
            # the now-stale module-level constant.
            with patch.dict(os.environ, {"UNIFI_CONTROLLER_TYPE": "direct"}):
                with patch(
                    "unifi_core.network.managers.connection_manager.detect_unifi_os_proactively",
                    mock_detect,
                ):
                    manager = ConnectionManager(
                        host="192.0.2.1",
                        username="test_user",
                        password="test_password",
                        port=443,
                        site="default",
                        verify_ssl=False,
                    )

                    # Initialize
                    await manager.initialize()

                    # Verify manual override was applied
                    assert manager._unifi_os_override is False, (
                        "Should force standard/direct mode with UNIFI_CONTROLLER_TYPE=direct"
                    )

                    # Verify detection was NOT called
                    assert len(detection_called) == 0, "Detection should NOT be called when manual override is set"

                    await manager.cleanup()

    @pytest.mark.asyncio
    async def test_override_restoration(self):
        """Verify that is_unifi_os flag is correctly restored after each request.

        FR-003 - Validates that the temporary override of is_unifi_os flag
        during request execution is properly restored to maintain session state.

        Setup:
        - Create ConnectionManager with _unifi_os_override = True
        - Mock controller with is_unifi_os = False initially

        Test:
        - Make a request
        - During request: verify is_unifi_os was temporarily set to True
        - After request: verify is_unifi_os was restored to False

        Expected:
        - Before request: is_unifi_os = False (original state)
        - During request: is_unifi_os = True (override applied)
        - After request: is_unifi_os = False (restored)
        - Override restoration should work correctly
        """
        manager = ConnectionManager(
            host="192.0.2.1",
            username="test_user",
            password="test_password",
            port=443,
            site="default",
            verify_ssl=False,
        )

        # Create a mock controller
        manager.controller = AsyncMock(spec=Controller)
        manager.controller.connectivity = MagicMock()
        manager.controller.connectivity.is_unifi_os = False  # Original state
        manager.controller.connectivity.config = MagicMock()
        manager.controller.connectivity.config.session = MagicMock()
        manager.controller.connectivity.config.session.closed = False  # Session is open
        manager._initialized = True
        manager._aiohttp_session = AsyncMock()
        manager._aiohttp_session.closed = False

        # Set override to True (opposite of original)
        manager._unifi_os_override = True

        # Track state changes
        state_changes = []

        async def mock_request_method(api_request):
            """Mock request that captures is_unifi_os state."""
            state_changes.append(("during", manager.controller.connectivity.is_unifi_os))
            return {"meta": {"rc": "ok"}, "data": [{"test": "data"}]}

        manager.controller.request = mock_request_method

        # Capture initial state
        state_changes.append(("before", manager.controller.connectivity.is_unifi_os))

        # Make a request
        request = ApiRequest(method="get", path="/stat/sta")
        await manager.request(request)

        # Capture final state
        state_changes.append(("after", manager.controller.connectivity.is_unifi_os))

        # Verify state transitions
        assert len(state_changes) == 3, f"Should have 3 state captures. Got: {state_changes}"

        before_state = [s for s in state_changes if s[0] == "before"][0][1]
        during_state = [s for s in state_changes if s[0] == "during"][0][1]
        after_state = [s for s in state_changes if s[0] == "after"][0][1]

        assert before_state is False, f"Before request: is_unifi_os should be False. Got: {before_state}"
        assert during_state is True, f"During request: is_unifi_os should be True (overridden). Got: {during_state}"
        assert after_state is False, f"After request: is_unifi_os should be restored to False. Got: {after_state}"
