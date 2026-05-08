import copy
from typing import Any, Dict

# Port forwarding rule schema
PORT_FORWARD_SCHEMA = {
    "type": "object",
    "required": ["name", "dst_port", "fwd_port", "fwd_ip"],
    "properties": {
        "name": {
            "type": "string",
            "description": "Descriptive name for the port forwarding rule",
        },
        "dst_port": {
            "type": "string",
            "description": "Destination port (external port)",
        },
        "fwd_port": {
            "type": "string",
            "description": "Port to forward to (internal port)",
        },
        "fwd_ip": {"type": "string", "description": "IP address to forward to"},
        "protocol": {
            "type": "string",
            "enum": ["tcp", "udp", "tcp_udp"],
            "default": "tcp_udp",
            "description": "Network protocol",
        },
        "enabled": {
            "type": "boolean",
            "default": True,
            "description": "Whether rule is initially enabled",
        },
    },
    "additionalProperties": False,
}

# Port forwarding rule update schema (all fields optional)
PORT_FORWARD_UPDATE_SCHEMA = copy.deepcopy(PORT_FORWARD_SCHEMA)
PORT_FORWARD_UPDATE_SCHEMA.pop("required", None)  # Remove the required field
# Make all properties optional for update
for prop in PORT_FORWARD_UPDATE_SCHEMA.get("properties", {}):
    PORT_FORWARD_UPDATE_SCHEMA["properties"][prop].pop("default", None)  # Remove defaults for update

# Traffic route schema - Updated for V2 API structure
TRAFFIC_ROUTE_SCHEMA = {
    "type": "object",
    # Keep name/interface required based on POST API errors
    # Added network_id and target_devices as required based on API validation error for create
    "required": [
        "name",
        "interface",
        "matching_target",
        "network_id",
        "target_devices",
    ],
    "properties": {
        "name": {"type": "string", "description": "Descriptive name for the route"},
        "interface": {
            "type": "string",
            "description": "Interface name (e.g., 'wan', 'wan2', 'vpnclient0') required for creation",
        },
        "description": {"type": "string", "description": "Additional description"},
        "enabled": {
            "type": "boolean",
            "default": True,
            "description": "Whether route is enabled initially",
        },
        "matching_target": {
            "type": "string",
            "description": "Specifies the destination/source type",
            "enum": ["INTERNET", "DOMAIN", "IP", "REGION"],
        },
        # network_id is now required for creation according to API errors
        "network_id": {
            "type": "string",
            "description": "Network ID (LAN/VLAN) the route applies to (Required for creation)",
        },
        # target_devices is now required for creation according to API errors
        # It specifies WHICH devices/networks on the source network_id are affected
        "target_devices": {
            "type": "array",
            "description": "List of client devices or networks the route applies to (Required, cannot be empty). Defines the source scope within network_id.",
            "minItems": 1,  # Explicitly require at least one item based on API error
            "items": {
                "type": "object",
                "required": ["type"],  # Type is always needed
                "properties": {
                    # client_mac OR network_id should be present based on type
                    "client_mac": {
                        "type": "string",
                        "format": "mac",
                        "description": "MAC address of the client (Required if type is CLIENT)",
                    },
                    "network_id": {
                        "type": "string",
                        "description": "Network ID if type is NETWORK (Required if type is NETWORK)",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["CLIENT", "NETWORK"],
                        "description": "Type of target: CLIENT or NETWORK",
                    },
                },
                "allOf": [  # Add conditional requirements for client_mac/network_id
                    {
                        "if": {"properties": {"type": {"const": "CLIENT"}}},
                        "then": {"required": ["client_mac"]},
                    },
                    {
                        "if": {"properties": {"type": {"const": "NETWORK"}}},
                        "then": {"required": ["network_id"]},
                    },
                ],
            },
        },
        # Other fields matching TypedTrafficRoute model (made optional here, API validates)
        "domains": {
            "type": "array",
            "description": "List of domains with ports (used with matching_target: DOMAIN)",
            "items": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string"},
                    "ports": {"type": "array", "items": {"type": "integer"}},
                    "port_ranges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "port_start": {"type": "integer"},
                                "port_stop": {"type": "integer"},
                            },
                        },
                    },
                },
            },
        },
        "ip_addresses": {
            "type": "array",
            "description": "List of IPs/subnets with ports (used with matching_target: IP)",
            "items": {
                "type": "object",
                "properties": {
                    "ip_or_subnet": {"type": "string"},
                    "ip_version": {"type": "string"},
                    "ports": {"type": "array", "items": {"type": "integer"}},
                    "port_ranges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "port_start": {"type": "integer"},
                                "port_stop": {"type": "integer"},
                            },
                        },
                    },
                },
            },
        },
        "ip_ranges": {
            "type": "array",
            "description": "List of IP ranges",
            "items": {
                "type": "object",
                "properties": {
                    "ip_start": {"type": "string"},
                    "ip_stop": {"type": "string"},
                    "ip_version": {"type": "string"},
                },
            },
        },
        "regions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of regions (used with matching_target: REGION)",
        },
        "kill_switch_enabled": {
            "type": "boolean",
            "default": False,
            "description": "Whether kill switch is enabled (for VPNs)",
        },
        "next_hop": {
            "type": "string",
            "description": "Next hop IP address (advanced routing)",
        },
    },
    "additionalProperties": False,
}

# Traffic route update schema (derived from above, removes name/interface, makes fields optional)
TRAFFIC_ROUTE_UPDATE_SCHEMA = copy.deepcopy(TRAFFIC_ROUTE_SCHEMA)
# Remove fields not settable via update or missing from GET/PUT model
TRAFFIC_ROUTE_UPDATE_SCHEMA["properties"].pop("interface", None)
TRAFFIC_ROUTE_UPDATE_SCHEMA["properties"].pop("name", None)
# Updates are partial, so top-level fields aren't required for the UPDATE operation itself
# However, the items within arrays might still have requirements (handled by schema)
TRAFFIC_ROUTE_UPDATE_SCHEMA.pop("required", None)

# Make all remaining top-level properties optional for update
for prop in TRAFFIC_ROUTE_UPDATE_SCHEMA.get("properties", {}):
    TRAFFIC_ROUTE_UPDATE_SCHEMA["properties"][prop].pop("default", None)

