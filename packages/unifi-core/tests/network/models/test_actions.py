"""Tests for Network action-tool input models (_actions.py)."""

import pytest
from pydantic import ValidationError
from unifi_core.network.models._actions import (
    AdoptDeviceInput,
    AuthorizeGuestInput,
    BlockClientInput,
    ConfigurePortAggregationInput,
    ConfigurePortMirrorInput,
    CreateVoucherInput,
    ForceProvisionDeviceInput,
    ForceReconnectClientInput,
    ForgetClientInput,
    LocateDeviceInput,
    PortForwardCreateInput,
    PortForwardSimpleInput,
    PortForwardUpdateInput,
    QosRuleSimpleInput,
    RebootDeviceInput,
    RenameClientInput,
    RenameDeviceInput,
    RevokeVoucherInput,
    SetClientFixedApInput,
    SetClientIpSettingsInput,
    SetDeviceLedInput,
    SetJumboFramesInput,
    SetOutletStateInput,
    SetSiteLedsInput,
    SetSwitchPortProfileInput,
    UnauthorizeGuestInput,
    UnblockClientInput,
    UpgradeDeviceInput,
)

# ---------------------------------------------------------------------------
# BlockClientInput
# ---------------------------------------------------------------------------


class TestBlockClientInput:
    def test_valid_construction(self):
        m = BlockClientInput(mac_address="AA:BB:CC:DD:EE:FF")
        assert m.mac_address == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# UnblockClientInput
# ---------------------------------------------------------------------------


class TestUnblockClientInput:
    def test_valid_construction(self):
        m = UnblockClientInput(mac_address="AA:BB:CC:DD:EE:FF")
        assert m.mac_address == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# RenameClientInput
# ---------------------------------------------------------------------------


class TestRenameClientInput:
    def test_valid_construction(self):
        m = RenameClientInput(mac_address="AA:BB:CC:DD:EE:FF", name="Living Room TV")
        assert m.mac_address == "AA:BB:CC:DD:EE:FF"
        assert m.name == "Living Room TV"


# ---------------------------------------------------------------------------
# ForceReconnectClientInput
# ---------------------------------------------------------------------------


class TestForceReconnectClientInput:
    def test_valid_construction(self):
        m = ForceReconnectClientInput(mac_address="AA:BB:CC:DD:EE:FF")
        assert m.mac_address == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# AuthorizeGuestInput
# ---------------------------------------------------------------------------


class TestAuthorizeGuestInput:
    def test_action_input_flag(self):
        assert AuthorizeGuestInput.__action_input__ is True

    def test_required_mac(self):
        with pytest.raises(ValidationError):
            AuthorizeGuestInput()

    def test_minutes_default(self):
        m = AuthorizeGuestInput(mac_address="AA:BB:CC:DD:EE:FF")
        assert m.minutes == 1440

    def test_minutes_minimum(self):
        m = AuthorizeGuestInput(mac_address="AA:BB:CC:DD:EE:FF", minutes=1)
        assert m.minutes == 1

    def test_minutes_below_minimum(self):
        with pytest.raises(ValidationError):
            AuthorizeGuestInput(mac_address="AA:BB:CC:DD:EE:FF", minutes=0)

    def test_optional_bandwidth_fields(self):
        m = AuthorizeGuestInput(
            mac_address="AA:BB:CC:DD:EE:FF",
            minutes=60,
            up_kbps=5000,
            down_kbps=10000,
            bytes_quota=1073741824,
        )
        assert m.up_kbps == 5000
        assert m.down_kbps == 10000
        assert m.bytes_quota == 1073741824

    def test_optional_fields_default_none(self):
        m = AuthorizeGuestInput(mac_address="AA:BB:CC:DD:EE:FF")
        assert m.up_kbps is None
        assert m.down_kbps is None
        assert m.bytes_quota is None


# ---------------------------------------------------------------------------
# UnauthorizeGuestInput
# ---------------------------------------------------------------------------


