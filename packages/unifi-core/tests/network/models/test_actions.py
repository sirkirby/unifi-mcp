"""Tests for Network action-tool input models (_actions.py)."""

import pytest
from pydantic import ValidationError
from unifi_core.network.models._actions import (
    AdoptDeviceInput,
    AuthorizeGuestInput,
    BlockClientInput,
    ConfigurePortAggregationInput,
    ConfigurePortMirrorInput,
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
    def test_action_input_flag(self):
        assert BlockClientInput.__action_input__ is True

    def test_required_mac(self):
        with pytest.raises(ValidationError):
            BlockClientInput()

    def test_valid_construction(self):
        m = BlockClientInput(mac_address="AA:BB:CC:DD:EE:FF")
        assert m.mac_address == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# UnblockClientInput
# ---------------------------------------------------------------------------


class TestUnblockClientInput:
    def test_action_input_flag(self):
        assert UnblockClientInput.__action_input__ is True

    def test_required_mac(self):
        with pytest.raises(ValidationError):
            UnblockClientInput()

    def test_valid_construction(self):
        m = UnblockClientInput(mac_address="AA:BB:CC:DD:EE:FF")
        assert m.mac_address == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# RenameClientInput
# ---------------------------------------------------------------------------


class TestRenameClientInput:
    def test_action_input_flag(self):
        assert RenameClientInput.__action_input__ is True

    def test_required_mac(self):
        with pytest.raises(ValidationError):
            RenameClientInput(name="My Device")

    def test_required_name(self):
        with pytest.raises(ValidationError):
            RenameClientInput(mac_address="AA:BB:CC:DD:EE:FF")

    def test_valid_construction(self):
        m = RenameClientInput(mac_address="AA:BB:CC:DD:EE:FF", name="Living Room TV")
        assert m.mac_address == "AA:BB:CC:DD:EE:FF"
        assert m.name == "Living Room TV"


# ---------------------------------------------------------------------------
# ForceReconnectClientInput
# ---------------------------------------------------------------------------


class TestForceReconnectClientInput:
    def test_action_input_flag(self):
        assert ForceReconnectClientInput.__action_input__ is True

    def test_required_mac(self):
        with pytest.raises(ValidationError):
            ForceReconnectClientInput()

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
    def test_action_input_flag(self):
        assert ForgetClientInput.__action_input__ is True

    def test_required_mac(self):
        with pytest.raises(ValidationError):
            ForgetClientInput()

    def test_valid_construction(self):
        m = ForgetClientInput(mac_address="AA:BB:CC:DD:EE:FF")
        assert m.mac_address == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# SetClientIpSettingsInput
# ---------------------------------------------------------------------------


class TestSetClientIpSettingsInput:
    def test_action_input_flag(self):
        assert SetClientIpSettingsInput.__action_input__ is True

    def test_required_mac(self):
        with pytest.raises(ValidationError):
            SetClientIpSettingsInput()

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


# ---------------------------------------------------------------------------
# LocateDeviceInput
# ---------------------------------------------------------------------------


class TestLocateDeviceInput:
    def test_action_input_flag(self):
        assert LocateDeviceInput.__action_input__ is True

    def test_required_device_mac(self):
        with pytest.raises(ValidationError):
            LocateDeviceInput(enabled=True)

    def test_required_enabled(self):
        with pytest.raises(ValidationError):
            LocateDeviceInput(device_mac="AA:BB:CC:DD:EE:FF")

    def test_valid_construction(self):
        m = LocateDeviceInput(device_mac="AA:BB:CC:DD:EE:FF", enabled=True)
        assert m.device_mac == "AA:BB:CC:DD:EE:FF"
        assert m.enabled is True


# ---------------------------------------------------------------------------
# RebootDeviceInput
# ---------------------------------------------------------------------------


class TestRebootDeviceInput:
    def test_action_input_flag(self):
        assert RebootDeviceInput.__action_input__ is True

    def test_required_mac(self):
        with pytest.raises(ValidationError):
            RebootDeviceInput()

    def test_valid_construction(self):
        m = RebootDeviceInput(mac_address="AA:BB:CC:DD:EE:FF")
        assert m.mac_address == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# AdoptDeviceInput
# ---------------------------------------------------------------------------


class TestAdoptDeviceInput:
    def test_action_input_flag(self):
        assert AdoptDeviceInput.__action_input__ is True

    def test_required_mac(self):
        with pytest.raises(ValidationError):
            AdoptDeviceInput()

    def test_valid_construction(self):
        m = AdoptDeviceInput(mac_address="AA:BB:CC:DD:EE:FF")
        assert m.mac_address == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# UpgradeDeviceInput
# ---------------------------------------------------------------------------


class TestUpgradeDeviceInput:
    def test_action_input_flag(self):
        assert UpgradeDeviceInput.__action_input__ is True

    def test_required_mac(self):
        with pytest.raises(ValidationError):
            UpgradeDeviceInput()

    def test_valid_construction(self):
        m = UpgradeDeviceInput(mac_address="AA:BB:CC:DD:EE:FF")
        assert m.mac_address == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# RenameDeviceInput
# ---------------------------------------------------------------------------


class TestRenameDeviceInput:
    def test_action_input_flag(self):
        assert RenameDeviceInput.__action_input__ is True

    def test_required_mac(self):
        with pytest.raises(ValidationError):
            RenameDeviceInput(name="Office AP")

    def test_required_name(self):
        with pytest.raises(ValidationError):
            RenameDeviceInput(mac_address="AA:BB:CC:DD:EE:FF")

    def test_valid_construction(self):
        m = RenameDeviceInput(mac_address="AA:BB:CC:DD:EE:FF", name="Office AP")
        assert m.name == "Office AP"


# ---------------------------------------------------------------------------
# SetDeviceLedInput
# ---------------------------------------------------------------------------


class TestSetDeviceLedInput:
    def test_action_input_flag(self):
        assert SetDeviceLedInput.__action_input__ is True

    def test_required_device_mac(self):
        with pytest.raises(ValidationError):
            SetDeviceLedInput(led_state="on")

    def test_required_led_state(self):
        with pytest.raises(ValidationError):
            SetDeviceLedInput(device_mac="AA:BB:CC:DD:EE:FF")

    def test_valid_states(self):
        for state in ("on", "off", "default"):
            m = SetDeviceLedInput(device_mac="AA:BB:CC:DD:EE:FF", led_state=state)
            assert m.led_state == state


# ---------------------------------------------------------------------------
# ForceProvisionDeviceInput
# ---------------------------------------------------------------------------


class TestForceProvisionDeviceInput:
    def test_action_input_flag(self):
        assert ForceProvisionDeviceInput.__action_input__ is True

    def test_required_device_mac(self):
        with pytest.raises(ValidationError):
            ForceProvisionDeviceInput()

    def test_valid_construction(self):
        m = ForceProvisionDeviceInput(device_mac="AA:BB:CC:DD:EE:FF")
        assert m.device_mac == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# SetSwitchPortProfileInput
# ---------------------------------------------------------------------------


class TestSetSwitchPortProfileInput:
    def test_action_input_flag(self):
        assert SetSwitchPortProfileInput.__action_input__ is True

    def test_required_device_mac(self):
        with pytest.raises(ValidationError):
            SetSwitchPortProfileInput(port_overrides=[{"port_idx": 1, "portconf_id": "abc"}])

    def test_required_port_overrides(self):
        with pytest.raises(ValidationError):
            SetSwitchPortProfileInput(device_mac="AA:BB:CC:DD:EE:FF")

    def test_valid_construction(self):
        overrides = [{"port_idx": 1, "portconf_id": "profile-abc"}]
        m = SetSwitchPortProfileInput(device_mac="AA:BB:CC:DD:EE:FF", port_overrides=overrides)
        assert m.device_mac == "AA:BB:CC:DD:EE:FF"
        assert m.port_overrides == overrides


# ---------------------------------------------------------------------------
# SetOutletStateInput
# ---------------------------------------------------------------------------


class TestSetOutletStateInput:
    def test_action_input_flag(self):
        assert SetOutletStateInput.__action_input__ is True

    def test_required_mac(self):
        with pytest.raises(ValidationError):
            SetOutletStateInput(outlet_index=1, relay_state=True)

    def test_required_outlet_index(self):
        with pytest.raises(ValidationError):
            SetOutletStateInput(mac_address="AA:BB:CC:DD:EE:FF", relay_state=True)

    def test_outlet_index_minimum(self):
        m = SetOutletStateInput(mac_address="AA:BB:CC:DD:EE:FF", outlet_index=1, relay_state=True)
        assert m.outlet_index == 1

    def test_outlet_index_below_minimum(self):
        with pytest.raises(ValidationError):
            SetOutletStateInput(mac_address="AA:BB:CC:DD:EE:FF", outlet_index=0, relay_state=True)

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
    def test_action_input_flag(self):
        assert ConfigurePortAggregationInput.__action_input__ is True

    def test_required_device_mac(self):
        with pytest.raises(ValidationError):
            ConfigurePortAggregationInput(port_overrides=[])

    def test_valid_construction(self):
        overrides = [{"port_idx": 1, "op_mode": "aggregate", "aggregate_members": [1, 2], "lag_idx": 1}]
        m = ConfigurePortAggregationInput(device_mac="AA:BB:CC:DD:EE:FF", port_overrides=overrides)
        assert m.device_mac == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# ConfigurePortMirrorInput
# ---------------------------------------------------------------------------


class TestConfigurePortMirrorInput:
    def test_action_input_flag(self):
        assert ConfigurePortMirrorInput.__action_input__ is True

    def test_required_device_mac(self):
        with pytest.raises(ValidationError):
            ConfigurePortMirrorInput(port_overrides=[])

    def test_valid_construction(self):
        overrides = [{"port_idx": 1, "op_mode": "mirror", "mirror_port_idx": "2"}]
        m = ConfigurePortMirrorInput(device_mac="AA:BB:CC:DD:EE:FF", port_overrides=overrides)
        assert m.device_mac == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# SetJumboFramesInput
# ---------------------------------------------------------------------------


class TestSetJumboFramesInput:
    def test_action_input_flag(self):
        assert SetJumboFramesInput.__action_input__ is True

    def test_required_device_mac(self):
        with pytest.raises(ValidationError):
            SetJumboFramesInput(enabled=True)

    def test_required_enabled(self):
        with pytest.raises(ValidationError):
            SetJumboFramesInput(device_mac="AA:BB:CC:DD:EE:FF")

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
    def test_action_input_flag(self):
        assert SetSiteLedsInput.__action_input__ is True

    def test_required_enabled(self):
        with pytest.raises(ValidationError):
            SetSiteLedsInput()

    def test_valid_enable(self):
        m = SetSiteLedsInput(enabled=True)
        assert m.enabled is True

    def test_valid_disable(self):
        m = SetSiteLedsInput(enabled=False)
        assert m.enabled is False


# ---------------------------------------------------------------------------
# RevokeVoucherInput
# ---------------------------------------------------------------------------


class TestRevokeVoucherInput:
    def test_action_input_flag(self):
        assert RevokeVoucherInput.__action_input__ is True

    def test_required_voucher_id(self):
        with pytest.raises(ValidationError):
            RevokeVoucherInput()

    def test_valid_construction(self):
        m = RevokeVoucherInput(voucher_id="voucher-uuid-123")
        assert m.voucher_id == "voucher-uuid-123"


# ---------------------------------------------------------------------------
# QosRuleSimpleInput
# ---------------------------------------------------------------------------


class TestQosRuleSimpleInput:
    def test_action_input_flag(self):
        assert QosRuleSimpleInput.__action_input__ is True

    def test_required_name(self):
        with pytest.raises(ValidationError):
            QosRuleSimpleInput(interface="wan", direction="upload", limit_kbps=1000)

    def test_required_interface(self):
        with pytest.raises(ValidationError):
            QosRuleSimpleInput(name="Test", direction="upload", limit_kbps=1000)

    def test_required_direction(self):
        with pytest.raises(ValidationError):
            QosRuleSimpleInput(name="Test", interface="wan", limit_kbps=1000)

    def test_required_limit_kbps(self):
        with pytest.raises(ValidationError):
            QosRuleSimpleInput(name="Test", interface="wan", direction="upload")

    def test_limit_kbps_minimum(self):
        m = QosRuleSimpleInput(name="Test", interface="wan", direction="upload", limit_kbps=1)
        assert m.limit_kbps == 1

    def test_limit_kbps_below_minimum(self):
        with pytest.raises(ValidationError):
            QosRuleSimpleInput(name="Test", interface="wan", direction="upload", limit_kbps=0)

    def test_enabled_default_true(self):
        m = QosRuleSimpleInput(name="Test", interface="wan", direction="download", limit_kbps=500)
        assert m.enabled is True

    def test_dscp_value_bounds(self):
        m = QosRuleSimpleInput(name="T", interface="lan", direction="upload", limit_kbps=100, dscp_value=0)
        assert m.dscp_value == 0
        m2 = QosRuleSimpleInput(name="T", interface="lan", direction="upload", limit_kbps=100, dscp_value=63)
        assert m2.dscp_value == 63

    def test_dscp_value_below_min(self):
        with pytest.raises(ValidationError):
            QosRuleSimpleInput(name="T", interface="lan", direction="upload", limit_kbps=100, dscp_value=-1)

    def test_dscp_value_above_max(self):
        with pytest.raises(ValidationError):
            QosRuleSimpleInput(name="T", interface="lan", direction="upload", limit_kbps=100, dscp_value=64)

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
    def test_action_input_flag(self):
        assert PortForwardCreateInput.__action_input__ is True

    def test_required_name(self):
        with pytest.raises(ValidationError):
            PortForwardCreateInput(dst_port="80", fwd_port="8080", fwd_ip="192.168.1.10")

    def test_required_dst_port(self):
        with pytest.raises(ValidationError):
            PortForwardCreateInput(name="Web", fwd_port="8080", fwd_ip="192.168.1.10")

    def test_required_fwd_port(self):
        with pytest.raises(ValidationError):
            PortForwardCreateInput(name="Web", dst_port="80", fwd_ip="192.168.1.10")

    def test_required_fwd_ip(self):
        with pytest.raises(ValidationError):
            PortForwardCreateInput(name="Web", dst_port="80", fwd_port="8080")

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
    def test_action_input_flag(self):
        assert PortForwardUpdateInput.__action_input__ is True

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
    def test_action_input_flag(self):
        assert PortForwardSimpleInput.__action_input__ is True

    def test_required_name(self):
        with pytest.raises(ValidationError):
            PortForwardSimpleInput(ext_port="8443", to_ip="192.168.1.10")

    def test_required_ext_port(self):
        with pytest.raises(ValidationError):
            PortForwardSimpleInput(name="Home Web", to_ip="192.168.1.10")

    def test_required_to_ip(self):
        with pytest.raises(ValidationError):
            PortForwardSimpleInput(name="Home Web", ext_port="8443")

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
