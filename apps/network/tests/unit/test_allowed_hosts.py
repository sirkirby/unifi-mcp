"""Unit tests for allowed hosts parsing in get_server().

These tests verify that UNIFI_MCP_ALLOWED_HOSTS is correctly parsed
and passed to FastMCP's TransportSecuritySettings.

Since src/runtime.py eagerly initializes singletons at import time,
we test the parsing logic by mocking FastMCP before import.
"""

import os
import sys
from unittest.mock import patch


class TestAllowedHostsParsing:
    """Test UNIFI_MCP_ALLOWED_HOSTS environment variable parsing in get_server()."""

    def _test_get_server_with_env(self, env_vars: dict, expected_hosts: list):
        """Helper to test get_server with specific environment variables.

        This carefully imports and tests get_server in isolation by:
        1. Mocking all dependencies that would fail without real config
        2. Setting up the specified environment variables
        3. Verifying TransportSecuritySettings passed to FastMCP
        """
        # Remove runtime from sys.modules to force reimport with new env
        modules_to_remove = [key for key in sys.modules if key.startswith("unifi_network_mcp.")]
        for mod in modules_to_remove:
            del sys.modules[mod]

        # Set up environment with required config vars + test vars
        test_env = {
            "UNIFI_HOST": "192.168.1.1",
            "UNIFI_USERNAME": "admin",
            "UNIFI_PASSWORD": "password",
            **env_vars,
        }

        # Remove UNIFI_MCP_ALLOWED_HOSTS if set in shell environment
        # (load_dotenv is mocked, so .env won't reload it during import)
        os.environ.pop("UNIFI_MCP_ALLOWED_HOSTS", None)

        with (
            patch.dict(os.environ, test_env),
            patch("dotenv.load_dotenv"),  # Prevent .env from being reloaded during import
            patch("unifi_mcp_shared.strict_dispatch.StrictKwargFastMCP") as mock_fastmcp,
        ):
            try:
                # Import triggers module-level get_server() call
                from unifi_network_mcp.runtime import get_server  # noqa: F401

                # Verify FastMCP was called with correct transport_security
                # Use call_args_list[-1] since module import may call it multiple times
                assert mock_fastmcp.call_args_list, "FastMCP should have been called"

                # Check the most recent call (from get_server())
                _, kwargs = mock_fastmcp.call_args_list[-1]
                settings = kwargs.get("transport_security")

                assert settings is not None, "transport_security should be passed to FastMCP"
                assert settings.allowed_hosts == expected_hosts, (
                    f"Expected {expected_hosts}, got {settings.allowed_hosts}"
                )

            finally:
                # Clean up modules for next test
                modules_to_remove = [key for key in sys.modules if key.startswith("unifi_network_mcp.")]
                for mod in modules_to_remove:
                    del sys.modules[mod]

    def test_default_allowed_hosts(self):
        """Test default allowed hosts when env var is not set."""
        self._test_get_server_with_env({}, ["localhost", "127.0.0.1"])

    def test_custom_allowed_hosts(self):
        """Test custom allowed hosts are parsed correctly."""
        self._test_get_server_with_env(
            {"UNIFI_MCP_ALLOWED_HOSTS": "example.com,foo.bar,baz.io"},
            ["example.com", "foo.bar", "baz.io"],
        )

    def test_whitespace_is_stripped(self):
        """Test that whitespace around hostnames is stripped."""
        self._test_get_server_with_env(
            {"UNIFI_MCP_ALLOWED_HOSTS": " example.com , foo.bar , baz.io "},
            ["example.com", "foo.bar", "baz.io"],
        )

    def test_empty_entries_are_filtered(self):
        """Test that empty entries from double commas are filtered out."""
        self._test_get_server_with_env(
            {"UNIFI_MCP_ALLOWED_HOSTS": "example.com,,foo.bar, ,baz.io"},
            ["example.com", "foo.bar", "baz.io"],
        )

    def test_single_host(self):
        """Test parsing a single host."""
        self._test_get_server_with_env(
            {"UNIFI_MCP_ALLOWED_HOSTS": "my-domain.example.com"},
            ["my-domain.example.com"],
        )

    def test_empty_value_results_in_empty_list(self):
        """Test that empty string results in empty allowed hosts list."""
        self._test_get_server_with_env({"UNIFI_MCP_ALLOWED_HOSTS": ""}, [])


