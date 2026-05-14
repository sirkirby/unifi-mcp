"""Pydantic input models for Network action tools and simplified create paths.

Action tools (block/unblock client, reboot device, set outlet, etc.) and
simplified create tools (simple QoS rule, simple port forward) take typed
action parameters rather than a round-trip domain object.  Each input class
lives here.

The class-level ``__action_input__`` flag marks these as out-of-scope for
the cross-layer field-symmetry test — they have no Strawberry read shape to
compare against.  Tools import the relevant input class and validate kwargs
via ``ToolInput(**kwargs)`` at the top of the body.
"""

from __future__ import annotations

from typing import ClassVar, Dict, List, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Client actions
# ---------------------------------------------------------------------------


class BlockClientInput(BaseModel):
    """Input for ``unifi_block_client``."""

    __action_input__: ClassVar[bool] = True

    mac_address: str = Field(description="MAC address of the client to block (AA:BB:CC:DD:EE:FF)")


class UnblockClientInput(BaseModel):
    """Input for ``unifi_unblock_client``."""

    __action_input__: ClassVar[bool] = True

    mac_address: str = Field(description="MAC address of the client to unblock (AA:BB:CC:DD:EE:FF)")


class RenameClientInput(BaseModel):
    """Input for ``unifi_rename_client``."""

    __action_input__: ClassVar[bool] = True

    mac_address: str = Field(description="MAC address of the client to rename (AA:BB:CC:DD:EE:FF)")
    name: str = Field(description="New display name for the client")


class ForceReconnectClientInput(BaseModel):
    """Input for ``unifi_force_reconnect_client``."""

    __action_input__: ClassVar[bool] = True

    mac_address: str = Field(description="MAC address of the client to force-reconnect (AA:BB:CC:DD:EE:FF)")


class AuthorizeGuestInput(BaseModel):
    """Input for ``unifi_authorize_guest``."""

    __action_input__: ClassVar[bool] = True

    mac_address: str = Field(description="MAC address of the guest client (AA:BB:CC:DD:EE:FF)")
    minutes: int = Field(default=1440, ge=1, description="Authorization duration in minutes (minimum 1)")
    up_kbps: Optional[int] = Field(default=None, ge=1, description="Upload bandwidth cap in Kbps")
    down_kbps: Optional[int] = Field(default=None, ge=1, description="Download bandwidth cap in Kbps")
    bytes_quota: Optional[int] = Field(default=None, ge=1, description="Total data quota in bytes")


class UnauthorizeGuestInput(BaseModel):
    """Input for ``unifi_unauthorize_guest``."""

    __action_input__: ClassVar[bool] = True

    mac_address: str = Field(description="MAC address of the guest client (AA:BB:CC:DD:EE:FF)")


class ForgetClientInput(BaseModel):
    """Input for ``unifi_forget_client``."""

    __action_input__: ClassVar[bool] = True

    mac_address: str = Field(description="MAC address of the client to forget (AA:BB:CC:DD:EE:FF)")


class SetClientIpSettingsInput(BaseModel):
    """Input for ``unifi_set_client_ip_settings``."""

    __action_input__: ClassVar[bool] = True

    mac_address: str = Field(description="MAC address of the client (AA:BB:CC:DD:EE:FF)")
    use_fixedip: Optional[bool] = Field(default=None, description="Enable/disable fixed IP (DHCP reservation)")
    fixed_ip: Optional[str] = Field(default=None, description="Static IP to assign (only used when use_fixedip=True)")
    local_dns_record_enabled: Optional[bool] = Field(
        default=None, description="Enable/disable local DNS record (UniFi Network 7.2+)"
    )
    local_dns_record: Optional[str] = Field(
        default=None,
        description="Local DNS hostname (only used when local_dns_record_enabled=True)",
    )


# ---------------------------------------------------------------------------
# Device actions
# ---------------------------------------------------------------------------


class LocateDeviceInput(BaseModel):
    """Input for ``unifi_locate_device``."""

    __action_input__: ClassVar[bool] = True

    device_mac: str = Field(description="MAC address of the device (from unifi_list_devices)")
    enabled: bool = Field(description="True to start LED blinking, False to stop")