# Simplified high-level Traffic Route schema for LLM-friendly creation
TRAFFIC_ROUTE_SIMPLE_SCHEMA = {
    "type": "object",
    "required": [
        "name",
        "interface",
        "network",
        "matching_target",
    ],
    "properties": {
        "name": {"type": "string"},
        "interface": {"type": "string"},
        "network": {"type": "string", "description": "Source LAN/VLAN name or id"},
        "client_macs": {
            "type": "array",
            "items": {"type": "string", "format": "mac"},
            "description": "Optional list of client MACs within the network. If omitted the entire network is routed.",
        },
        "matching_target": {
            "type": "string",
            "enum": ["INTERNET", "DOMAIN", "IP", "REGION"],
        },
        "destinations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Destination values depending on matching_target (domain names, IPs, regions). Not required for INTERNET.",
        },
        "enabled": {"type": "boolean"},
    },
    "additionalProperties": False,
}

# WLAN (Wireless Network) schema
WLAN_SCHEMA = {
    "type": "object",
    "required": ["name", "security", "enabled", "ap_group_ids"],
    "properties": {
        "name": {
            "type": "string",
            "description": "Name of the wireless network (SSID)",
        },
        "security": {
            "type": "string",
            "enum": ["open", "wpa-psk", "wpa2-psk", "wpa3", "wpapsk", "wep"],
            "description": "Security protocol",
        },
        "x_passphrase": {
            "type": "string",
            "description": "Password for the wireless network",
        },
        "enabled": {"type": "boolean", "description": "Whether the network is enabled"},
        "hide_ssid": {
            "type": "boolean",
            "default": False,
            "description": "Whether to hide the SSID",
        },
        "guest_policy": {
            "type": "boolean",
            "default": False,
            "description": "Whether this is a guest network",
        },
        "usergroup_id": {"type": "string", "description": "User group ID"},
        "networkconf_id": {"type": "string", "description": "Network configuration ID"},
        "fast_roaming_enabled": {
            "type": "boolean",
            "description": "Enable 802.11r fast BSS transition",
        },
        "pmf_mode": {
            "type": "string",
            "enum": ["disabled", "optional", "required"],
            "description": "Protected Management Frames (802.11w) mode",
        },
        "wpa3_support": {"type": "boolean", "description": "Enable WPA3 support"},
        "wpa3_transition": {
            "type": "boolean",
            "description": "Enable WPA3 transition mode (WPA2+WPA3)",
        },
        "mac_filter_enabled": {
            "type": "boolean",
            "description": "Enable MAC address filtering on this WLAN",
        },
        "mac_filter_policy": {
            "type": "string",
            "enum": ["allow", "deny"],
            "description": "MAC filter policy: allow (whitelist) or deny (blacklist)",
        },
        "mac_filter_list": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of MAC addresses for the filter",
        },
        "schedule_enabled": {
            "type": "boolean",
            "description": "Enable WLAN schedule (time-based on/off)",
        },
        "l2_isolation": {
            "type": "boolean",
            "description": "Enable L2 client isolation within this WLAN",
        },
        "wlan_band": {
            "type": "string",
            "enum": ["both", "2g", "5g"],
            "description": "Restrict WLAN to specific band",
        },
        "multicast_enhance_enabled": {
            "type": "boolean",
            "description": "Convert multicast to unicast per client",
        },
        "dtim_mode": {
            "type": "string",
            "enum": ["default", "custom"],
            "description": "DTIM interval mode",
        },
        "dtim_na": {
            "type": "integer",
            "minimum": 1,
            "maximum": 255,
            "description": "DTIM interval for 5GHz radio",
        },
        "dtim_ng": {
            "type": "integer",
            "minimum": 1,
            "maximum": 255,
            "description": "DTIM interval for 2.4GHz radio",
        },
        "minrate_ng_enabled": {
            "type": "boolean",
            "description": "Enable minimum data rate for 2.4GHz",
        },
        "minrate_ng_data_rate_kbps": {
            "type": "integer",
            "description": "Minimum data rate for 2.4GHz in kbps",
        },
        "minrate_na_enabled": {
            "type": "boolean",
            "description": "Enable minimum data rate for 5GHz",
        },
        "minrate_na_data_rate_kbps": {
            "type": "integer",
            "description": "Minimum data rate for 5GHz in kbps",
        },
        "group_rekey": {
            "type": "integer",
            "minimum": 0,
            "description": "Group key rotation interval in seconds (0=disabled)",
        },
        "uapsd_enabled": {
            "type": "boolean",
            "description": "Enable Unscheduled Automatic Power Save Delivery",
        },
        "proxy_arp": {
            "type": "boolean",
            "description": "Enable proxy ARP for wireless clients",
        },
        "iapp_enabled": {
            "type": "boolean",
            "description": "Enable Inter-AP communication protocol",
        },
        "ap_group_ids": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": (
                "AP group IDs that this WLAN broadcasts on. Required on create; "
                "an empty list is rejected by the controller. Use "
                "`unifi_list_ap_groups` to discover available IDs (the default "
                'all-APs group has type "All-APs").'
            ),
        },
        "ap_group_mode": {
            "type": "string",
            "enum": ["all", "groups"],
            "description": (
                "Whether the WLAN broadcasts on all APs (`all`) or only the "
                "groups listed in `ap_group_ids` (`groups`). Optional — the "
                "controller infers and may rewrite the value to keep it "
                "consistent with the supplied IDs. Case-sensitive."
            ),
        },
    },
    "allOf": [
        {"if": {"properties": {"security": {"enum": ["open"]}}}, "then": {}},
        {
            "if": {"properties": {"security": {"not": {"enum": ["open"]}}}},
            "then": {"required": ["x_passphrase"]},
        },
    ],
    "additionalProperties": False,
}

# WLAN update schema
WLAN_UPDATE_SCHEMA = copy.deepcopy(WLAN_SCHEMA)
WLAN_UPDATE_SCHEMA.pop("required", None)
WLAN_UPDATE_SCHEMA.pop("allOf", None)  # Remove conditional requirement for update
# Make all properties optional for update
for prop in WLAN_UPDATE_SCHEMA.get("properties", {}):
    WLAN_UPDATE_SCHEMA["properties"][prop].pop("default", None)

