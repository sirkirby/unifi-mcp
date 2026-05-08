from typing import Any, Dict, Optional, Tuple

from .schemas import (
    AP_GROUP_SCHEMA,
    AP_GROUP_UPDATE_SCHEMA,
    AUTOBACKUP_SETTINGS_UPDATE_SCHEMA,
    CLIENT_GROUP_UPDATE_SCHEMA,
    CONTENT_FILTER_UPDATE_SCHEMA,
    DEVICE_RADIO_UPDATE_SCHEMA,
    DNS_RECORD_SCHEMA,
    DNS_RECORD_UPDATE_SCHEMA,
    FIREWALL_POLICY_CREATE_SCHEMA,
    FIREWALL_POLICY_SCHEMA,
    FIREWALL_POLICY_SIMPLE_SCHEMA,
    FIREWALL_POLICY_UPDATE_SCHEMA,
    FIREWALL_POLICY_V2_CREATE_SCHEMA,
    FIREWALL_POLICY_V2_UPDATE_SCHEMA,
    NETWORK_SCHEMA,
    NETWORK_UPDATE_SCHEMA,
    OON_POLICY_UPDATE_SCHEMA,
    PORT_FORWARD_SCHEMA,
    PORT_FORWARD_SIMPLE_SCHEMA,
    PORT_FORWARD_UPDATE_SCHEMA,
    PORT_PROFILE_UPDATE_SCHEMA,
    QOS_RULE_SCHEMA,
    QOS_RULE_SIMPLE_SCHEMA,
    QOS_RULE_UPDATE_SCHEMA,
    SNMP_SETTINGS_UPDATE_SCHEMA,
    TRAFFIC_ROUTE_SCHEMA,
    TRAFFIC_ROUTE_SIMPLE_SCHEMA,
    TRAFFIC_ROUTE_UPDATE_SCHEMA,
    VPN_PROFILE_SCHEMA,
    WLAN_SCHEMA,
    WLAN_UPDATE_SCHEMA,
)
from .validators import ResourceValidator


class UniFiValidatorRegistry:
    """Registry for UniFi Network resource validators."""

    _validators = {
        "port_forward": ResourceValidator(PORT_FORWARD_SCHEMA, "Port Forwarding Rule"),
        "traffic_route": ResourceValidator(TRAFFIC_ROUTE_SCHEMA, "Traffic Route"),
        "wlan": ResourceValidator(WLAN_SCHEMA, "Wireless Network"),
        "network": ResourceValidator(NETWORK_SCHEMA, "Network"),
        "vpn_profile": ResourceValidator(VPN_PROFILE_SCHEMA, "VPN Client Profile"),
        "firewall_policy": ResourceValidator(FIREWALL_POLICY_SCHEMA, "Firewall Policy"),
        "firewall_policy_create": ResourceValidator(FIREWALL_POLICY_CREATE_SCHEMA, "Firewall Policy Create"),
        "port_forward_update": ResourceValidator(PORT_FORWARD_UPDATE_SCHEMA, "Port Forwarding Rule Update"),
        "traffic_route_update": ResourceValidator(TRAFFIC_ROUTE_UPDATE_SCHEMA, "Traffic Route Update"),
        "wlan_update": ResourceValidator(WLAN_UPDATE_SCHEMA, "Wireless Network Update"),
        "network_update": ResourceValidator(NETWORK_UPDATE_SCHEMA, "Network Update"),
        "firewall_policy_update": ResourceValidator(FIREWALL_POLICY_UPDATE_SCHEMA, "Firewall Policy Update"),
        "firewall_policy_simple": ResourceValidator(FIREWALL_POLICY_SIMPLE_SCHEMA, "Simple Firewall Policy"),
        "traffic_route_simple": ResourceValidator(TRAFFIC_ROUTE_SIMPLE_SCHEMA, "Simple Traffic Route"),
        "qos_rule": ResourceValidator(QOS_RULE_SCHEMA, "QoS Rule"),
        "qos_rule_update": ResourceValidator(QOS_RULE_UPDATE_SCHEMA, "QoS Rule Update"),
        "qos_rule_simple": ResourceValidator(QOS_RULE_SIMPLE_SCHEMA, "Simple QoS Rule"),
        "port_forward_simple": ResourceValidator(PORT_FORWARD_SIMPLE_SCHEMA, "Simple Port Forward Rule"),
        "firewall_policy_v2_create": ResourceValidator(
            FIREWALL_POLICY_V2_CREATE_SCHEMA, "V2 Zone-Based Firewall Policy Create"
        ),
        "firewall_policy_v2_update": ResourceValidator(
            FIREWALL_POLICY_V2_UPDATE_SCHEMA, "V2 Zone-Based Firewall Policy Update"
        ),
        # ACL rule validation migrated to pydantic model (models/acl.py) — see #139
        "port_profile_update": ResourceValidator(PORT_PROFILE_UPDATE_SCHEMA, "Port Profile Update"),
        "client_group_update": ResourceValidator(CLIENT_GROUP_UPDATE_SCHEMA, "Client Group Update"),
        "content_filter_update": ResourceValidator(CONTENT_FILTER_UPDATE_SCHEMA, "Content Filter Update"),
        "oon_policy_update": ResourceValidator(OON_POLICY_UPDATE_SCHEMA, "OON Policy Update"),
        "ap_group": ResourceValidator(AP_GROUP_SCHEMA, "AP Group"),
        "ap_group_update": ResourceValidator(AP_GROUP_UPDATE_SCHEMA, "AP Group Update"),
        "device_radio_update": ResourceValidator(DEVICE_RADIO_UPDATE_SCHEMA, "Device Radio Update"),
        "snmp_settings_update": ResourceValidator(SNMP_SETTINGS_UPDATE_SCHEMA, "SNMP Settings Update"),
        "autobackup_settings_update": ResourceValidator(
            AUTOBACKUP_SETTINGS_UPDATE_SCHEMA, "Auto-Backup Settings Update"
        ),
        "dns_record": ResourceValidator(DNS_RECORD_SCHEMA, "DNS Record"),
        "dns_record_update": ResourceValidator(DNS_RECORD_UPDATE_SCHEMA, "DNS Record Update"),
    }

    @classmethod
    def get_validator(cls, resource_type: str) -> Optional[ResourceValidator]:
        """Get validator for a resource type."""
        return cls._validators.get(resource_type)

    @classmethod
    def validate(
        cls, resource_type: str, params: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """Validate parameters for a resource type.

        Args:
            resource_type: The type of resource to validate
            params: The parameters to validate

        Returns:
            Tuple of (is_valid, error_message, validated_params)
        """
        validator = cls.get_validator(resource_type)
        if validator:
            return validator.validate(params)
        return False, f"No validator found for resource type: {resource_type}", None

    @classmethod
    def validate_and_apply_defaults(
        cls, resource_type: str, params: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """Validate and fill missing top-level properties with schema defaults.

        Opt-in companion to :meth:`validate` for create paths. See
        ``ResourceValidator.validate_and_apply_defaults`` — never use on
        update paths.
        """
        validator = cls.get_validator(resource_type)
        if validator:
            return validator.validate_and_apply_defaults(params)
        return False, f"No validator found for resource type: {resource_type}", None