class TestUnauthorizeGuestInput:
    def test_action_input_flag(self):
        assert UnauthorizeGuestInput.__action_input__ is True

    def test_required_mac(self):
        with pytest.raises(ValidationError):
            UnauthorizeGuestInput()

    def test_valid_construction(self):
        m = UnauthorizeGuestInput(mac_address="AA:BB:CC:DD:EE:FF")
        assert m.mac_address == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# ForgetClientInput
# ---------------------------------------------------------------------------


class TestForgetClientInput:
    def test_valid_construction(self):
        m = ForgetClientInput(mac_address="AA:BB:CC:DD:EE:FF")
        assert m.mac_address == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# SetClientIpSettingsInput
# ---------------------------------------------------------------------------


class TestSetClientIpSettingsInput:
    def test_all_optional_fields_default_none(self):
        m = SetClientIpSettingsInput(mac_address="AA:BB:CC:DD:EE:FF")
        assert m.use_fixedip is None
        assert m.fixed_ip is None
        assert m.local_dns_record_enabled is None
        assert m.local_dns_record is None

    def test_valid_fixed_ip_construction(self):
        m = SetClientIpSettingsInput(
            mac_address="AA:BB:CC:DD:EE:FF",
            use_fixedip=True,
            fixed_ip="192.168.1.50",
        )
        assert m.use_fixedip is True
        assert m.fixed_ip == "192.168.1.50"

    def test_valid_dns_construction(self):
        m = SetClientIpSettingsInput(
            mac_address="AA:BB:CC:DD:EE:FF",
            local_dns_record_enabled=True,
            local_dns_record="mydevice.local",
        )
        assert m.local_dns_record == "mydevice.local"


class TestSetClientFixedApInput:
    def test_requires_access_point_when_enabling(self):
        with pytest.raises(ValidationError, match="fixed_ap_mac is required"):
            SetClientFixedApInput(mac_address="AA:BB:CC:DD:EE:FF", fixed_ap_enabled=True)

    def test_rejects_invalid_mac_addresses(self):
        with pytest.raises(ValidationError, match="valid MAC"):
            SetClientFixedApInput(mac_address="not-a-mac", fixed_ap_enabled=False)

    def test_accepts_disable_without_access_point(self):
        model = SetClientFixedApInput(mac_address="AA:BB:CC:DD:EE:FF", fixed_ap_enabled=False)
        assert model.fixed_ap_mac is None

    @pytest.mark.parametrize("ap_mac", ["", "11:22:33:44:55:66"])
    def test_normalizes_disable_access_point_to_none(self, ap_mac):
        model = SetClientFixedApInput(mac_address="AA:BB:CC:DD:EE:FF", fixed_ap_enabled=False, fixed_ap_mac=ap_mac)
        assert model.fixed_ap_mac is None

    def test_rejects_empty_client_mac(self):
        with pytest.raises(ValidationError, match="valid MAC"):
            SetClientFixedApInput(mac_address="", fixed_ap_enabled=False)


# ---------------------------------------------------------------------------
# LocateDeviceInput
# ---------------------------------------------------------------------------


class TestLocateDeviceInput:
    def test_valid_construction(self):
        m = LocateDeviceInput(device_mac="AA:BB:CC:DD:EE:FF", enabled=True)
        assert m.device_mac == "AA:BB:CC:DD:EE:FF"
        assert m.enabled is True


# ---------------------------------------------------------------------------
# RebootDeviceInput
# ---------------------------------------------------------------------------


class TestRebootDeviceInput:
    def test_valid_construction(self):
        m = RebootDeviceInput(mac_address="AA:BB:CC:DD:EE:FF")
        assert m.mac_address == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# AdoptDeviceInput
# ---------------------------------------------------------------------------


class TestAdoptDeviceInput:
    def test_valid_construction(self):
        m = AdoptDeviceInput(mac_address="AA:BB:CC:DD:EE:FF")
        assert m.mac_address == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# UpgradeDeviceInput
# ---------------------------------------------------------------------------