# Network schema (LAN/VLAN)
NETWORK_SCHEMA = {
    "type": "object",
    "required": ["name", "purpose"],
    "properties": {
        "name": {"type": "string", "description": "Network name"},
        "purpose": {
            "type": "string",
            "enum": ["corporate", "guest", "wan", "vlan-only"],
            "description": "Network purpose/type",
        },
        "vlan_enabled": {
            "type": "boolean",
            "default": False,
            "description": "Whether VLAN is enabled",
        },
        "vlan": {"type": "string", "description": "VLAN ID (if VLAN is enabled)"},
        "ip_subnet": {
            "type": "string",
            "description": (
                "IP subnet in host-address-form CIDR (e.g., '192.168.1.1/24'). "
                "Note: the controller rejects the network-address form "
                "('192.168.1.0/24') with api.err.IncorrectIPSubnetSpec. Optional "
                "for vlan-only purpose; recommended for corporate (the network "
                "won't be functional without it, though the controller doesn't "
                "force-require it on create)."
            ),
        },
        "enabled": {
            "type": "boolean",
            "default": True,
            "description": "Whether the network is enabled",
        },
        "igmp_snooping": {
            "type": "boolean",
            "description": "Enable IGMP snooping to limit multicast flooding to interested ports only",
        },
        "igmp_querier_switches": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["switch_mac"],
                "properties": {
                    "switch_mac": {"type": "string", "description": "MAC address of the switch to act as IGMP querier"},
                    "querier_address": {"type": "string", "description": "Querier IP address (empty for auto)"},
                },
            },
            "description": "List of switches assigned as IGMP queriers for this network",
        },
        "igmp_flood_unknown_multicast": {
            "type": "boolean",
            "description": "Flood unknown multicast traffic to all ports (false = drop unknown multicast)",
        },
        "mdns_enabled": {
            "type": "boolean",
            "description": "Enable mDNS (Bonjour/Avahi) reflection on this network",
        },
        "domain_name": {
            "type": "string",
            "description": "DNS domain name for the network (e.g., 'example.com')",
        },
        "dhcpd_enabled": {
            "type": "boolean",
            "description": "Enable the DHCP server on this network (mutually exclusive with dhcp_relay_enabled — the controller rejects having both true)",
        },
        "dhcpd_start": {
            "type": "string",
            "description": "DHCP range start IP address",
        },
        "dhcpd_stop": {
            "type": "string",
            "description": "DHCP range end IP address",
        },
        "dhcpd_leasetime": {
            "type": "integer",
            "minimum": 60,
            "description": "DHCP lease time in seconds (default 86400 = 24 hours)",
        },
        "dhcpd_gateway": {
            "type": "string",
            "description": "Custom DHCP gateway IP (overrides default gateway)",
        },
        "dhcpd_gateway_enabled": {
            "type": "boolean",
            "description": "Enable custom DHCP gateway (use dhcpd_gateway value instead of default)",
        },
        "dhcpd_dns_1": {
            "type": "string",
            "description": "Primary DNS server IP for DHCP clients",
        },
        "dhcpd_dns_2": {
            "type": "string",
            "description": "Secondary DNS server IP for DHCP clients",
        },
        "dhcpd_dns_enabled": {
            "type": "boolean",
            "description": "Enable custom DNS servers in DHCP (use dhcpd_dns_1/2 instead of default)",
        },
        "dhcpd_ntp_1": {
            "type": "string",
            "description": "Primary NTP server IPv4 address for DHCP clients (controller rejects hostnames)",
        },
        "dhcpd_ntp_2": {
            "type": "string",
            "description": "Secondary NTP server IPv4 address for DHCP clients (controller rejects hostnames)",
        },
        "dhcpd_ntp_enabled": {
            "type": "boolean",
            "description": "Enable NTP server option in DHCP responses",
        },
        "dhcpd_wins_1": {
            "type": "string",
            "description": "Primary WINS server IP for DHCP clients",
        },
        "dhcpd_wins_2": {
            "type": "string",
            "description": "Secondary WINS server IP for DHCP clients",
        },
        "dhcpd_wins_enabled": {
            "type": "boolean",
            "description": "Enable WINS server option in DHCP responses",
        },
        "dhcpd_unifi_controller": {
            "type": "string",
            "description": "UniFi controller IP for DHCP option 43 (device adoption)",
        },
        "dhcpd_tftp_server": {
            "type": "string",
            "description": "TFTP server name/IP for DHCP option 150 (Cisco TFTP server). Independent of PXE boot — see dhcpd_boot_server for PXE",
        },
        "dhcpd_boot_server": {
            "type": "string",
            "description": "PXE boot server IP (BOOTP siaddr). Set together with dhcpd_boot_filename and dhcpd_boot_enabled to enable PXE boot",
        },
        "dhcpd_boot_filename": {
            "type": "string",
            "description": "PXE boot filename served via DHCP option 67 (required when dhcpd_boot_enabled is true)",
        },
        "dhcpd_boot_enabled": {
            "type": "boolean",
            "description": "Enable PXE network boot options in DHCP (requires dhcpd_boot_server and dhcpd_boot_filename)",
        },
        "dhcpd_conflict_checking": {
            "type": "boolean",
            "description": "Enable DHCP conflict checking (ping before assigning IP)",
        },
        "dhcp_relay_enabled": {
            "type": "boolean",
            "description": "Enable DHCP relay instead of local DHCP server (mutually exclusive with dhcpd_enabled — set dhcpd_enabled=false in the same update)",
        },
        "dhcpd_ip_1": {
            "type": "string",
            "description": "Trusted DHCP server IP for DHCP guard (typically the network gateway). Required when dhcpguard_enabled=true — enabling dhcpguard without this returns api.err.MissingIPAddress. Not present in GET responses until set",
        },
        "dhcpguard_enabled": {
            "type": "boolean",
            "description": "Enable DHCP guard (blocks rogue DHCP servers on this network). Requires dhcpd_ip_1 to be set to the trusted DHCP server's IP address in the same update; the controller returns api.err.MissingIPAddress otherwise",
        },
        "network_isolation_enabled": {
            "type": "boolean",
            "description": "Enable network isolation (corporate networks only — blocks inter-VLAN routing)",
        },
        "internet_access_enabled": {
            "type": "boolean",
            "description": "Allow this network to access the internet (WAN)",
        },
        "upnp_lan_enabled": {
            "type": "boolean",
            "description": "Enable UPnP on this network",
        },
    },
    "allOf": [
        {
            "if": {"properties": {"vlan_enabled": {"enum": [True]}}},
            "then": {"required": ["vlan"]},
        },
        {
            # Controller defaults `vlan` to 1 when not supplied for corporate/vlan-only
            # purposes, which collides with the default LAN (api.err.VlanUsed). Force
            # callers to explicitly choose a non-conflicting VLAN. See issue #209.
            "if": {"properties": {"purpose": {"enum": ["corporate", "vlan-only"]}}},
            "then": {
                "required": ["vlan", "vlan_enabled"],
                "properties": {"vlan_enabled": {"enum": [True]}},
            },
        },
    ],
    "additionalProperties": False,
}