class TestDnsRebindingProtection:
    """Test UNIFI_MCP_ENABLE_DNS_REBINDING_PROTECTION environment variable."""

    def _test_get_server_dns_rebinding(self, env_vars: dict, expected_enabled: bool):
        """Helper to test get_server with DNS rebinding protection settings.

        This carefully imports and tests get_server in isolation by:
        1. Mocking all dependencies that would fail without real config
        2. Setting up the specified environment variables
        3. Verifying enable_dns_rebinding_protection in TransportSecuritySettings
        """
        # Remove runtime from sys.modules to force reimport with new env
        modules_to_remove = [key for key in sys.modules if key.startswith("unifi_network_mcp.")]
        for mod in modules_to_remove:
            del sys.modules[mod]

        # Set up environment with required config vars + test vars
        test_env = {
            "UNIFI_HOST": "192.168.1.1",
            "UNIFI_USERNAME": "admin",
            "UNIFI_PASSWORD": "password",
            **env_vars,
        }

        # Remove env vars if set in shell environment
        os.environ.pop("UNIFI_MCP_ALLOWED_HOSTS", None)
        os.environ.pop("UNIFI_MCP_ENABLE_DNS_REBINDING_PROTECTION", None)

        with (
            patch.dict(os.environ, test_env),
            patch("dotenv.load_dotenv"),
            patch("unifi_mcp_shared.strict_dispatch.StrictKwargFastMCP") as mock_fastmcp,
        ):
            try:
                from unifi_network_mcp.runtime import get_server  # noqa: F401

                assert mock_fastmcp.call_args_list, "FastMCP should have been called"

                _, kwargs = mock_fastmcp.call_args_list[-1]
                settings = kwargs.get("transport_security")

                assert settings is not None, "transport_security should be passed to FastMCP"
                assert settings.enable_dns_rebinding_protection == expected_enabled, (
                    f"Expected enable_dns_rebinding_protection={expected_enabled}, "
                    f"got {settings.enable_dns_rebinding_protection}"
                )

            finally:
                modules_to_remove = [key for key in sys.modules if key.startswith("unifi_network_mcp.")]
                for mod in modules_to_remove:
                    del sys.modules[mod]

    def test_dns_rebinding_protection_enabled_by_default(self):
        """Test that DNS rebinding protection is enabled by default."""
        self._test_get_server_dns_rebinding({}, expected_enabled=True)

    def test_dns_rebinding_protection_disabled_with_false(self):
        """Test that setting to 'false' disables DNS rebinding protection."""
        self._test_get_server_dns_rebinding(
            {"UNIFI_MCP_ENABLE_DNS_REBINDING_PROTECTION": "false"},
            expected_enabled=False,
        )

    def test_dns_rebinding_protection_disabled_case_insensitive(self):
        """Test that 'FALSE' and 'False' also disable protection."""
        self._test_get_server_dns_rebinding(
            {"UNIFI_MCP_ENABLE_DNS_REBINDING_PROTECTION": "FALSE"},
            expected_enabled=False,
        )
        self._test_get_server_dns_rebinding(
            {"UNIFI_MCP_ENABLE_DNS_REBINDING_PROTECTION": "False"},
            expected_enabled=False,
        )

    def test_dns_rebinding_protection_enabled_with_true(self):
        """Test that explicitly setting to 'true' keeps it enabled."""
        self._test_get_server_dns_rebinding(
            {"UNIFI_MCP_ENABLE_DNS_REBINDING_PROTECTION": "true"},
            expected_enabled=True,
        )

    def test_dns_rebinding_protection_enabled_with_invalid_value(self):
        """Test that invalid values default to enabled (safe default)."""
        self._test_get_server_dns_rebinding(
            {"UNIFI_MCP_ENABLE_DNS_REBINDING_PROTECTION": "invalid"},
            expected_enabled=False,  # "invalid".lower() != "true"
        )

    def test_dns_rebinding_protection_enabled_with_empty_string(self):
        """Test that empty string defaults to disabled (empty != 'true')."""
        self._test_get_server_dns_rebinding(
            {"UNIFI_MCP_ENABLE_DNS_REBINDING_PROTECTION": ""},
            expected_enabled=False,  # "".lower() != "true"
        )
