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


SAMPLE_WAN = {
    "_id": "wan001",
    "name": "Quantum",
    "purpose": "wan",
    "wan_networkgroup": "WAN",
    "wan_type": "dhcp",
    "wan_dns_preference": "auto",
    "wan_smartq_enabled": False,
}


class TestGetNetworkDetailsWanSummary:
    """WAN fields in get_network_details summary mode."""

    @pytest.mark.asyncio
    async def test_wan_summary_section_includes_wan_fields(self):
        """summary=true,include='wan' exposes the curated WAN config section."""
        wan = {
            **SAMPLE_WAN,
            "wan_load_balance_type": "weighted",
            "wan_load_balance_weight": 50,
            "wan_failover_priority": 1,
            "wan_vlan_enabled": False,
            "igmp_proxy_upstream": False,
            "igmp_proxy_for": ["net-a"],
            "mac_override_enabled": False,
            "wan_ip_aliases": [],
            "ipv6_enabled": True,
            "wan_type_v6": "disabled",
            "ipv6_setting_preference": "manual",
            "ipv6_wan_delegation_type": "none",
            "wan_dhcpv6_pd_size": 64,
            "wan_dhcpv6_pd_size_auto": False,
            "wan_ipv6_dns_preference": "auto",
            "wan_ipv6_dns1": "",
            "wan_ipv6_dns2": "",
        }
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_network_details = AsyncMock(return_value=wan)
            mock_mgr._connection.site = "default"

            from unifi_network_mcp.tools.network import get_network_details

            result = await get_network_details(network_id="wan001", summary=True, include="wan")

        assert result["success"] is True
        assert result["summary_mode"] is True
        assert result["details"]["wan_type"] == "dhcp"
        assert result["details"]["wan_load_balance_weight"] == 50
        assert result["details"]["igmp_proxy_for"] == ["net-a"]
        # IPv6 WAN keys present in the curated summary section (guards key typos/drops)
        assert result["details"]["ipv6_enabled"] is True
        assert result["details"]["wan_type_v6"] == "disabled"
        assert result["details"]["wan_dhcpv6_pd_size"] == 64
        assert result["details"]["wan_ipv6_dns_preference"] == "auto"
        for k in (
            "ipv6_setting_preference",
            "ipv6_wan_delegation_type",
            "wan_dhcpv6_pd_size_auto",
            "wan_ipv6_dns1",
            "wan_ipv6_dns2",
        ):
            assert k in result["details"], f"summary 'wan' section missing {k}"
        assert "dhcpd_enabled" not in result["details"]