# Network update schema
NETWORK_UPDATE_SCHEMA = copy.deepcopy(NETWORK_SCHEMA)
NETWORK_UPDATE_SCHEMA.pop("required", None)
NETWORK_UPDATE_SCHEMA.pop("allOf", None)  # Remove conditional requirement for update
# Make all properties optional for update
for prop in NETWORK_UPDATE_SCHEMA.get("properties", {}):
    NETWORK_UPDATE_SCHEMA["properties"][prop].pop("default", None)

# VPN Client Profile schema
VPN_PROFILE_SCHEMA = {
    "type": "object",
    "required": ["name", "server_id"],
    "properties": {
        "name": {"type": "string", "description": "Name for the VPN client profile"},
        "server_id": {"type": "string", "description": "ID of the VPN server"},
        "exp": {"type": "integer", "default": 365, "description": "Expiration in days"},
    },
    "additionalProperties": False,
}

# FirewallPolicy schema
FIREWALL_POLICY_SCHEMA = {
    "type": "object",
    "required": ["name", "ruleset", "action", "rule_index"],
    "properties": {
        "name": {"type": "string", "description": "Name of the firewall policy"},
        "ruleset": {
            "type": "string",
            "description": "The firewall ruleset (e.g., 'WAN_IN', 'LAN_OUT')",
        },
        "action": {
            "type": "string",
            "enum": ["accept", "drop", "reject"],
            "description": "Policy action",
        },
        "rule_index": {
            "type": "integer",
            "description": "Rule index/order (lower numbers process first)",
        },
        "protocol": {
            "type": "string",
            "enum": ["all", "tcp", "udp", "icmp"],
            "default": "all",
            "description": "Protocol",
        },
        "src_address": {"type": "string", "description": "Source address or CIDR"},
        "dst_address": {"type": "string", "description": "Destination address or CIDR"},
        "src_port": {
            "type": "string",
            "description": "Source port or range (e.g., '80' or '80-443')",
        },
        "dst_port": {
            "type": "string",
            "description": "Destination port or range (e.g., '80' or '80-443')",
        },
        "enabled": {
            "type": "boolean",
            "default": True,
            "description": "Whether the policy is enabled",
        },
        "description": {"type": "string", "description": "Description of the rule"},
        "logging": {
            "type": "boolean",
            "description": "Enable logging for matched traffic",
        },
    },
    "additionalProperties": False,
}

# Firewall Policy update schema
FIREWALL_POLICY_UPDATE_SCHEMA = copy.deepcopy(FIREWALL_POLICY_SCHEMA)
FIREWALL_POLICY_UPDATE_SCHEMA.pop("required", None)
# Make all properties optional for update
for prop in FIREWALL_POLICY_UPDATE_SCHEMA.get("properties", {}):
    FIREWALL_POLICY_UPDATE_SCHEMA["properties"][prop].pop("default", None)

