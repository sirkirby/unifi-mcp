"""Tests for NETWORK_SCHEMA and NETWORK_UPDATE_SCHEMA validation.

Verifies DHCP, DNS, multicast, and network feature fields
are accepted or rejected correctly by the validator.
"""

from unifi_network_mcp.validator_registry import UniFiValidatorRegistry


class TestNetworkUpdateSchema:
    """Tests for network_update schema validation."""

    def test_dhcpd_fields_accepted(self):
        """Test DHCP server fields pass validation."""
        is_valid, error_msg, data = UniFiValidatorRegistry.validate(
            "network_update",
            {
                "dhcpd_enabled": True,
                "dhcpd_start": "10.0.0.100",
                "dhcpd_stop": "10.0.0.200",
                "dhcpd_leasetime": 86400,
            },
        )
        assert is_valid
        assert data["dhcpd_enabled"] is True
        assert data["dhcpd_leasetime"] == 86400

    def test_dhcpd_leasetime_minimum(self):
        """Test dhcpd_leasetime rejects values below minimum."""
        is_valid, error_msg, _ = UniFiValidatorRegistry.validate(
            "network_update",
            {"dhcpd_leasetime": 10},
        )
        assert not is_valid
        assert "minimum" in error_msg.lower() or "10" in error_msg

    def test_dhcpd_dns_fields_accepted(self):
        """Test DHCP DNS option fields pass validation."""
        is_valid, _, data = UniFiValidatorRegistry.validate(
            "network_update",
            {
                "dhcpd_dns_enabled": True,
                "dhcpd_dns_1": "1.1.1.1",
                "dhcpd_dns_2": "8.8.8.8",
            },
        )
        assert is_valid
        assert data["dhcpd_dns_1"] == "1.1.1.1"

    def test_dhcpd_ntp_fields_accepted(self):
        """Test DHCP NTP option fields pass validation."""
        is_valid, _, data = UniFiValidatorRegistry.validate(
            "network_update",
            {
                "dhcpd_ntp_enabled": True,
                "dhcpd_ntp_1": "pool.ntp.org",
            },
        )
        assert is_valid

    def test_dhcpd_wins_fields_accepted(self):
        """Test DHCP WINS option fields pass validation."""
        is_valid, _, data = UniFiValidatorRegistry.validate(
            "network_update",
            {
                "dhcpd_wins_enabled": True,
                "dhcpd_wins_1": "10.0.0.10",
            },
        )
        assert is_valid

    def test_dhcp_security_fields_accepted(self):
        """Test DHCP security fields pass validation."""
        is_valid, _, data = UniFiValidatorRegistry.validate(
            "network_update",
            {
                "dhcpguard_enabled": True,
                "dhcpd_conflict_checking": True,
                "dhcp_relay_enabled": False,
            },
        )
        assert is_valid

    def test_domain_name_accepted(self):
        """Test domain_name field passes validation."""
        is_valid, _, data = UniFiValidatorRegistry.validate(
            "network_update",
            {"domain_name": "example.com"},
        )
        assert is_valid
        assert data["domain_name"] == "example.com"

    def test_network_feature_fields_accepted(self):
        """Test network feature fields pass validation."""
        is_valid, _, data = UniFiValidatorRegistry.validate(
            "network_update",
            {
                "network_isolation_enabled": True,
                "internet_access_enabled": False,
                "upnp_lan_enabled": True,
            },
        )
        assert is_valid

    def test_igmp_fields_accepted(self):
        """Test IGMP/multicast fields pass validation."""
        is_valid, _, data = UniFiValidatorRegistry.validate(
            "network_update",
            {
                "igmp_snooping": True,
                "igmp_flood_unknown_multicast": False,
                "mdns_enabled": True,
            },
        )
        assert is_valid

    def test_igmp_querier_requires_switch_mac(self):
        """Test igmp_querier_switches rejects entries without switch_mac."""
        is_valid, error_msg, _ = UniFiValidatorRegistry.validate(
            "network_update",
            {"igmp_querier_switches": [{"querier_address": "10.0.0.1"}]},
        )
        assert not is_valid
        assert "switch_mac" in error_msg

    def test_wrong_type_rejected(self):
        """Test wrong types are rejected."""
        is_valid, error_msg, _ = UniFiValidatorRegistry.validate(
            "network_update",
            {"dhcpd_enabled": "yes"},
        )
        assert not is_valid
        assert "type" in error_msg.lower()

    def test_partial_update_accepted(self):
        """Test single field update passes (no required fields on update schema)."""
        is_valid, _, data = UniFiValidatorRegistry.validate(
            "network_update",
            {"domain_name": "new.example.com"},
        )
        assert is_valid
        assert len(data) == 1

    def test_pxe_boot_fields_accepted(self):
        """Test PXE/TFTP boot fields pass validation.

        Note: dhcpd_tftp_server is DHCP option 150 (Cisco TFTP, independent).
        PXE boot uses dhcpd_boot_server (BOOTP siaddr) + dhcpd_boot_filename.
        """
        is_valid, _, data = UniFiValidatorRegistry.validate(
            "network_update",
            {
                "dhcpd_boot_enabled": True,
                "dhcpd_boot_server": "10.0.0.5",
                "dhcpd_boot_filename": "pxelinux.0",
                "dhcpd_tftp_server": "10.0.0.6",
            },
        )
        assert is_valid
        assert set(data.keys()) == {
            "dhcpd_boot_enabled",
            "dhcpd_boot_server",
            "dhcpd_boot_filename",
            "dhcpd_tftp_server",
        }

    def test_dhcpd_unifi_controller_accepted(self):
        """Test UniFi controller DHCP option passes validation."""
        is_valid, _, data = UniFiValidatorRegistry.validate(
            "network_update",
            {"dhcpd_unifi_controller": "192.168.1.1"},
        )
        assert is_valid

    def test_dhcpguard_with_trusted_ip_accepted(self):
        """Test dhcpguard_enabled with required dhcpd_ip_1 trusted server."""
        is_valid, _, data = UniFiValidatorRegistry.validate(
            "network_update",
            {"dhcpguard_enabled": True, "dhcpd_ip_1": "192.168.1.1"},
        )
        assert is_valid
        assert data["dhcpguard_enabled"] is True
        assert data["dhcpd_ip_1"] == "192.168.1.1"