class RebootDeviceInput(BaseModel):
    """Input for ``unifi_reboot_device``."""

    __action_input__: ClassVar[bool] = True

    mac_address: str = Field(description="MAC address of the device to reboot (AA:BB:CC:DD:EE:FF)")


class AdoptDeviceInput(BaseModel):
    """Input for ``unifi_adopt_device``."""

    __action_input__: ClassVar[bool] = True

    mac_address: str = Field(description="MAC address of the pending device to adopt (AA:BB:CC:DD:EE:FF)")


class UpgradeDeviceInput(BaseModel):
    """Input for ``unifi_upgrade_device``."""

    __action_input__: ClassVar[bool] = True

    mac_address: str = Field(description="MAC address of the device to upgrade (AA:BB:CC:DD:EE:FF)")


class RenameDeviceInput(BaseModel):
    """Input for ``unifi_rename_device``."""

    __action_input__: ClassVar[bool] = True

    mac_address: str = Field(description="MAC address of the device to rename (AA:BB:CC:DD:EE:FF)")
    name: str = Field(description="New display name for the device")


class SetDeviceLedInput(BaseModel):
    """Input for ``unifi_set_device_led``."""

    __action_input__: ClassVar[bool] = True

    device_mac: str = Field(description="MAC address of the device (from unifi_list_devices)")
    led_state: str = Field(description="LED override state: 'on', 'off', or 'default'")


class ForceProvisionDeviceInput(BaseModel):
    """Input for ``unifi_force_provision_device``."""

    __action_input__: ClassVar[bool] = True

    device_mac: str = Field(description="MAC address of the device (from unifi_list_devices)")


# ---------------------------------------------------------------------------
# Switch / port actions
# ---------------------------------------------------------------------------


class SetSwitchPortProfileInput(BaseModel):
    """Input for ``unifi_set_switch_port_profile``."""

    __action_input__: ClassVar[bool] = True

    device_mac: str = Field(description="MAC address of the switch")
    port_overrides: List[Dict] = Field(
        description="Complete list of port overrides. Each entry needs port_idx (int) and portconf_id (str)"
    )


class SetOutletStateInput(BaseModel):
    """Input for ``unifi_set_outlet_state``."""

    __action_input__: ClassVar[bool] = True

    mac_address: str = Field(description="MAC address of the PDU (AA:BB:CC:DD:EE:FF)")
    outlet_index: int = Field(ge=1, description="1-based outlet index on the strip")
    relay_state: bool = Field(description="True to power on, False to power off")
    cycle_enabled: Optional[bool] = Field(default=None, description="Optional per-outlet power-cycle-on-loss toggle")


class ConfigurePortAggregationInput(BaseModel):
    """Input for ``unifi_configure_port_aggregation``."""

    __action_input__: ClassVar[bool] = True

    device_mac: str = Field(description="MAC address of the switch")
    port_overrides: List[Dict] = Field(
        description=(
            "Complete port overrides array. The master port must have "
            "op_mode='aggregate', aggregate_members=[...], and lag_idx=<int>"
        )
    )


class ConfigurePortMirrorInput(BaseModel):
    """Input for ``unifi_configure_port_mirror``."""

    __action_input__: ClassVar[bool] = True

    device_mac: str = Field(description="MAC address of the switch")
    port_overrides: List[Dict] = Field(
        description=(
            "Complete port overrides array. The source port must have "
            "op_mode='mirror' and mirror_port_idx='<destination_port_idx>'"
        )
    )


# ---------------------------------------------------------------------------
# Site actions
# ---------------------------------------------------------------------------


class SetJumboFramesInput(BaseModel):
    """Input for ``unifi_set_jumbo_frames``."""

    __action_input__: ClassVar[bool] = True

    device_mac: str = Field(description="MAC address of the switch")
    enabled: bool = Field(description="True to enable jumbo frames, False to disable")