# Firewall Policy Create schema (V2 API specific)
FIREWALL_POLICY_CREATE_SCHEMA = {
    "type": "object",
    "required": ["name", "ruleset", "action", "index"],
    "properties": {
        "name": {
            "type": "string",
            "minLength": 1,
            "description": "Name of the firewall policy.",
            "examples": ["Block Xbox LAN Out"],
        },
        "ruleset": {
            "type": "string",
            "enum": [  # Based on common UniFi rulesets, adjust if needed
                "WAN_IN",
                "WAN_OUT",
                "WAN_LOCAL",
                "LAN_IN",
                "LAN_OUT",
                "LAN_LOCAL",
                "GUEST_IN",
                "GUEST_OUT",
                "GUEST_LOCAL",
                "VPN_IN",
                "VPN_OUT",
                "VPN_LOCAL",
            ],
            "description": "Target firewall ruleset.",
            "examples": ["LAN_OUT"],
        },
        "action": {
            "type": "string",
            "enum": ["accept", "drop", "reject"],
            "description": "Action for matched traffic (must be lowercase).",
            "examples": ["drop"],
        },
        "index": {
            "type": "integer",
            "minimum": 1,
            "description": "Rule priority index (lower numbers execute first). API uses 'index' for V2.",
            "examples": [2010],
        },
        "enabled": {
            "type": "boolean",
            "default": True,
            "description": "Whether the rule is enabled upon creation.",
            "examples": [True],
        },
        "description": {
            "type": "string",
            "default": "",
            "description": "Optional description for the rule.",
            "examples": ["Block specific Xbox device from WAN"],
        },
        "logging": {
            "type": "boolean",
            "default": False,
            "description": "Enable logging for matched traffic.",
            "examples": [True],
        },
        "protocol": {
            "type": "string",
            "default": "all",
            "description": "Network protocol (e.g., 'tcp', 'udp', 'icmp', 'all').",
            "examples": ["all"],
        },
        "connection_state_type": {
            "type": "string",
            "enum": ["inclusive", "exclusive"],
            "default": "inclusive",
            "description": "How connection states are matched.",
            "examples": ["inclusive"],
        },
        "connection_states": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["new", "established", "related", "invalid"],
            },
            "default": [
                "new",
                "established",
                "related",
                "invalid",
            ],  # Default to match all states
            "description": "Connection states to match.",
            "examples": [["new", "established", "related", "invalid"]],
        },
        "source": {  # Structure based on FirewallPolicyEndpoint TypedDict
            "type": "object",
            "required": [
                "match_opposite_ports",
                "matching_target",
                "port_matching_type",
                "zone_id",
            ],
            "properties": {
                "match_opposite_ports": {"type": "boolean", "default": False},
                "matching_target": {
                    "type": "string",
                    "enum": [
                        "zone",
                        "client_macs",
                        "network_id",
                        "ip_group_id",
                        "region",
                    ],
                    "description": "How source is matched.",
                    "examples": ["client_macs"],
                },
                "port_matching_type": {
                    "type": "string",
                    "enum": ["any", "single_port", "port_range"],
                    "default": "any",
                    "description": "How ports are matched.",
                    "examples": ["any"],
                },
                "zone_id": {
                    "type": "string",
                    "description": "Source zone ID (e.g., 'trusted', 'guest', 'iot').",
                    "examples": ["trusted"],
                },
                "client_macs": {
                    "type": "array",
                    "items": {"type": "string", "format": "mac"},
                    "description": "Required if matching_target is 'client_macs'.",
                    "examples": [["4c:3b:df:2c:c8:c6"]],
                },
                "network_id": {
                    "type": "string",
                    "description": "Required if matching_target is 'network_id'.",
                },
                "ip_group_id": {
                    "type": "string",
                    "description": "Required if matching_target is 'ip_group_id'.",
                },
                "port": {
                    "type": "string",
                    "description": "Required if port_matching_type is 'single_port'.",
                },
                "port_range_start": {
                    "type": "string",
                    "description": "Required if port_matching_type is 'port_range'.",
                },
                "port_range_end": {
                    "type": "string",
                    "description": "Required if port_matching_type is 'port_range'.",
                },
                "region": {
                    "type": "string",
                    "description": "Required if matching_target is 'region'.",
                },
            },
            "additionalProperties": True,  # Allow other potential fields
        },
        "destination": {  # Structure based on FirewallPolicyEndpoint TypedDict
            "type": "object",
            "required": [
                "match_opposite_ports",
                "matching_target",
                "port_matching_type",
                "zone_id",
            ],
            "properties": {
                "match_opposite_ports": {"type": "boolean", "default": False},
                "matching_target": {
                    "type": "string",
                    "enum": [
                        "zone",
                        "client_macs",
                        "network_id",
                        "ip_group_id",
                        "region",
                    ],
                    "description": "How destination is matched.",
                    "examples": ["zone"],
                },
                "port_matching_type": {
                    "type": "string",
                    "enum": ["any", "single_port", "port_range"],
                    "default": "any",
                    "description": "How ports are matched.",
                    "examples": ["any"],
                },
                "zone_id": {
                    "type": "string",
                    "description": "Destination zone ID (e.g., 'wan', 'trusted', 'guest').",
                    "examples": ["wan"],
                },
                "client_macs": {
                    "type": "array",
                    "items": {"type": "string", "format": "mac"},
                    "description": "Required if matching_target is 'client_macs'.",
                },
                "network_id": {
                    "type": "string",
                    "description": "Required if matching_target is 'network_id'.",
                },
                "ip_group_id": {
                    "type": "string",
                    "description": "Required if matching_target is 'ip_group_id'.",
                },
                "port": {
                    "type": "string",
                    "description": "Required if port_matching_type is 'single_port'.",
                },
                "port_range_start": {
                    "type": "string",
                    "description": "Required if port_matching_type is 'port_range'.",
                },
                "port_range_end": {
                    "type": "string",
                    "description": "Required if port_matching_type is 'port_range'.",
                },
                "region": {
                    "type": "string",
                    "description": "Required if matching_target is 'region'.",
                },
            },
            "additionalProperties": True,  # Allow other potential fields
        },
        "icmp_typename": {
            "type": "string",
            "description": "ICMP type name (if protocol is 'icmp').",
        },
        "icmp_v6_typename": {
            "type": "string",
            "description": "ICMPv6 type name (if protocol is 'icmpv6').",
        },
        "ip_version": {
            "type": "string",
            "enum": ["ipv4", "ipv6", "both"],
            "default": "ipv4",
            "description": "IP version to apply the rule to.",
            "examples": ["ipv4"],
        },
        "match_ip_sec": {
            "type": "boolean",
            "default": False,
            "description": "Match IPSec traffic.",
            "examples": [False],
        },
        "match_opposite_protocol": {
            "type": "boolean",
            "default": False,
            "description": "Match opposite protocol.",
            "examples": [False],
        },
        "schedule": {  # Placeholder for schedule object - define if needed
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["always", "specific_time", "disabled"],
                },
                "repeat_on_days": {
                    "type": "array",
                    "items": {"type": "string"},
                },  # e.g., ["mon", "tue"]
                "time_all_day": {"type": "boolean"},
                # Add time_start, time_end if needed for specific_time
            },
            "description": "Rule schedule configuration (optional).",
        },
        "create_allow_respond": {
            "type": "boolean",
            "default": False,
            "description": "Whether to create an allow respond rule automatically.",
            "examples": [False],
        },
    },
    "additionalProperties": False,
}

# QoS Rule schema
QOS_RULE_SCHEMA = {
    "type": "object",
    "required": ["name", "interface", "direction", "bandwidth_limit_kbps"],
    "properties": {
        "name": {"type": "string", "description": "Descriptive name for the QoS rule"},
        "interface": {
            "type": "string",
            "description": "Network interface the rule applies to (e.g., 'WAN', 'LAN')",
        },
        "direction": {
            "type": "string",
            "enum": ["upload", "download"],
            "description": "Direction of traffic affected",
        },
        "bandwidth_limit_kbps": {
            "type": "integer",
            "description": "Bandwidth limit in Kilobits per second",
        },
        "target_ip_address": {
            "type": "string",
            "description": "Specific IP address to target",
        },
        "target_subnet": {
            "type": "string",
            "description": "Subnet (CIDR notation) to target",
        },
        "dscp_value": {
            "type": "integer",
            "description": "DSCP value to match/set (0-63)",
            "minimum": 0,
            "maximum": 63,
        },
        "enabled": {
            "type": "boolean",
            "default": True,
            "description": "Whether the rule is enabled",
        },
    },
    # Note: UniFi might have more complex targeting (e.g., MAC address, user group) not covered here yet.
    "additionalProperties": False,
}

# QoS Rule update schema
QOS_RULE_UPDATE_SCHEMA = copy.deepcopy(QOS_RULE_SCHEMA)
QOS_RULE_UPDATE_SCHEMA.pop("required", None)
# Make all properties optional for update
for prop in QOS_RULE_UPDATE_SCHEMA.get("properties", {}):
    QOS_RULE_UPDATE_SCHEMA["properties"][prop].pop("default", None)

