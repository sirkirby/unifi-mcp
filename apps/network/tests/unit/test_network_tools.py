"""Tests for network tool functions.

Tests tool-layer behavior: validation, preview/confirm flow, response format,
and manager error propagation. Manager-level tests and schema validation tests
live in test_network_schema.py.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest

from unifi_core.redaction import REDACTED
from unifi_core.write_verification import failed_write, verify_write

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
    """Test update_network preview, confirm, errors, and structured write results."""

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
        """Wrong field types are rejected before preview or controller access."""
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            from unifi_network_mcp.tools.network import update_network

            result = await update_network(
                network_id="net001",
                update_data={"dhcpd_leasetime": "not-an-int"},
                confirm=True,
            )

        assert result["success"] is False
        assert "Invalid network update data" in result["error"]
        mock_mgr.get_network_details.assert_not_called()
        mock_mgr.update_network.assert_not_called()

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
            mock_mgr.update_network = AsyncMock(
                return_value=verify_write(
                    operation="update",
                    requested={"domain_name": "new.example.com"},
                    before=SAMPLE_NETWORK,
                    after=updated,
                )
            )

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
        """Controller error detail from the structured manager result reaches the caller."""
        controller_error = "{'meta': {'rc': 'error', 'msg': 'api.err.MissingIPAddress'}, 'data': []}"
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_network_details = AsyncMock(return_value=SAMPLE_NETWORK)
            mock_mgr.update_network = AsyncMock(return_value=failed_write(controller_error, operation="update"))

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
    async def test_manager_structured_result_contract(self):
        """A regression to a bare bool is rejected instead of reporting phantom success."""
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


@pytest.mark.asyncio
async def test_update_network_preview_read_failure_returns_structured_error():
    with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
        mock_mgr.get_network_details = AsyncMock(side_effect=RuntimeError("controller unavailable"))

        from unifi_network_mcp.tools.network import update_network

        result = await update_network(
            network_id="net001",
            update_data={"enabled": False},
            confirm=False,
        )

    assert result == {
        "success": False,
        "error": "Failed to prepare network update for net001: controller unavailable",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "update_data,error_fragment",
    [
        ({"vlan": "not-an-integer"}, "must be an integer"),
        ({"vlan": 5000}, "between 1 and 4094"),
        ({"ip_subnet": "not-a-cidr"}, "valid IPv4 or IPv6 CIDR"),
    ],
)
async def test_update_network_rejects_malformed_values_before_preview(update_data, error_fragment):
    with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
        from unifi_network_mcp.tools.network import update_network

        result = await update_network("net001", update_data, confirm=False)

    assert result["success"] is False
    assert error_fragment in result["error"]
    mock_mgr.get_network_details.assert_not_called()


@pytest.mark.asyncio
async def test_create_network_rejects_malformed_vlan_without_exception():
    with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
        from unifi_network_mcp.tools.network import create_network

        result = await create_network(
            {"name": "Broken", "purpose": "vlan-only", "vlan": "not-an-integer"},
            confirm=False,
        )

    assert result["success"] is False
    assert "must be an integer" in result["error"]
    mock_mgr.create_network.assert_not_called()


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
            mock_mgr.update_network = AsyncMock(
                return_value=verify_write(
                    operation="update",
                    requested={"wan_smartq_enabled": True},
                    before=SAMPLE_WAN,
                    after=updated,
                )
            )

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
    async def test_confirmed_update_forwards_firewall_zone_and_wan_monitor_fields(self):
        fields = {
            "firewall_zone_id": "zone-v2-1",
            "wan_sla": "sla-1",
            "report_wan_event": False,
        }
        updated = {**SAMPLE_WAN, **fields}
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr._connection.site = "default"
            mock_mgr.get_network_details = AsyncMock(return_value=SAMPLE_WAN)
            mock_mgr.update_network = AsyncMock(
                return_value=verify_write(
                    operation="update",
                    requested=fields,
                    before=SAMPLE_WAN,
                    after=updated,
                )
            )

            from unifi_network_mcp.tools.network import update_network

            result = await update_network("wan001", fields, confirm=True)

        assert result["success"] is True
        mock_mgr.update_network.assert_awaited_once_with("wan001", fields)

    @pytest.mark.asyncio
    async def test_firewall_zone_preview_warns_about_security_scope(self):
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_network_details = AsyncMock(return_value=SAMPLE_NETWORK)

            from unifi_network_mcp.tools.network import update_network

            result = await update_network(
                "net001",
                {"firewall_zone_id": "zone-v2-1"},
                confirm=False,
            )

        warnings = result.get("warnings") or []
        assert any("security policies" in warning for warning in warnings)

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

        valid_values = {
            "wan_type": "static",
            "wan_networkgroup": "WAN2",
            "wan_dns_preference": "manual",
            "wan_load_balance_type": "weighted",
            "wan_load_balance_weight": 50,
            "wan_failover_priority": 1,
            "wan_sla": "sla-object-id",
            "wan_vlan_enabled": False,
            "mac_override_enabled": False,
        }
        for field in sorted(CONNECTIVITY_CRITICAL_WAN_FIELDS):
            value = valid_values[field]
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

    @pytest.mark.asyncio
    async def test_wan_ipv6_pd_delegation_preview(self):
        """The controller-native PD value reaches the confirmation preview unchanged."""
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_network_details = AsyncMock(return_value=SAMPLE_WAN)
            mock_mgr.update_network = AsyncMock()
            from unifi_network_mcp.tools.network import update_network

            result = await update_network(
                network_id="wan001",
                update_data={"ipv6_wan_delegation_type": "pd"},
                confirm=False,
            )

        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["preview"]["proposed"]["ipv6_wan_delegation_type"] == "pd"
        mock_mgr.update_network.assert_not_called()


class TestWlanToolRedaction:
    @pytest.mark.asyncio
    async def test_get_wlan_details_redacts_by_default_and_uses_policy_opt_out(self, monkeypatch):
        secret_wlan = {"_id": "w1", "name": "SSID", "x_passphrase": "wifi-secret"}
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_wlan_details = AsyncMock(return_value=secret_wlan)
            mock_mgr._connection.site = "default"

            from unifi_network_mcp.tools.network import get_wlan_details

            default = await get_wlan_details("w1")
            monkeypatch.setenv("UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS", "false")
            raw = await get_wlan_details("w1")

        assert default["details"]["x_passphrase"] == REDACTED
        assert raw["details"]["x_passphrase"] == "wifi-secret"

    @pytest.mark.asyncio
    async def test_get_wlan_details_redacts_private_psk_and_iapp_key_by_default(self, monkeypatch):
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
            monkeypatch.setenv("UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS", "false")
            raw = await get_wlan_details("w1")

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


class TestCreateWlanNetworkconfId:
    """create_wlan must forward networkconf_id to the manager regardless of whether
    the caller uses the controller field name (networkconf_id) or the model field name (network_id)."""

    @pytest.mark.asyncio
    async def test_networkconf_id_alias_reaches_manager(self):
        created = {"_id": "w99", "name": "HomeSSID", "networkconf_id": "net-abc"}
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.create_wlan = AsyncMock(
                return_value=verify_write(operation="create", requested={}, after=created, metadata={"wlan_id": "w99"})
            )
            mock_mgr._connection.site = "default"

            from unifi_network_mcp.tools.network import create_wlan

            result = await create_wlan(
                {
                    "name": "HomeSSID",
                    "security": "wpapsk",
                    "x_passphrase": "password1",
                    "networkconf_id": "net-abc",
                },
                confirm=True,
            )

        assert result["success"] is True
        payload = mock_mgr.create_wlan.call_args[0][0]
        assert payload.get("networkconf_id") == "net-abc", (
            "networkconf_id was silently dropped before reaching the manager"
        )
        assert "network_id" not in payload

    @pytest.mark.asyncio
    async def test_network_id_model_name_also_works(self):
        created = {"_id": "w99", "name": "HomeSSID", "networkconf_id": "net-abc"}
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.create_wlan = AsyncMock(
                return_value=verify_write(operation="create", requested={}, after=created, metadata={"wlan_id": "w99"})
            )
            mock_mgr._connection.site = "default"

            from unifi_network_mcp.tools.network import create_wlan

            result = await create_wlan(
                {
                    "name": "HomeSSID",
                    "security": "wpapsk",
                    "x_passphrase": "password1",
                    "network_id": "net-abc",
                },
                confirm=True,
            )

        assert result["success"] is True
        payload = mock_mgr.create_wlan.call_args[0][0]
        assert payload.get("networkconf_id") == "net-abc"


class TestCreateWlanRoamingFields:
    """Adding the roaming fields to Wlan.MUTABLE_FIELDS also makes create_wlan accept
    them, since it filters wlan_data through WLAN_MUTABLE_FIELDS. Pin that boundary:
    the model-conversion tests would still pass if create_wlan dropped them here."""

    @pytest.mark.asyncio
    async def test_roaming_fields_reach_the_manager(self):
        created = {"_id": "w99", "name": "HomeSSID"}
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.create_wlan = AsyncMock(
                return_value=verify_write(operation="create", requested={}, after=created, metadata={"wlan_id": "w99"})
            )
            mock_mgr._connection.site = "default"

            from unifi_network_mcp.tools.network import create_wlan

            result = await create_wlan(
                {
                    "name": "HomeSSID",
                    "security": "wpapsk",
                    "x_passphrase": "password1",
                    # rrm_enabled False and the negative RSSIs are deliberate: a
                    # truthiness filter anywhere on this path would silently eat them.
                    "rrm_enabled": False,
                    "roaming_assistant_na_enabled": True,
                    "roaming_assistant_na_rssi": -77,
                    "roaming_assistant_6e_enabled": True,
                    "roaming_assistant_6e_rssi": -88,
                },
                confirm=True,
            )

        assert result["success"] is True
        payload = mock_mgr.create_wlan.call_args[0][0]
        assert payload.get("rrm_enabled") is False, "rrm_enabled=False dropped before the manager"
        assert payload.get("roaming_assistant_na_enabled") is True
        assert payload.get("roaming_assistant_na_rssi") == -77
        assert payload.get("roaming_assistant_6e_enabled") is True
        assert payload.get("roaming_assistant_6e_rssi") == -88


class TestUpdateWlanNetworkconfId:
    """update_wlan must accept networkconf_id (controller field name) and not return
    'Update data is effectively empty or invalid' when it is the only field passed."""

    @pytest.mark.asyncio
    async def test_networkconf_id_alias_is_not_rejected(self):
        current_wlan = {"_id": "w1", "name": "SSID", "networkconf_id": "old-net"}
        updated_wlan = {"_id": "w1", "name": "SSID", "networkconf_id": "new-net"}
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_wlan_details = AsyncMock(side_effect=[current_wlan, updated_wlan])
            mock_mgr.update_wlan = AsyncMock(
                return_value=verify_write(
                    operation="update",
                    requested={"networkconf_id": "new-net"},
                    before=current_wlan,
                    after=updated_wlan,
                )
            )

            from unifi_network_mcp.tools.network import update_wlan

            result = await update_wlan("w1", {"networkconf_id": "new-net"}, confirm=True)

        assert result["success"] is True
        assert "networkconf_id" in result["updated_fields"]
        payload = mock_mgr.update_wlan.call_args[0][1]
        assert payload.get("networkconf_id") == "new-net"
        assert "network_id" not in payload

    @pytest.mark.asyncio
    async def test_networkconf_id_preview_is_not_rejected(self):
        current_wlan = {"_id": "w1", "name": "SSID", "networkconf_id": "old-net"}
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_wlan_details = AsyncMock(return_value=current_wlan)
            mock_mgr.update_wlan = AsyncMock()

            from unifi_network_mcp.tools.network import update_wlan

            result = await update_wlan("w1", {"networkconf_id": "new-net"}, confirm=False)

        assert "preview" in result
        assert result["preview"]["proposed"]["networkconf_id"] == "new-net"
        mock_mgr.update_wlan.assert_not_called()


@pytest.mark.asyncio
async def test_update_wlan_preview_includes_minrate_dependencies():
    current = {
        "_id": "wlan001",
        "name": "SSID",
        "minrate_setting_preference": "auto",
        "minrate_ng_enabled": False,
        "minrate_ng_data_rate_kbps": 1000,
    }
    with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
        mock_mgr.get_wlan_details = AsyncMock(return_value=current)

        from unifi_network_mcp.tools.network import update_wlan

        result = await update_wlan(
            wlan_id="wlan001",
            update_data={"minrate_ng_data_rate_kbps": 6000},
            confirm=False,
        )

    assert result["preview"]["proposed"] == {
        "minrate_ng_data_rate_kbps": 6000,
        "minrate_ng_enabled": True,
        "minrate_setting_preference": "manual",
    }


@pytest.mark.asyncio
async def test_update_wlan_preview_includes_validated_schedule_windows():
    current = {
        "_id": "wlan001",
        "name": "SSID",
        "schedule_enabled": False,
        "schedule_reversed": False,
        "schedule_with_duration": [],
    }
    windows = [
        {
            "duration_minutes": 360,
            "name": "Weeknight outage",
            "start_days_of_week": ["mon", "tue", "wed", "thu", "fri"],
            "start_hour": 1,
            "start_minute": 0,
        }
    ]
    with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
        mock_mgr.get_wlan_details = AsyncMock(return_value=current)

        from unifi_network_mcp.tools.network import update_wlan

        result = await update_wlan(
            wlan_id="wlan001",
            update_data={
                "schedule_enabled": True,
                "schedule_reversed": True,
                "schedule_with_duration": windows,
            },
            confirm=False,
        )

    assert result["preview"]["proposed"] == {
        "schedule_enabled": True,
        "schedule_reversed": True,
        "schedule_with_duration": windows,
    }


@pytest.mark.asyncio
async def test_update_wlan_rejects_mixed_unknown_field_before_preview():
    with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
        from unifi_network_mcp.tools.network import update_wlan

        result = await update_wlan(
            wlan_id="wlan001",
            update_data={"enabled": False, "unknown_field": True},
            confirm=False,
        )

    assert result["success"] is False
    assert "Unknown WLAN field" in result["error"]
    mock_mgr.get_wlan_details.assert_not_called()


@pytest.mark.asyncio
async def test_update_wlan_preview_read_failure_returns_structured_error():
    with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
        mock_mgr.get_wlan_details = AsyncMock(side_effect=RuntimeError("controller unavailable"))

        from unifi_network_mcp.tools.network import update_wlan

        result = await update_wlan(
            wlan_id="wlan001",
            update_data={"enabled": False},
            confirm=False,
        )

    assert result == {
        "success": False,
        "error": "Failed to prepare WLAN update for wlan001: controller unavailable",
    }


class TestUpdateNetworkReadOnlyFields:
    """update_network must reject read-only fields with a clear, specific error
    rather than a generic 'no valid fields' message."""

    @pytest.mark.asyncio
    async def test_mdns_enabled_returns_read_only_error(self):
        from unifi_network_mcp.tools.network import update_network

        result = await update_network(
            network_id="net001",
            update_data={"mdns_enabled": False},
            confirm=True,
        )

        assert result["success"] is False
        assert "mdns_enabled" in result["error"]
        assert "read-only" in result["error"]

    @pytest.mark.asyncio
    async def test_mdns_enabled_read_only_error_in_preview_mode(self):
        """confirm=False also returns the read-only error — the check fires before
        the preview gate so users get feedback without a wasted round-trip."""
        from unifi_network_mcp.tools.network import update_network

        result = await update_network(
            network_id="net001",
            update_data={"mdns_enabled": True},
            confirm=False,
        )

        assert result["success"] is False
        assert "mdns_enabled" in result["error"]
        assert "read-only" in result["error"]

    @pytest.mark.asyncio
    async def test_unknown_field_is_rejected_explicitly(self):
        """Completely unrecognised fields are rejected before controller access."""
        from unifi_network_mcp.tools.network import update_network

        result = await update_network(
            network_id="net001",
            update_data={"totally_unknown_field": "value"},
            confirm=True,
        )

        assert result["success"] is False
        assert "Unknown network field" in result["error"]
        assert "read-only" not in result["error"]

    @pytest.mark.asyncio
    async def test_read_only_field_mixed_with_valid_field_rejects_entire_update(self):
        """Mixed payloads cannot silently discard part of the caller's intent."""
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            from unifi_network_mcp.tools.network import update_network

            result = await update_network(
                network_id="net001",
                update_data={"name": "Updated LAN", "mdns_enabled": False},
                confirm=True,
            )

        assert result["success"] is False
        assert "mdns_enabled" in result["error"]
        assert "read-only" in result["error"]
        mock_mgr.get_network_details.assert_not_called()
        mock_mgr.update_network.assert_not_called()