class TestUpgradeDeviceInput:
    def test_valid_construction(self):
        m = UpgradeDeviceInput(mac_address="AA:BB:CC:DD:EE:FF")
        assert m.mac_address == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# RenameDeviceInput
# ---------------------------------------------------------------------------


class TestRenameDeviceInput:
    def test_valid_construction(self):
        m = RenameDeviceInput(mac_address="AA:BB:CC:DD:EE:FF", name="Office AP")
        assert m.name == "Office AP"


# ---------------------------------------------------------------------------
# SetDeviceLedInput
# ---------------------------------------------------------------------------


class TestSetDeviceLedInput:
    def test_valid_states(self):
        for state in ("on", "off", "default"):
            m = SetDeviceLedInput(device_mac="AA:BB:CC:DD:EE:FF", led_state=state)
            assert m.led_state == state


# ---------------------------------------------------------------------------
# ForceProvisionDeviceInput
# ---------------------------------------------------------------------------


class TestForceProvisionDeviceInput:
    def test_valid_construction(self):
        m = ForceProvisionDeviceInput(device_mac="AA:BB:CC:DD:EE:FF")
        assert m.device_mac == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# SetSwitchPortProfileInput
# ---------------------------------------------------------------------------


class TestSetSwitchPortProfileInput:
    def test_valid_construction(self):
        overrides = [{"port_idx": 1, "portconf_id": "profile-abc"}]
        m = SetSwitchPortProfileInput(device_mac="AA:BB:CC:DD:EE:FF", port_overrides=overrides)
        assert m.device_mac == "AA:BB:CC:DD:EE:FF"
        assert m.port_overrides == overrides


# ---------------------------------------------------------------------------
# SetOutletStateInput
# ---------------------------------------------------------------------------


class TestSetOutletStateInput:
    def test_outlet_index_minimum(self):
        m = SetOutletStateInput(mac_address="AA:BB:CC:DD:EE:FF", outlet_index=1, relay_state=True)
        assert m.outlet_index == 1

    def test_cycle_enabled_default_none(self):
        m = SetOutletStateInput(mac_address="AA:BB:CC:DD:EE:FF", outlet_index=2, relay_state=False)
        assert m.cycle_enabled is None

    def test_valid_full_construction(self):
        m = SetOutletStateInput(
            mac_address="AA:BB:CC:DD:EE:FF",
            outlet_index=3,
            relay_state=True,
            cycle_enabled=False,
        )
        assert m.outlet_index == 3
        assert m.relay_state is True
        assert m.cycle_enabled is False


# ---------------------------------------------------------------------------
# ConfigurePortAggregationInput
# ---------------------------------------------------------------------------


class TestConfigurePortAggregationInput:
    def test_valid_construction(self):
        overrides = [{"port_idx": 1, "op_mode": "aggregate", "aggregate_members": [1, 2], "lag_idx": 1}]
        m = ConfigurePortAggregationInput(device_mac="AA:BB:CC:DD:EE:FF", port_overrides=overrides)
        assert m.device_mac == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# ConfigurePortMirrorInput
# ---------------------------------------------------------------------------


class TestConfigurePortMirrorInput:
    def test_valid_construction(self):
        overrides = [{"port_idx": 1, "op_mode": "mirror", "mirror_port_idx": "2"}]
        m = ConfigurePortMirrorInput(device_mac="AA:BB:CC:DD:EE:FF", port_overrides=overrides)
        assert m.device_mac == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# SetJumboFramesInput
# ---------------------------------------------------------------------------


class TestSetJumboFramesInput:
    def test_valid_enable(self):
        m = SetJumboFramesInput(device_mac="AA:BB:CC:DD:EE:FF", enabled=True)
        assert m.enabled is True

    def test_valid_disable(self):
        m = SetJumboFramesInput(device_mac="AA:BB:CC:DD:EE:FF", enabled=False)
        assert m.enabled is False


# ---------------------------------------------------------------------------
# SetSiteLedsInput
# ---------------------------------------------------------------------------


