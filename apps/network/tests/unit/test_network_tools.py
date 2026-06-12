"""Tests for network tool functions.

Tests tool-layer behavior: validation, preview/confirm flow, response format,
and manager error propagation. Manager-level tests and schema validation tests
live in test_network_schema.py.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest

from unifi_core.redaction import REDACTED

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")


SAMPLE_NETWORK = {
    "_id": "net001",
    "name": "Test LAN",
    "purpose": "corporate",
    "ip_subnet": "10.0.0.1/24",
    "dhcpd_enabled": True,
    "dhcpd_start": "10.0.0.50",
    "dhcpd_stop": "10.0.0.150",
    "dhcpd_leasetime": 86400,
    "dhcpguard_enabled": False,
    "domain_name": "example.com",
    "vlan_enabled": True,
    "vlan": 10,
}


class TestUpdateNetwork:
    """Test the update_network tool — covers preview, confirm, error paths, and
    the Tuple[bool, Optional[str]] manager contract."""

    @pytest.mark.asyncio
    async def test_missing_network_id(self):
        """Empty network_id returns error."""
        from unifi_network_mcp.tools.network import update_network

        result = await update_network(
            network_id="",
            update_data={"domain_name": "new.example.com"},
            confirm=True,
        )

        assert result["success"] is False
        assert "network_id is required" in result["error"]

    @pytest.mark.asyncio
    async def test_empty_update_data(self):
        """Empty update_data short-circuits before calling manager."""
        from unifi_network_mcp.tools.network import update_network

        result = await update_network(
            network_id="net001",
            update_data={},
            confirm=True,
        )

        assert result["success"] is False
        assert "update_data cannot be empty" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_field_type(self):
        """Fields with wrong-type values pass through to the manager (type
        validation delegated to the controller API layer after pydantic migration).
        A known-mutable field with a non-None value is forwarded; the manager/
        controller rejects it there if needed."""
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_network_details = AsyncMock(return_value=SAMPLE_NETWORK)
            mock_mgr.update_network = AsyncMock(return_value=(True, None))
            updated = {**SAMPLE_NETWORK, "dhcpd_leasetime": "not-an-int"}
            mock_mgr.get_network_details = AsyncMock(side_effect=[SAMPLE_NETWORK, updated])

            from unifi_network_mcp.tools.network import update_network

            result = await update_network(
                network_id="net001",
                update_data={"dhcpd_leasetime": "not-an-int"},
                confirm=True,
            )

        # With pydantic-model filtering, the value passes to the manager;
        # tool returns success when manager succeeds.
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_network_not_found(self):
        """Missing network returns error without calling update_network."""
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_network_details = AsyncMock(return_value=None)
            mock_mgr.update_network = AsyncMock()

            from unifi_network_mcp.tools.network import update_network

            result = await update_network(
                network_id="nonexistent",
                update_data={"domain_name": "new.example.com"},
                confirm=True,
            )

        assert result["success"] is False
        assert "Network not found" in result["error"]
        mock_mgr.update_network.assert_not_called()

    @pytest.mark.asyncio
    async def test_preview_mode(self):
        """confirm=False returns preview with current state and proposed updates."""
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_network_details = AsyncMock(return_value=SAMPLE_NETWORK)
            mock_mgr.update_network = AsyncMock()

            from unifi_network_mcp.tools.network import update_network

            result = await update_network(
                network_id="net001",
                update_data={"domain_name": "new.example.com"},
                confirm=False,
            )

        assert result["success"] is True
        assert result.get("requires_confirmation") is True
        mock_mgr.update_network.assert_not_called()

    @pytest.mark.asyncio
    async def test_confirm_success(self):
        """confirm=True calls manager and returns updated details on success."""
        updated = {**SAMPLE_NETWORK, "domain_name": "new.example.com"}
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_network_details = AsyncMock(side_effect=[SAMPLE_NETWORK, updated])
            mock_mgr.update_network = AsyncMock(return_value=(True, None))

            from unifi_network_mcp.tools.network import update_network

            result = await update_network(
                network_id="net001",
                update_data={"domain_name": "new.example.com"},
                confirm=True,
            )

        assert result["success"] is True
        assert result["network_id"] == "net001"
        assert "domain_name" in result["updated_fields"]
        assert result["details"]["domain_name"] == "new.example.com"

    @pytest.mark.asyncio
    async def test_manager_error_surfaces_verbatim(self):
        """Controller error body from manager tuple propagates to caller.

        This test guards the whole point of the error-surfacing fix: a future
        refactor that reverts manager.update_network to bool would break this.
        """
        controller_error = "{'meta': {'rc': 'error', 'msg': 'api.err.MissingIPAddress'}, 'data': []}"
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_network_details = AsyncMock(return_value=SAMPLE_NETWORK)
            mock_mgr.update_network = AsyncMock(return_value=(False, controller_error))

            from unifi_network_mcp.tools.network import update_network

            result = await update_network(
                network_id="net001",
                update_data={"dhcpguard_enabled": True},
                confirm=True,
            )

        assert result["success"] is False
        assert "api.err.MissingIPAddress" in result["error"]
        assert "net001" in result["error"]
        # Ensure we're NOT returning the old misleading constant message
        assert "might not be fully implemented" not in result["error"]

    @pytest.mark.asyncio
    async def test_manager_tuple_contract_unpacking(self):
        """Regression guard: manager must return a 2-tuple, not a bare bool.

        If someone reverts manager.update_network to return bool, unpacking
        `success, error_detail = ...` will raise TypeError, and this test will
        catch it.
        """
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_network_details = AsyncMock(return_value=SAMPLE_NETWORK)
            # Simulate a regression: manager returns bare True
            mock_mgr.update_network = AsyncMock(return_value=True)

            from unifi_network_mcp.tools.network import update_network

            result = await update_network(
                network_id="net001",
                update_data={"domain_name": "new.example.com"},
                confirm=True,
            )

        # The tool catches the TypeError in its except block and returns error dict
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_vlan_range_validation(self):
        """VLAN ID outside 1-4094 is rejected by cross-field validation."""
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_network_details = AsyncMock(return_value=SAMPLE_NETWORK)
            mock_mgr.update_network = AsyncMock()

            from unifi_network_mcp.tools.network import update_network

            result = await update_network(
                network_id="net001",
                update_data={"vlan": "5000"},
                confirm=True,
            )

        assert result["success"] is False
        assert "1 and 4094" in result["error"]
        mock_mgr.update_network.assert_not_called()


class TestWlanToolRedaction:
    @pytest.mark.asyncio
    async def test_get_wlan_details_redacts_by_default_and_allows_opt_out(self):
        secret_wlan = {"_id": "w1", "name": "SSID", "x_passphrase": "wifi-secret"}
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_wlan_details = AsyncMock(return_value=secret_wlan)
            mock_mgr._connection.site = "default"

            from unifi_network_mcp.tools.network import get_wlan_details

            default = await get_wlan_details("w1")
            raw = await get_wlan_details("w1", include_sensitive=True)

        assert default["details"]["x_passphrase"] == REDACTED
        assert raw["details"]["x_passphrase"] == "wifi-secret"

    @pytest.mark.asyncio
    async def test_get_wlan_details_redacts_private_psk_and_iapp_key_by_default(self):
        secret_wlan = {
            "_id": "w1",
            "name": "SSID",
            "private_preshared_keys": [{"id": "k1", "psk": "wifi-psk"}],
            "private_preshared_keys_enabled": True,
            "x_iapp_key": "wlan-iapp",
        }
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_wlan_details = AsyncMock(return_value=secret_wlan)
            mock_mgr._connection.site = "default"

            from unifi_network_mcp.tools.network import get_wlan_details

            default = await get_wlan_details("w1")
            raw = await get_wlan_details("w1", include_sensitive=True)

        assert default["details"]["private_preshared_keys"] == REDACTED
        # The boolean toggle is non-sensitive config and stays visible.
        assert default["details"]["private_preshared_keys_enabled"] is True
        assert default["details"]["x_iapp_key"] == REDACTED
        assert raw["details"]["private_preshared_keys"] == [{"id": "k1", "psk": "wifi-psk"}]
        assert raw["details"]["private_preshared_keys_enabled"] is True
        assert raw["details"]["x_iapp_key"] == "wlan-iapp"

    @pytest.mark.asyncio
    async def test_update_wlan_preview_redacts_current_and_proposed_passphrase(self):
        secret_wlan = {"_id": "w1", "name": "SSID", "x_passphrase": "old-secret"}
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_wlan_details = AsyncMock(return_value=secret_wlan)
            mock_mgr.update_wlan = AsyncMock()

            from unifi_network_mcp.tools.network import update_wlan

            result = await update_wlan("w1", {"x_passphrase": "new-secret"}, confirm=False)

        assert result["preview"]["current"]["x_passphrase"] == REDACTED
        assert result["preview"]["proposed"]["x_passphrase"] == REDACTED
        mock_mgr.update_wlan.assert_not_called()

    # Redaction-marker write-back is rejected centrally at the MCP dispatch
    # boundary (StrictKwargFastMCP.call_tool), covered in the unifi-mcp-shared
    # strict_dispatch tests rather than per tool.

    @pytest.mark.asyncio
    async def test_create_wlan_preview_redacts_passphrase_by_default(self):
        from unifi_network_mcp.tools.network import create_wlan

        result = await create_wlan(
            {"name": "SSID", "security": "wpapsk", "x_passphrase": "wifi-secret"},
            confirm=False,
        )

        assert result["preview"]["will_create"]["x_passphrase"] == REDACTED