class TestUpdateNetworkIpv6Preview:
    """Switching a delegated network to static IPv6 releases its prefix."""

    @pytest.mark.asyncio
    async def test_preview_warns_on_pd_to_static_ipv6(self):
        pd_network = {**SAMPLE_NETWORK, "ipv6_interface_type": "pd"}
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_network_details = AsyncMock(return_value=pd_network)
            mock_mgr.update_network = AsyncMock()

            from unifi_network_mcp.tools.network import update_network

            result = await update_network(
                network_id="net001",
                update_data={"ipv6_interface_type": "static"},
                confirm=False,
            )

        mock_mgr.update_network.assert_not_called()
        warnings = result.get("warnings") or []
        assert any("delegated prefix" in w for w in warnings), result

    @pytest.mark.asyncio
    async def test_preview_no_ipv6_warning_when_already_static(self):
        """No warning when there is no delegated prefix to lose."""
        static_network = {**SAMPLE_NETWORK, "ipv6_interface_type": "static"}
        with patch("unifi_network_mcp.tools.network.network_manager") as mock_mgr:
            mock_mgr.get_network_details = AsyncMock(return_value=static_network)
            mock_mgr.update_network = AsyncMock()

            from unifi_network_mcp.tools.network import update_network

            result = await update_network(
                network_id="net001",
                update_data={"ipv6_interface_type": "static"},
                confirm=False,
            )

        warnings = result.get("warnings") or []
        assert not any("delegated prefix" in w for w in warnings), result