class TestWlanCreateSchema:
    """Tests for WLAN_SCHEMA validation around ap_group_ids and ap_group_mode (#208).

    Live-controller probe (UDM-SE 8.4.17) confirmed:
    - ap_group_ids: required on create, array of strings, empty list rejected
    - ap_group_mode: optional, enum ["all", "groups"], case-sensitive
    """

    def _base_payload(self, **overrides):
        payload = {
            "name": "TestSSID",
            "security": "wpa2-psk",
            "x_passphrase": "supersecret",
            "enabled": True,
            "ap_group_ids": ["abc"],
        }
        payload.update(overrides)
        return payload

    def test_create_with_ap_group_ids_and_mode_all_accepted(self):
        """Valid create with both ap_group_ids and ap_group_mode='all' validates."""
        is_valid, error_msg, data = UniFiValidatorRegistry.validate(
            "wlan",
            self._base_payload(ap_group_mode="all"),
        )
        assert is_valid, error_msg
        assert data["ap_group_ids"] == ["abc"]
        assert data["ap_group_mode"] == "all"

    def test_create_with_ap_group_ids_only_accepted(self):
        """ap_group_mode is optional; create succeeds without it."""
        is_valid, error_msg, data = UniFiValidatorRegistry.validate(
            "wlan",
            self._base_payload(),
        )
        assert is_valid, error_msg
        assert data["ap_group_ids"] == ["abc"]
        assert "ap_group_mode" not in data

    def test_create_missing_ap_group_ids_rejected(self):
        """Create without ap_group_ids fails validation with field name in error."""
        payload = self._base_payload()
        payload.pop("ap_group_ids")
        is_valid, error_msg, _ = UniFiValidatorRegistry.validate("wlan", payload)
        assert not is_valid
        assert "ap_group_ids" in error_msg

    def test_create_with_invalid_ap_group_mode_rejected(self):
        """ap_group_mode='custom' (the wrong-but-natural guess) fails with enum listed."""
        is_valid, error_msg, _ = UniFiValidatorRegistry.validate(
            "wlan",
            self._base_payload(ap_group_mode="custom"),
        )
        assert not is_valid
        # Enum error should mention the accepted values
        assert "all" in error_msg
        assert "groups" in error_msg

    def test_create_with_empty_ap_group_ids_rejected(self):
        """ap_group_ids: [] is rejected by minItems: 1 (mirrors controller behavior)."""
        is_valid, error_msg, _ = UniFiValidatorRegistry.validate(
            "wlan",
            self._base_payload(ap_group_ids=[]),
        )
        assert not is_valid
        # jsonschema reports minItems violations as "should be non-empty" / "too short"
        assert "non-empty" in error_msg.lower() or "short" in error_msg.lower() or "ap_group_ids" in error_msg

    def test_create_with_int_items_in_ap_group_ids_rejected(self):
        """ap_group_ids items must be strings; ints fail with a type error."""
        is_valid, error_msg, _ = UniFiValidatorRegistry.validate(
            "wlan",
            self._base_payload(ap_group_ids=[123]),
        )
        assert not is_valid
        assert "type" in error_msg.lower() or "string" in error_msg.lower()