class TestUpdateNetworkWanFields:
    """WAN field updates + connectivity-loss warnings in the confirm-preview."""

    @pytest.mark.asyncio
    async def test_wan_partial_update_forwards_only_changed_field(self):
        """Tool forwards ONLY the changed field to the manager; the merge/preservation step
        is the manager's deep_merge (covered in the manager suite), so this asserts forwarding."""
        updated = {**SAMPLE_WAN, "wan_smartq_enabled": True}
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_network_details = AsyncMock(side_effect=[SAMPLE_WAN, updated])
            mock_mgr.update_network = AsyncMock(return_value=(True, None))

            from unifi_network_mcp.tools.network import update_network

            result = await update_network(
                network_id="wan001",
                update_data={"wan_smartq_enabled": True},
                confirm=True,
            )

        assert result["success"] is True
        forwarded = mock_mgr.update_network.call_args[0][1]
        assert forwarded == {"wan_smartq_enabled": True}

    @pytest.mark.asyncio
    async def test_wan_preview_warns_on_connectivity_critical(self):
        """confirm=False with a connectivity-critical WAN field surfaces a warning."""
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_network_details = AsyncMock(return_value=SAMPLE_WAN)
            mock_mgr.update_network = AsyncMock()

            from unifi_network_mcp.tools.network import update_network

            result = await update_network(
                network_id="wan001",
                update_data={"wan_type": "static"},
                confirm=False,
            )

        assert result.get("requires_confirmation") is True
        warnings = result.get("warnings") or []
        assert any("interrupt internet" in w for w in warnings)
        assert any("wan_type" in w for w in warnings)
        mock_mgr.update_network.assert_not_called()

    @pytest.mark.asyncio
    async def test_wan_preview_no_warning_for_safe_field(self):
        """A non-connectivity-critical WAN field (smartq) emits no warning."""
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_network_details = AsyncMock(return_value=SAMPLE_WAN)
            mock_mgr.update_network = AsyncMock()

            from unifi_network_mcp.tools.network import update_network

            result = await update_network(
                network_id="wan001",
                update_data={"wan_smartq_enabled": True},
                confirm=False,
            )

        assert result.get("requires_confirmation") is True
        assert not result.get("warnings")
        mock_mgr.update_network.assert_not_called()

    def test_connectivity_critical_subset_of_mutable(self):
        """Every connectivity-critical field must be a real mutable model field.
        Guards against a future model rename silently disabling a warning."""
        from unifi_core.network.models.networks import MUTABLE_FIELDS
        from unifi_network_mcp.tools.network import CONNECTIVITY_CRITICAL_WAN_FIELDS

        missing = CONNECTIVITY_CRITICAL_WAN_FIELDS - MUTABLE_FIELDS
        assert not missing, f"critical fields not in MUTABLE_FIELDS (renamed?): {missing}"

    @pytest.mark.asyncio
    async def test_wan_preview_warns_for_every_critical_field(self):
        """The warning fires for EACH field in the critical set (not just wan_type),
        so dropping any one from the frozenset is caught."""
        from unifi_network_mcp.tools.network import CONNECTIVITY_CRITICAL_WAN_FIELDS, update_network

        for field in sorted(CONNECTIVITY_CRITICAL_WAN_FIELDS):
            value = 50 if field == "wan_load_balance_weight" else "x"
            with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
                mock_mgr.get_network_details = AsyncMock(return_value=SAMPLE_WAN)
                mock_mgr.update_network = AsyncMock()
                result = await update_network(network_id="wan001", update_data={field: value}, confirm=False)
            warnings = result.get("warnings") or []
            assert any("interrupt internet" in w for w in warnings), f"{field}: no warning fired"
            assert any(field in w for w in warnings), f"{field}: not named in warning"

    @pytest.mark.asyncio
    async def test_wan_preview_no_warning_for_non_wan_network(self):
        """A connectivity-critical WAN field on a NON-wan network emits no (mislabeled) warning."""
        lan = {"_id": "lan001", "name": "Test LAN", "purpose": "corporate"}
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_network_details = AsyncMock(return_value=lan)
            mock_mgr.update_network = AsyncMock()
            from unifi_network_mcp.tools.network import update_network

            result = await update_network(network_id="lan001", update_data={"wan_vlan_enabled": True}, confirm=False)

        assert result.get("requires_confirmation") is True
        assert not result.get("warnings")  # purpose != 'wan' -> no WAN warning / mislabel
        mock_mgr.update_network.assert_not_called()

    @pytest.mark.asyncio
    async def test_wan_load_balance_weight_out_of_range_rejected(self):
        """Out-of-range weight is rejected at the tool layer (parity with the vlan guard)."""
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_network_details = AsyncMock(return_value=SAMPLE_WAN)
            mock_mgr.update_network = AsyncMock()
            from unifi_network_mcp.tools.network import update_network

            result = await update_network(
                network_id="wan001", update_data={"wan_load_balance_weight": 999}, confirm=True
            )

        assert result["success"] is False
        assert "0 and 100" in result["error"]
        mock_mgr.update_network.assert_not_called()

    @pytest.mark.asyncio
    async def test_wan_load_balance_weight_out_of_range_rejected_in_preview(self):
        """Preview validates weight too; invalid previews must not look confirmable."""
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_network_details = AsyncMock(return_value=SAMPLE_WAN)
            mock_mgr.update_network = AsyncMock()
            from unifi_network_mcp.tools.network import update_network

            result = await update_network(
                network_id="wan001", update_data={"wan_load_balance_weight": 999}, confirm=False
            )

        assert result["success"] is False
        assert "0 and 100" in result["error"]
        assert result.get("requires_confirmation") is not True
        mock_mgr.get_network_details.assert_not_called()
        mock_mgr.update_network.assert_not_called()

    @pytest.mark.asyncio
    async def test_wan_ipv6_field_no_connectivity_warning(self):
        """IPv6 WAN fields are dual-stack and not connectivity-critical -> no warning."""
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_network_details = AsyncMock(return_value=SAMPLE_WAN)
            mock_mgr.update_network = AsyncMock()
            from unifi_network_mcp.tools.network import update_network

            result = await update_network(network_id="wan001", update_data={"ipv6_enabled": True}, confirm=False)

        assert result.get("requires_confirmation") is True
        assert not result.get("warnings")
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