class SetSiteLedsInput(BaseModel):
    """Input for ``unifi_set_site_leds``."""

    __action_input__: ClassVar[bool] = True

    enabled: bool = Field(description="True to enable all site LEDs, False to disable them")


# ---------------------------------------------------------------------------
# Voucher action
# ---------------------------------------------------------------------------


class RevokeVoucherInput(BaseModel):
    """Input for ``unifi_revoke_voucher``."""

    __action_input__: ClassVar[bool] = True

    voucher_id: str = Field(description="Unique identifier (_id) of the voucher to revoke")


# ---------------------------------------------------------------------------
# Simplified create inputs (replace legacy validator calls in create tools)
# ---------------------------------------------------------------------------


class _QosTarget(BaseModel):
    """Nested target selector for QosRuleSimpleInput."""

    type: str = Field(description="Selector kind: 'ip' or 'subnet'")
    value: str = Field(description="IP address or CIDR subnet")


class QosRuleSimpleInput(BaseModel):
    """Input for the simplified QoS rule create path (``unifi_create_simple_qos_rule``)."""

    __action_input__: ClassVar[bool] = True

    name: str = Field(description="User-friendly name of the QoS rule")
    interface: str = Field(description="Target interface (e.g. 'wan', 'lan') — case-insensitive")
    direction: str = Field(description="Traffic direction: 'upload' or 'download'")
    limit_kbps: int = Field(ge=1, description="Bandwidth limit in kilobits per second")
    enabled: bool = Field(default=True, description="Enable rule (default true)")
    dscp_value: Optional[int] = Field(default=None, ge=0, le=63, description="DSCP value tag (0-63)")
    target: Optional[_QosTarget] = Field(
        default=None,
        description="Optional traffic selector. Omit to apply rule to all clients",
    )


class PortForwardCreateInput(BaseModel):
    """Input for the full port-forward create path (``unifi_create_port_forward``)."""

    __action_input__: ClassVar[bool] = True

    name: str = Field(description="Descriptive name for the port-forward rule")
    dst_port: str = Field(description="External (destination) port or range")
    fwd_port: str = Field(description="Internal (forward-to) port or range")
    fwd_ip: str = Field(description="Internal IP address to forward traffic to")
    protocol: str = Field(default="tcp_udp", description="Protocol: tcp, udp, or tcp_udp")
    enabled: bool = Field(default=True, description="Whether the rule is enabled initially")
    src_ip: Optional[str] = Field(default=None, description="Source IP/CIDR to match (empty = any)")
    log: bool = Field(default=False, description="Log rule matches")


class PortForwardUpdateInput(BaseModel):
    """Input for the port-forward update path (``unifi_update_port_forward``).

    All fields are optional — only supplied fields are applied.
    """

    __action_input__: ClassVar[bool] = True

    name: Optional[str] = Field(default=None, description="New name for the rule")
    dst_port: Optional[str] = Field(default=None, description="New external port or range")
    fwd_port: Optional[str] = Field(default=None, description="New internal port or range")
    fwd_ip: Optional[str] = Field(default=None, description="New internal IP address")
    protocol: Optional[str] = Field(default=None, description="New protocol: tcp, udp, or tcp_udp")
    enabled: Optional[bool] = Field(default=None, description="New enabled state")
    src_ip: Optional[str] = Field(default=None, description="New source IP/CIDR (empty string to remove)")
    log: Optional[bool] = Field(default=None, description="New logging state")


class PortForwardSimpleInput(BaseModel):
    """Input for the simplified port-forward create path (``unifi_create_simple_port_forward``)."""

    __action_input__: ClassVar[bool] = True

    name: str = Field(description="User-friendly name of the port forward rule")
    ext_port: str = Field(description="External (destination) port or range, e.g. '80' or '10000-10010'")
    to_ip: str = Field(description="Internal IP address to forward traffic to")
    int_port: Optional[str] = Field(
        default=None, description="Internal port to forward to (defaults to ext_port if omitted)"
    )
    protocol: str = Field(default="both", description="Protocol: 'tcp', 'udp', or 'both' (default both)")
    enabled: bool = Field(default=True, description="Enable rule (default true)")