# Simplified (high-level) QoS Rule schema used by the LLM-friendly create tool
QOS_RULE_SIMPLE_SCHEMA = {
    "type": "object",
    "required": [
        "name",
        "interface",
        "direction",
        "limit_kbps",
    ],
    "properties": {
        "name": {"type": "string", "description": "User-friendly name of the QoS rule"},
        "interface": {
            "type": "string",
            "description": "Target interface (e.g., 'wan', 'lan', 'wan2') – case-insensitive, accepted as displayed in UniFi UI.",
        },
        "direction": {
            "type": "string",
            "enum": ["upload", "download"],
            "description": "Traffic direction affected",
        },
        "limit_kbps": {
            "type": "integer",
            "minimum": 1,
            "description": "Bandwidth limit in kilobits per second (Kbps)",
        },
        "enabled": {"type": "boolean", "description": "Enable rule (default true)"},
        "dscp_value": {
            "type": "integer",
            "minimum": 0,
            "maximum": 63,
            "description": "Optional DSCP value tag (0-63)",
        },
        "target": {
            "type": "object",
            "required": ["type", "value"],
            "description": "Optional traffic selector. If omitted the rule applies to all clients on the interface.",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["ip", "subnet"],
                    "description": "Selector kind: single IP address or subnet CIDR",
                },
                "value": {
                    "type": "string",
                    "description": "Selector value (e.g., '192.168.1.50' or '192.168.1.0/24')",
                },
            },
        },
    },
    "additionalProperties": False,
}

# ACL Rule validation migrated to pydantic model (models/acl.py) — see #139

# Port Profile update schema
PORT_PROFILE_UPDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Profile name"},
        "forward": {
            "type": "string",
            "enum": ["all", "native", "customize", "disabled"],
            "description": "Forwarding mode",
        },
        "native_networkconf_id": {
            "type": "string",
            "description": "Native network/VLAN ID",
        },
        "voice_networkconf_id": {
            "type": "string",
            "description": "Voice VLAN network ID",
        },
        "isolation": {"type": "boolean", "description": "Port isolation"},
        "poe_mode": {
            "type": "string",
            "enum": ["auto", "off", "pasv24", "passthrough"],
            "description": "PoE mode",
        },
        "stp_port_mode": {"type": "boolean", "description": "STP port mode"},
        "dot1x_ctrl": {
            "type": "string",
            "enum": ["force_authorized", "auto", "force_unauthorized", "mac_based", "multi_host"],
            "description": "802.1X control mode",
        },
    },
    "additionalProperties": False,
}

# Client Group update schema
CLIENT_GROUP_UPDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Group name"},
        "members": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of member MAC addresses",
        },
    },
    "additionalProperties": False,
}

# Content Filter update schema
CONTENT_FILTER_UPDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Profile name"},
        "enabled": {"type": "boolean", "description": "Whether the filter is active"},
        "blocked_categories": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of blocked content categories",
        },
        "safe_search": {
            "type": "array",
            "items": {"type": "string", "enum": ["GOOGLE", "YOUTUBE", "BING"]},
            "description": "Safe search enforcement (valid: GOOGLE, YOUTUBE, BING)",
        },
        "client_macs": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Client MAC addresses this filter applies to",
        },
        "network_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Network IDs this filter applies to",
        },
    },
    "additionalProperties": False,
}

# OON Policy update schema
OON_POLICY_UPDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Policy name"},
        "enabled": {"type": "boolean", "description": "Whether the policy is active"},
        "target_type": {
            "type": "string",
            "enum": ["CLIENTS", "GROUPS"],
            "description": "Target type",
        },
        "targets": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Target MAC addresses or group IDs",
        },
        "secure": {
            "type": "object",
            "description": "Internet access and app blocking configuration",
        },
        "qos": {"type": "object", "description": "Bandwidth limiting configuration"},
        "route": {"type": "object", "description": "VPN routing configuration"},
    },
    "additionalProperties": False,
}

# AP Group create schema
AP_GROUP_SCHEMA = {
    "type": "object",
    "required": ["name"],
    "properties": {
        "name": {"type": "string", "description": "AP group name"},
        "device_macs": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of AP MAC addresses to include in this group",
        },
        "wlan_group_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of WLAN group IDs to assign to this AP group",
        },
    },
    "additionalProperties": False,
}

# AP Group update schema
AP_GROUP_UPDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "AP group name"},
        "device_macs": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of AP MAC addresses to include in this group",
        },
        "wlan_group_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of WLAN group IDs to assign to this AP group",
        },
    },
    "additionalProperties": False,
}

# Simplified (high-level) Firewall Policy schema used by the LLM-friendly create tool
FIREWALL_POLICY_SIMPLE_SCHEMA = {
    "type": "object",
    "required": [
        "name",
        "ruleset",
        "action",
        "src",
        "dst",
    ],
    "properties": {
        "name": {"type": "string", "description": "User-friendly name of the policy"},
        "ruleset": {
            "type": "string",
            "enum": [
                "WAN_IN",
                "WAN_OUT",
                "WAN_LOCAL",
                "LAN_IN",
                "LAN_OUT",
                "LAN_LOCAL",
                "GUEST_IN",
                "GUEST_OUT",
                "GUEST_LOCAL",
                "VPN_IN",
                "VPN_OUT",
                "VPN_LOCAL",
            ],
            "description": "Target firewall ruleset",
        },
        "action": {
            "type": "string",
            "enum": ["accept", "drop", "reject"],
            "description": "Policy action",
        },
        "src": {
            "type": "object",
            "required": ["type", "value"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["zone", "network", "client_mac", "ip_group"],
                    "description": "Selector type for source",
                },
                "value": {
                    "type": "string",
                    "description": "Selector value (name, id, MAC, etc.)",
                },
            },
        },
        "dst": {
            "type": "object",
            "required": ["type", "value"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["zone", "network", "client_mac", "ip_group"],
                    "description": "Selector type for destination",
                },
                "value": {
                    "type": "string",
                    "description": "Selector value (name, id, MAC, etc.)",
                },
            },
        },
        "index": {"type": "integer", "description": "Priority index (optional)"},
        "enabled": {"type": "boolean", "description": "Enable rule (default true)"},
        "log": {"type": "boolean", "description": "Enable logging (default false)"},
        "protocol": {
            "type": "string",
            "enum": ["all", "tcp", "udp", "icmp"],
            "default": "all",
        },
    },
    "additionalProperties": False,
}