class TestSetSiteLedsInput:
    def test_valid_enable(self):
        m = SetSiteLedsInput(enabled=True)
        assert m.enabled is True

    def test_valid_disable(self):
        m = SetSiteLedsInput(enabled=False)
        assert m.enabled is False


# ---------------------------------------------------------------------------
# CreateVoucherInput
# ---------------------------------------------------------------------------


class TestCreateVoucherInput:
    def test_defaults_match_public_action_contract(self):
        model = CreateVoucherInput()

        assert model.expire_minutes == 1440
        assert model.count == 1
        assert model.quota == 1

    @pytest.mark.parametrize(
        "fields",
        [
            {"expire_minutes": 0},
            {"count": 0},
            {"count": 10001},
        ],
    )
    def test_rejects_values_outside_controller_safe_bounds(self, fields):
        with pytest.raises(ValidationError):
            CreateVoucherInput(**fields)


# ---------------------------------------------------------------------------
# RevokeVoucherInput
# ---------------------------------------------------------------------------


class TestRevokeVoucherInput:
    def test_valid_construction(self):
        m = RevokeVoucherInput(voucher_id="voucher-uuid-123")
        assert m.voucher_id == "voucher-uuid-123"


# ---------------------------------------------------------------------------
# QosRuleSimpleInput
# ---------------------------------------------------------------------------


class TestQosRuleSimpleInput:
    def test_limit_kbps_minimum(self):
        m = QosRuleSimpleInput(name="Test", interface="wan", direction="upload", limit_kbps=1)
        assert m.limit_kbps == 1

    def test_enabled_default_true(self):
        m = QosRuleSimpleInput(name="Test", interface="wan", direction="download", limit_kbps=500)
        assert m.enabled is True

    def test_dscp_value_bounds(self):
        m = QosRuleSimpleInput(name="T", interface="lan", direction="upload", limit_kbps=100, dscp_value=0)
        assert m.dscp_value == 0
        m2 = QosRuleSimpleInput(name="T", interface="lan", direction="upload", limit_kbps=100, dscp_value=63)
        assert m2.dscp_value == 63

    def test_target_optional(self):
        m = QosRuleSimpleInput(name="Test", interface="wan", direction="upload", limit_kbps=1000)
        assert m.target is None

    def test_target_ip(self):
        m = QosRuleSimpleInput(
            name="Test",
            interface="wan",
            direction="upload",
            limit_kbps=1000,
            target={"type": "ip", "value": "192.168.1.50"},
        )
        assert m.target is not None
        assert m.target.type == "ip"
        assert m.target.value == "192.168.1.50"


# ---------------------------------------------------------------------------
# PortForwardCreateInput
# ---------------------------------------------------------------------------


class TestPortForwardCreateInput:
    @pytest.mark.parametrize("destination", ["198.51.100.69", "any"])
    def test_destination_ip_accepted(self, destination):
        m = PortForwardCreateInput(
            name="Web", dst_port="80", fwd_port="8080", fwd_ip="192.168.1.10", destination_ip=destination
        )
        assert m.destination_ip == destination

    @pytest.mark.parametrize("destination", ["", "2001:db8::1", "198.51.100.0/24", "bad"])
    def test_invalid_destination_ip_rejected(self, destination):
        with pytest.raises(ValidationError):
            PortForwardCreateInput(
                name="Web", dst_port="80", fwd_port="8080", fwd_ip="192.168.1.10", destination_ip=destination
            )

    def test_protocol_default(self):
        m = PortForwardCreateInput(name="Web", dst_port="80", fwd_port="8080", fwd_ip="192.168.1.10")
        assert m.protocol == "tcp_udp"

    def test_enabled_default(self):
        m = PortForwardCreateInput(name="Web", dst_port="80", fwd_port="8080", fwd_ip="192.168.1.10")
        assert m.enabled is True

    def test_log_default(self):
        m = PortForwardCreateInput(name="Web", dst_port="80", fwd_port="8080", fwd_ip="192.168.1.10")
        assert m.log is False

    def test_src_ip_optional(self):
        m = PortForwardCreateInput(name="Web", dst_port="80", fwd_port="8080", fwd_ip="192.168.1.10")
        assert m.src_ip is None