class TestNetworkCreateSchemaPurposeRequirements:
    """Tests for NETWORK_SCHEMA conditional vlan requirement on create (#209).

    Live-controller probe (UDM-SE 8.4.17) confirmed:
    - For purpose in {corporate, vlan-only}, the controller silently defaults
      vlan=1 when not supplied, which collides with the default LAN
      (api.err.VlanUsed). Schema now requires explicit vlan + vlan_enabled=True.
    - ip_subnet is NOT force-required by the controller for corporate purpose
      (the network is non-functional without it, but create succeeds).
    """

    def test_corporate_with_explicit_vlan_accepted(self):
        """Corporate purpose with explicit vlan + vlan_enabled=True validates."""
        is_valid, error_msg, data = UniFiValidatorRegistry.validate(
            "network",
            {"name": "x", "purpose": "corporate", "vlan_enabled": True, "vlan": "100"},
        )
        assert is_valid, error_msg
        assert data["vlan"] == "100"
        assert data["vlan_enabled"] is True

    def test_vlan_only_with_explicit_vlan_accepted(self):
        """vlan-only purpose with explicit vlan + vlan_enabled=True validates."""
        is_valid, error_msg, data = UniFiValidatorRegistry.validate(
            "network",
            {"name": "x", "purpose": "vlan-only", "vlan_enabled": True, "vlan": "100"},
        )
        assert is_valid, error_msg
        assert data["vlan"] == "100"

    def test_corporate_missing_vlan_rejected(self):
        """Corporate purpose without vlan fails with mention of vlan."""
        is_valid, error_msg, _ = UniFiValidatorRegistry.validate(
            "network",
            {"name": "x", "purpose": "corporate"},
        )
        assert not is_valid
        assert "vlan" in error_msg.lower()

    def test_vlan_only_missing_vlan_rejected(self):
        """vlan-only purpose without vlan fails with mention of vlan."""
        is_valid, error_msg, _ = UniFiValidatorRegistry.validate(
            "network",
            {"name": "x", "purpose": "vlan-only"},
        )
        assert not is_valid
        assert "vlan" in error_msg.lower()

    def test_corporate_with_vlan_enabled_false_rejected(self):
        """Corporate with vlan_enabled=False fails the conditional rule.

        The conditional `properties: {vlan_enabled: {enum: [True]}}` produces a
        jsonschema error like "False is not one of [True]" — match on the enum
        violation rather than the field name.
        """
        is_valid, error_msg, _ = UniFiValidatorRegistry.validate(
            "network",
            {"name": "x", "purpose": "corporate", "vlan_enabled": False, "vlan": "100"},
        )
        assert not is_valid
        lowered = error_msg.lower()
        assert "false" in lowered and "true" in lowered

    def test_corporate_without_ip_subnet_accepted(self):
        """ip_subnet is NOT force-required for corporate (per live probe findings)."""
        is_valid, error_msg, data = UniFiValidatorRegistry.validate(
            "network",
            {"name": "x", "purpose": "corporate", "vlan_enabled": True, "vlan": "100"},
        )
        assert is_valid, error_msg
        assert "ip_subnet" not in data