# Simplified (high-level) Port Forward schema used by the LLM-friendly create tool
PORT_FORWARD_SIMPLE_SCHEMA = {
    "type": "object",
    "required": [
        "name",
        "ext_port",
        "to_ip",
    ],
    "properties": {
        "name": {
            "type": "string",
            "description": "User-friendly name of the port forward rule",
        },
        "ext_port": {
            "type": "string",
            "description": "External (destination) port or range, e.g. '80' or '10000-10010'",
        },
        "to_ip": {
            "type": "string",
            "description": "Internal IP address to forward traffic to",
        },
        "int_port": {
            "type": "string",
            "description": "Internal port to forward to (defaults to ext_port if omitted)",
        },
        "protocol": {
            "type": "string",
            "enum": ["tcp", "udp", "both"],
            "description": "Protocol to match (default both)",
        },
        "enabled": {"type": "boolean", "description": "Enable rule (default true)"},
    },
    "additionalProperties": False,
}


# V2 Zone-Based Firewall Policy Create schema
# The v2 API uses zone_id + matching_target + matching_target_type instead of rulesets.
# Actions are uppercase: ALLOW, BLOCK, REJECT.
# See: /proxy/network/v2/api/site/{site}/firewall-policies
# Property definitions shared between V2 create and update schemas.
# Defining them once eliminates the drift hazard that produced issue #203
# (and the connection_state_type/connection_states siblings discovered in its
# audit). Update schema strips defaults — partial-update merge with defaults
# baked in would clobber existing controller values.
_FIREWALL_POLICY_V2_PROPERTIES = {
    "name": {
        "type": "string",
        "minLength": 1,
        "description": "Name of the firewall policy.",
    },
    "action": {
        "type": "string",
        "enum": ["ALLOW", "BLOCK", "REJECT"],
        "description": "Policy action (uppercase v2 format).",
    },
    "enabled": {
        "type": "boolean",
        "default": True,
        "description": "Whether the policy is active.",
    },
    "index": {
        "type": "integer",
        "description": "Rule priority/order (lower = evaluated first). API assigns based on creation order.",
    },
    "protocol": {
        "type": "string",
        "default": "all",
        "description": "Protocol to match (e.g. 'all', 'tcp', 'udp', 'icmp').",
    },
    "ip_version": {
        "type": "string",
        "enum": ["BOTH", "IPV4", "IPV6"],
        "default": "BOTH",
        "description": "IP version to match. Controller requires all-uppercase; mixed-case input is normalized.",
    },
    "logging": {
        "type": "boolean",
        "default": False,
        "description": "Enable logging for matched traffic.",
    },
    "connection_state_type": {
        "type": "string",
        "enum": ["ALL", "RESPOND_ONLY", "CUSTOM"],
        "default": "ALL",
        "description": (
            "Connection state matching mode. ALL = match every state. "
            "RESPOND_ONLY = match only return traffic. CUSTOM = match the "
            "states listed in connection_states. Mixed-case input is normalized."
        ),
    },
    "connection_states": {
        "type": "array",
        "items": {
            "type": "string",
            "enum": ["NEW", "RELATED", "INVALID", "ESTABLISHED"],
        },
        "description": (
            "Connection states to match when connection_state_type='CUSTOM'. "
            "Mixed-case input is normalized."
        ),
    },
    "create_allow_respond": {
        "type": "boolean",
        "default": False,
        "description": "Auto-create return traffic rule for ALLOW policies.",
    },
    "match_ip_sec": {
        "type": "boolean",
        "default": False,
        "description": "Match IPSec traffic.",
    },
    "match_opposite_protocol": {
        "type": "boolean",
        "default": False,
        "description": "Match opposite protocol.",
    },
    "icmp_typename": {
        "type": "string",
        "default": "ANY",
        "description": "ICMP type name.",
    },
    "icmp_v6_typename": {
        "type": "string",
        "default": "ANY",
        "description": "ICMPv6 type name.",
    },
    "schedule": {
        "type": "object",
        "default": {"mode": "ALWAYS"},
        "description": 'Schedule object (e.g. {"mode": "ALWAYS"}).',
    },
    "source": {
        "type": "object",
        "description": (
            "Source targeting. Must include zone_id and matching_target. "
            "For IP targeting: matching_target='IP', matching_target_type='SPECIFIC', ips=[...]. "
            "For network targeting: matching_target='NETWORK', matching_target_type='OBJECT', network_ids=[...]. "
            "For any: matching_target='ANY'."
        ),
    },
    "destination": {
        "type": "object",
        "description": (
            "Destination targeting. Same structure as source. "
            "For IP targeting: matching_target='IP', matching_target_type='SPECIFIC', ips=[...]. "
            "For network targeting: matching_target='NETWORK', matching_target_type='OBJECT', network_ids=[...]. "
            "For any: matching_target='ANY'."
        ),
    },
}


def _strip_defaults(properties: dict) -> dict:
    """Return a copy of ``properties`` with the ``default`` key removed.

    Update schemas must not carry defaults: partial-update merge would clobber
    existing controller values with a default the caller never explicitly set
    (see field-symmetry skill, Gotcha 1: shared validator defaults are forbidden).
    """
    return {name: {k: v for k, v in spec.items() if k != "default"} for name, spec in properties.items()}


FIREWALL_POLICY_V2_CREATE_SCHEMA = {
    "type": "object",
    "required": ["name", "action", "source", "destination"],
    "properties": _FIREWALL_POLICY_V2_PROPERTIES,
    "additionalProperties": False,
}


FIREWALL_POLICY_V2_UPDATE_SCHEMA = {
    "type": "object",
    "properties": _strip_defaults(_FIREWALL_POLICY_V2_PROPERTIES),
    "additionalProperties": False,
}