# ---------------------------------------------------------------------------
# PortForwardUpdateInput
# ---------------------------------------------------------------------------


class TestPortForwardUpdateInput:
    @pytest.mark.parametrize("destination", ["2001:db8::1", "198.51.100.0/24", "bad"])
    def test_invalid_destination_ip_rejected(self, destination):
        with pytest.raises(ValidationError):
            PortForwardUpdateInput(destination_ip=destination)

    def test_destination_ip_explicit_null_is_distinct_from_omitted(self):
        assert "destination_ip" not in PortForwardUpdateInput().model_fields_set
        m = PortForwardUpdateInput(destination_ip=None)
        assert "destination_ip" in m.model_fields_set

    def test_all_fields_optional(self):
        # Should succeed with no args — all fields optional
        m = PortForwardUpdateInput()
        assert m.name is None
        assert m.dst_port is None
        assert m.fwd_port is None
        assert m.fwd_ip is None
        assert m.protocol is None
        assert m.enabled is None
        assert m.src_ip is None
        assert m.log is None

    def test_partial_update(self):
        m = PortForwardUpdateInput(name="New Name", enabled=False)
        assert m.name == "New Name"
        assert m.enabled is False

    def test_model_dump_excludes_none(self):
        m = PortForwardUpdateInput(name="Updated", dst_port="443")
        d = m.model_dump(exclude_none=True)
        assert d == {"name": "Updated", "dst_port": "443"}


# ---------------------------------------------------------------------------
# PortForwardSimpleInput
# ---------------------------------------------------------------------------


class TestPortForwardSimpleInput:
    def test_int_port_optional(self):
        m = PortForwardSimpleInput(name="Home Web", ext_port="8443", to_ip="192.168.1.10")
        assert m.int_port is None

    def test_protocol_default(self):
        m = PortForwardSimpleInput(name="Home Web", ext_port="8443", to_ip="192.168.1.10")
        assert m.protocol == "both"

    def test_enabled_default(self):
        m = PortForwardSimpleInput(name="Home Web", ext_port="8443", to_ip="192.168.1.10")
        assert m.enabled is True

    def test_valid_full_construction(self):
        m = PortForwardSimpleInput(
            name="SSH",
            ext_port="2222",
            to_ip="192.168.1.20",
            int_port="22",
            protocol="tcp",
            enabled=True,
        )
        assert m.ext_port == "2222"
        assert m.int_port == "22"
        assert m.protocol == "tcp"


class TestPortForwardInputStrictness:
    """Unknown keys fail loudly; long-accepted lax field coercion keeps working."""

    def test_unknown_key_is_rejected(self):
        with pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
            PortForwardCreateInput(name="Web", dst_port="80", fwd_port="8080", fwd_ip="192.168.1.10", fwdip="typo")

    def test_lax_scalar_coercion_still_accepted(self):
        m = PortForwardCreateInput(
            name="Web", dst_port="80", fwd_port="8080", fwd_ip="192.168.1.10", enabled="true", log=1
        )
        assert m.enabled is True
        assert m.log is True

    def test_update_unknown_key_is_rejected(self):
        with pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
            PortForwardUpdateInput(fwd="192.168.1.10")


@pytest.mark.parametrize(
    "model",
    [
        BlockClientInput,
        UnblockClientInput,
        RenameClientInput,
        ForceReconnectClientInput,
        ForgetClientInput,
        SetClientIpSettingsInput,
        LocateDeviceInput,
        RebootDeviceInput,
        AdoptDeviceInput,
        UpgradeDeviceInput,
        RenameDeviceInput,
        SetDeviceLedInput,
        ForceProvisionDeviceInput,
        SetSwitchPortProfileInput,
        SetOutletStateInput,
        ConfigurePortAggregationInput,
        ConfigurePortMirrorInput,
        SetJumboFramesInput,
        SetSiteLedsInput,
        RevokeVoucherInput,
        QosRuleSimpleInput,
        PortForwardCreateInput,
        PortForwardUpdateInput,
        PortForwardSimpleInput,
    ],
)
def test_action_input_flag(model):
    assert model.__action_input__ is True