# Device Radio Update schema
DEVICE_RADIO_UPDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "tx_power_mode": {
            "type": "string",
            "enum": ["auto", "high", "medium", "low", "custom"],
            "description": "Transmit power mode",
        },
        "tx_power": {
            "type": "integer",
            "minimum": 1,
            "maximum": 30,
            "description": "Custom TX power in dBm (only used when tx_power_mode is 'custom')",
        },
        "channel": {
            "type": "integer",
            "minimum": 0,
            "description": "Channel number (0 for auto)",
        },
        "ht": {
            "type": "string",
            "enum": ["20", "40", "80", "160", "320"],
            "description": "Channel width (HT20/HT40/HT80/HT160/EHT320)",
        },
        "min_rssi_enabled": {
            "type": "boolean",
            "description": "Enable minimum RSSI client filtering",
        },
        "min_rssi": {
            "type": "integer",
            "minimum": -95,
            "maximum": -20,
            "description": "Minimum RSSI threshold in dBm (e.g. -70). Clients below this are disconnected.",
        },
        "assisted_roaming_enabled": {
            "type": "boolean",
            "description": "Enable 802.11k/v assisted roaming (neighbor reports and BSS transition management)",
        },
        "antenna_gain": {
            "type": "integer",
            "minimum": 0,
            "maximum": 30,
            "description": "External antenna gain in dBi for regulatory TX power compensation",
        },
        "vwire_enabled": {
            "type": "boolean",
            "description": "Enable virtual wire mode (transparent bridge for meshed APs)",
        },
        "sens_level_enabled": {
            "type": "boolean",
            "description": "Enable receive sensitivity level adjustment",
        },
        "sens_level": {
            "type": "integer",
            "minimum": -95,
            "maximum": -20,
            "description": "Receive sensitivity level in dBm (e.g. -70)",
        },
    },
    "additionalProperties": False,
}


SNMP_SETTINGS_UPDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "enabled": {
            "type": "boolean",
            "description": "Enable or disable SNMP on the site",
        },
        "community": {
            "type": "string",
            "description": "SNMP community string (e.g., 'public')",
        },
    },
    "additionalProperties": False,
}

AUTOBACKUP_SETTINGS_UPDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "autobackup_enabled": {
            "type": "boolean",
            "description": "Enable or disable automatic backups",
        },
        "autobackup_cron_expr": {
            "type": "string",
            "description": "Cron expression for backup schedule (e.g., '30 2 * * *' for daily at 2:30 AM)",
        },
        "autobackup_days": {
            "type": "integer",
            "minimum": 0,
            "description": "Backup retention in days (0 = use max_files instead)",
        },
        "autobackup_max_files": {
            "type": "integer",
            "minimum": 1,
            "description": "Maximum number of backup files to keep",
        },
        "autobackup_timezone": {
            "type": "string",
            "description": "Timezone for backup schedule (e.g., 'America/Denver')",
        },
        "autobackup_cloud_enabled": {
            "type": "boolean",
            "description": "Enable cloud backup storage",
        },
    },
    "additionalProperties": False,
}

DNS_RECORD_SCHEMA = {
    "type": "object",
    "required": ["key", "value", "record_type"],
    "properties": {
        "key": {
            "type": "string",
            "description": "Hostname / record name (e.g., 'myhost.example.com')",
        },
        "value": {
            "type": "string",
            "description": "Record value — IP address for A/AAAA, hostname for CNAME, mail server for MX, text for TXT",
        },
        "record_type": {
            "type": "string",
            "enum": ["A", "AAAA", "CNAME", "MX", "TXT", "SRV"],
            "description": "DNS record type",
        },
        "enabled": {
            "type": "boolean",
            "description": "Whether the record is active",
        },
        "ttl": {
            "type": "integer",
            "minimum": 0,
            "description": "Time to live in seconds (0 = default 300s)",
        },
        "port": {
            "type": "integer",
            "minimum": 0,
            "description": "Port number (for SRV records)",
        },
        "priority": {
            "type": "integer",
            "minimum": 0,
            "description": "Priority (for MX and SRV records, lower = higher priority)",
        },
        "weight": {
            "type": "integer",
            "minimum": 0,
            "description": "Weight (for SRV records)",
        },
    },
    "additionalProperties": False,
}

DNS_RECORD_UPDATE_SCHEMA = copy.deepcopy(DNS_RECORD_SCHEMA)
DNS_RECORD_UPDATE_SCHEMA.pop("required", None)


class UniFiResourceRegistry:
    """Registry for UniFi Network resource schemas and validators."""

    _schemas = {
        "port_forward": PORT_FORWARD_SCHEMA,
        "port_forward_update": PORT_FORWARD_UPDATE_SCHEMA,
        "traffic_route": TRAFFIC_ROUTE_SCHEMA,
        "traffic_route_update": TRAFFIC_ROUTE_UPDATE_SCHEMA,
        "traffic_route_simple": TRAFFIC_ROUTE_SIMPLE_SCHEMA,
        "wlan": WLAN_SCHEMA,
        "wlan_update": WLAN_UPDATE_SCHEMA,
        "network": NETWORK_SCHEMA,
        "network_update": NETWORK_UPDATE_SCHEMA,
        "vpn_profile": VPN_PROFILE_SCHEMA,
        "firewall_policy": FIREWALL_POLICY_SCHEMA,
        "firewall_policy_update": FIREWALL_POLICY_UPDATE_SCHEMA,
        "firewall_policy_create": FIREWALL_POLICY_CREATE_SCHEMA,
        "qos_rule": QOS_RULE_SCHEMA,
        "qos_rule_update": QOS_RULE_UPDATE_SCHEMA,
        "firewall_policy_simple": FIREWALL_POLICY_SIMPLE_SCHEMA,
        "qos_rule_simple": QOS_RULE_SIMPLE_SCHEMA,
        "port_forward_simple": PORT_FORWARD_SIMPLE_SCHEMA,
        "device_radio_update": DEVICE_RADIO_UPDATE_SCHEMA,
        "snmp_settings_update": SNMP_SETTINGS_UPDATE_SCHEMA,
        "autobackup_settings_update": AUTOBACKUP_SETTINGS_UPDATE_SCHEMA,
        "dns_record": DNS_RECORD_SCHEMA,
        "dns_record_update": DNS_RECORD_UPDATE_SCHEMA,
        "firewall_policy_v2_create": FIREWALL_POLICY_V2_CREATE_SCHEMA,
    }

    @classmethod
    def get_schema(cls, resource_type: str) -> Dict[str, Any]:
        """Get JSON schema for a resource type."""
        return cls._schemas.get(resource_type, {})