@pytest.mark.parametrize(
    "model, fields",
    [
        (BlockClientInput, {}),
        (UnblockClientInput, {}),
        (RenameClientInput, {"name": "My Device"}),
        (RenameClientInput, {"mac_address": "AA:BB:CC:DD:EE:FF"}),
        (ForceReconnectClientInput, {}),
        (ForgetClientInput, {}),
        (SetClientIpSettingsInput, {}),
        (LocateDeviceInput, {"enabled": True}),
        (LocateDeviceInput, {"device_mac": "AA:BB:CC:DD:EE:FF"}),
        (RebootDeviceInput, {}),
        (AdoptDeviceInput, {}),
        (UpgradeDeviceInput, {}),
        (RenameDeviceInput, {"name": "Office AP"}),
        (RenameDeviceInput, {"mac_address": "AA:BB:CC:DD:EE:FF"}),
        (SetDeviceLedInput, {"led_state": "on"}),
        (SetDeviceLedInput, {"device_mac": "AA:BB:CC:DD:EE:FF"}),
        (ForceProvisionDeviceInput, {}),
        (SetSwitchPortProfileInput, {"port_overrides": [{"port_idx": 1, "portconf_id": "abc"}]}),
        (SetSwitchPortProfileInput, {"device_mac": "AA:BB:CC:DD:EE:FF"}),
        (SetOutletStateInput, {"outlet_index": 1, "relay_state": True}),
        (SetOutletStateInput, {"mac_address": "AA:BB:CC:DD:EE:FF", "relay_state": True}),
        (SetOutletStateInput, {"mac_address": "AA:BB:CC:DD:EE:FF", "outlet_index": 0, "relay_state": True}),
        (ConfigurePortAggregationInput, {"port_overrides": []}),
        (ConfigurePortMirrorInput, {"port_overrides": []}),
        (SetJumboFramesInput, {"enabled": True}),
        (SetJumboFramesInput, {"device_mac": "AA:BB:CC:DD:EE:FF"}),
        (SetSiteLedsInput, {}),
        (RevokeVoucherInput, {}),
        (QosRuleSimpleInput, {"interface": "wan", "direction": "upload", "limit_kbps": 1000}),
        (QosRuleSimpleInput, {"name": "Test", "direction": "upload", "limit_kbps": 1000}),
        (QosRuleSimpleInput, {"name": "Test", "interface": "wan", "limit_kbps": 1000}),
        (QosRuleSimpleInput, {"name": "Test", "interface": "wan", "direction": "upload"}),
        (QosRuleSimpleInput, {"name": "Test", "interface": "wan", "direction": "upload", "limit_kbps": 0}),
        (
            QosRuleSimpleInput,
            {"name": "T", "interface": "lan", "direction": "upload", "limit_kbps": 100, "dscp_value": -1},
        ),
        (
            QosRuleSimpleInput,
            {"name": "T", "interface": "lan", "direction": "upload", "limit_kbps": 100, "dscp_value": 64},
        ),
        (PortForwardCreateInput, {"dst_port": "80", "fwd_port": "8080", "fwd_ip": "192.168.1.10"}),
        (PortForwardCreateInput, {"name": "Web", "fwd_port": "8080", "fwd_ip": "192.168.1.10"}),
        (PortForwardCreateInput, {"name": "Web", "dst_port": "80", "fwd_ip": "192.168.1.10"}),
        (PortForwardCreateInput, {"name": "Web", "dst_port": "80", "fwd_port": "8080"}),
        (PortForwardSimpleInput, {"ext_port": "8443", "to_ip": "192.168.1.10"}),
        (PortForwardSimpleInput, {"name": "Home Web", "to_ip": "192.168.1.10"}),
        (PortForwardSimpleInput, {"name": "Home Web", "ext_port": "8443"}),
    ],
)
def test_invalid_action_input(model, fields):
    with pytest.raises(ValidationError):
        model(**fields)
