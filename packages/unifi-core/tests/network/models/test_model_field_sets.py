"""Shared field-set invariants, with explicit cases for each Network model."""

import pytest
from unifi_core.network.models import (
    ap_group,
    client_group,
    clients,
    content_filter,
    devices,
    dns,
    dynamic_dns,
    firewall,
    gateway_settings,
    nat,
    networks,
    oon,
    port_forwards,
    qos,
    route,
    switch,
    system,
    traffic_routes,
    vpn,
    wlans,
)


@pytest.mark.parametrize(
    "fields, expected",
    [
        (ap_group.MUTABLE_FIELDS, ("name", "device_macs", "wlan_group_ids")),
        (ap_group.READ_ONLY_FIELDS, ("id", "ap_count")),
        (client_group.MUTABLE_FIELDS, ("name", "members")),
        (client_group.READ_ONLY_FIELDS, ("id", "group_type")),
        (clients.Client.model_fields, ("name", "hostname")),
        (
            content_filter.MUTABLE_FIELDS,
            ("name", "enabled", "blocked_categories", "safe_search", "client_macs", "network_ids", "schedule_mode"),
        ),
        (content_filter.READ_ONLY_FIELDS, ("id", "profile")),
        (devices.DEVICE_MUTABLE_FIELDS, ("name",)),
        (devices.DEVICE_READ_ONLY_FIELDS, ("mac",)),
        (
            devices.DEVICERADIO_MUTABLE_FIELDS,
            (
                "tx_power_mode",
                "tx_power",
                "channel",
                "ht",
                "min_rssi_enabled",
                "min_rssi",
                "assisted_roaming_enabled",
                "antenna_gain",
                "vwire_enabled",
                "sens_level_enabled",
                "sens_level",
            ),
        ),
        (devices.DEVICERADIO_READ_ONLY_FIELDS, ("radio",)),
        (dns.MUTABLE_FIELDS, ("key", "value", "record_type", "enabled", "ttl", "port", "priority", "weight")),
        (dns.READ_ONLY_FIELDS, ("id",)),
        (
            dynamic_dns.MUTABLE_FIELDS,
            ("host_name", "service", "server", "login", "x_password", "interface", "custom_service", "options"),
        ),
        (dynamic_dns.READ_ONLY_FIELDS, ("id", "site_id")),
        (firewall.READ_ONLY_FIELDS, ("id", "predefined")),
        (firewall.FIREWALLGROUP_MUTABLE_FIELDS, ("name", "group_type", "members")),
        (firewall.FIREWALLGROUP_READ_ONLY_FIELDS, ("id",)),
        (
            gateway_settings.MUTABLE_FIELDS,
            (
                "upnp_enabled",
                "geo_ip_filtering_enabled",
                "tcp_established_timeout",
                "dns_verification",
                "echo_server",
                "unbind_wan_monitors",
            ),
        ),
        (
            nat.MUTABLE_FIELDS,
            (
                "type",
                "description",
                "enabled",
                "rule_index",
                "protocol",
                "ip_version",
                "in_interface",
                "out_interface",
                "ip_address",
                "port",
                "logging",
                "exclude",
                "pppoe_use_base_interface",
                "source_filter",
                "destination_filter",
            ),
        ),
        (networks.MUTABLE_FIELDS, ("name", "purpose", "enabled", "vlan_enabled", "vlan", "ip_subnet")),
        (networks.MUTABLE_FIELDS, ("dhcpd_enabled", "dhcpd_start", "dhcpd_stop", "dhcpd_leasetime")),
        (networks.MUTABLE_FIELDS, ("igmp_snooping", "igmp_flood_unknown_multicast")),
        (
            networks.MUTABLE_FIELDS,
            (
                "wan_type",
                "wan_networkgroup",
                "wan_dns_preference",
                "wan_dns1",
                "wan_dns2",
                "wan_load_balance_type",
                "wan_load_balance_weight",
                "wan_failover_priority",
                "wan_sla",
                "report_wan_event",
                "wan_smartq_enabled",
                "wan_vlan_enabled",
                "igmp_proxy_upstream",
                "igmp_proxy_for",
                "mac_override_enabled",
                "wan_ip_aliases",
            ),
        ),
        (networks.MUTABLE_FIELDS, ("firewall_zone_id",)),
        (
            networks.MUTABLE_FIELDS,
            (
                "ipv6_enabled",
                "wan_type_v6",
                "ipv6_setting_preference",
                "ipv6_wan_delegation_type",
                "wan_dhcpv6_pd_size",
                "wan_dhcpv6_pd_size_auto",
                "wan_ipv6_dns_preference",
                "wan_ipv6_dns1",
                "wan_ipv6_dns2",
            ),
        ),
        (networks.READ_ONLY_FIELDS, ("id", "site_id")),
        (oon.READ_ONLY_FIELDS, ("id", "restriction_level")),
        (
            port_forwards.MUTABLE_FIELDS,
            ("name", "enabled", "fwd_protocol", "dst_port", "destination_ip", "fwd_port", "fwd_ip", "src", "log"),
        ),
        (port_forwards.READ_ONLY_FIELDS, ("id", "site_id")),
        (
            qos.MUTABLE_FIELDS,
            (
                "name",
                "enabled",
                "interface",
                "direction",
                "bandwidth_limit_kbps",
                "dscp_value",
                "rate_max_down",
                "rate_max_up",
                "priority",
            ),
        ),
        (qos.READ_ONLY_FIELDS, ("id", "site_id")),
        (
            switch.MUTABLE_FIELDS,
            (
                "name",
                "forward",
                "native_networkconf_id",
                "tagged_networkconf_ids",
                "voice_networkconf_id",
                "isolation",
                "poe_mode",
                "stp_port_mode",
                "dot1x_ctrl",
            ),
        ),
        (switch.READ_ONLY_FIELDS, ("id", "attr_no_delete")),
        (system.SNMPSETTINGS_MUTABLE_FIELDS, ("enabled", "community")),
        (system.SNMPSETTINGS_READ_ONLY_FIELDS, ("port", "version")),
        (
            system.AUTOBACKUPSETTINGS_MUTABLE_FIELDS,
            (
                "autobackup_enabled",
                "autobackup_cron_expr",
                "autobackup_days",
                "autobackup_max_files",
                "autobackup_timezone",
                "autobackup_cloud_enabled",
            ),
        ),
        (
            traffic_routes.MUTABLE_FIELDS,
            ("name", "matching_target", "network_id", "enabled", "kill_switch_enabled", "next_hop"),
        ),
        (traffic_routes.READ_ONLY_FIELDS, ("id",)),
        (vpn.VPNCLIENT_MUTABLE_FIELDS, ("name", "enabled", "type", "server_address")),
        (vpn.VPNCLIENT_READ_ONLY_FIELDS, ("id",)),
        (wlans.READ_ONLY_FIELDS, ("id", "site_id")),
    ],
)
def test_includes(fields, expected):
    for field in expected:
        assert field in fields


@pytest.mark.parametrize(
    "fields, expected",
    [
        (ap_group.MUTABLE_FIELDS, ("id", "ap_count")),
        (client_group.MUTABLE_FIELDS, ("id", "group_type")),
        (content_filter.MUTABLE_FIELDS, ("id", "profile")),
        (devices.DEVICE_MUTABLE_FIELDS, ("mac", "model", "type", "version", "uptime", "state", "ip")),
        (devices.DEVICERADIO_MUTABLE_FIELDS, ("radio",)),
        (dns.MUTABLE_FIELDS, ("id",)),
        (dynamic_dns.MUTABLE_FIELDS, ("id", "site_id")),
        (firewall.MUTABLE_FIELDS, ("id", "predefined")),
        (gateway_settings.MUTABLE_FIELDS, ("id", "site_id", "key")),
        (networks.MUTABLE_FIELDS, ("id", "site_id")),
        (oon.MUTABLE_FIELDS, ("id", "restriction_level")),
        (port_forwards.MUTABLE_FIELDS, ("id", "site_id")),
        (qos.MUTABLE_FIELDS, ("id", "site_id")),
        (switch.MUTABLE_FIELDS, ("id", "attr_no_delete")),
        (system.SNMPSETTINGS_MUTABLE_FIELDS, ("port", "version")),
        (traffic_routes.MUTABLE_FIELDS, ("id",)),
        (vpn.VPNCLIENT_MUTABLE_FIELDS, ("id",)),
        (wlans.MUTABLE_FIELDS, ("id", "site_id")),
    ],
)
def test_excludes(fields, expected):
    for field in expected:
        assert field not in fields


@pytest.mark.parametrize(
    "mutable, read_only",
    [
        (ap_group.MUTABLE_FIELDS, ap_group.READ_ONLY_FIELDS),
        (client_group.MUTABLE_FIELDS, client_group.READ_ONLY_FIELDS),
        (client_group.USERGROUP_MUTABLE_FIELDS, client_group.USERGROUP_READ_ONLY_FIELDS),
        (content_filter.MUTABLE_FIELDS, content_filter.READ_ONLY_FIELDS),
        (devices.DEVICE_MUTABLE_FIELDS, devices.DEVICE_READ_ONLY_FIELDS),
        (devices.DEVICERADIO_MUTABLE_FIELDS, devices.DEVICERADIO_READ_ONLY_FIELDS),
        (dns.MUTABLE_FIELDS, dns.READ_ONLY_FIELDS),
        (dynamic_dns.MUTABLE_FIELDS, dynamic_dns.READ_ONLY_FIELDS),
        (firewall.MUTABLE_FIELDS, firewall.READ_ONLY_FIELDS),
        (firewall.FIREWALLGROUP_MUTABLE_FIELDS, firewall.FIREWALLGROUP_READ_ONLY_FIELDS),
        (networks.MUTABLE_FIELDS, networks.READ_ONLY_FIELDS),
        (oon.MUTABLE_FIELDS, oon.READ_ONLY_FIELDS),
        (port_forwards.MUTABLE_FIELDS, port_forwards.READ_ONLY_FIELDS),
        (qos.MUTABLE_FIELDS, qos.READ_ONLY_FIELDS),
        (route.ROUTE_MUTABLE_FIELDS, route.ROUTE_READ_ONLY_FIELDS),
        (route.ACTIVEROUTE_MUTABLE_FIELDS, route.ACTIVEROUTE_READ_ONLY_FIELDS),
        (switch.MUTABLE_FIELDS, switch.READ_ONLY_FIELDS),
        (system.SNMPSETTINGS_MUTABLE_FIELDS, system.SNMPSETTINGS_READ_ONLY_FIELDS),
        (traffic_routes.MUTABLE_FIELDS, traffic_routes.READ_ONLY_FIELDS),
        (vpn.VPNCLIENT_MUTABLE_FIELDS, vpn.VPNCLIENT_READ_ONLY_FIELDS),
        (wlans.MUTABLE_FIELDS, wlans.READ_ONLY_FIELDS),
    ],
)
def test_disjoint(mutable, read_only):
    assert not mutable & read_only


@pytest.mark.parametrize(
    "mutable, read_only, model_fields",
    [
        (ap_group.MUTABLE_FIELDS, ap_group.READ_ONLY_FIELDS, frozenset(ap_group.ApGroup.model_fields.keys())),
        (
            client_group.MUTABLE_FIELDS,
            client_group.READ_ONLY_FIELDS,
            frozenset(client_group.ClientGroup.model_fields.keys()),
        ),
        (
            content_filter.MUTABLE_FIELDS,
            content_filter.READ_ONLY_FIELDS,
            frozenset(content_filter.ContentFilter.model_fields.keys()),
        ),
        (devices.DEVICE_MUTABLE_FIELDS, devices.DEVICE_READ_ONLY_FIELDS, frozenset(devices.Device.model_fields.keys())),
        (
            devices.DEVICERADIO_MUTABLE_FIELDS,
            devices.DEVICERADIO_READ_ONLY_FIELDS,
            frozenset(devices.DeviceRadio.model_fields.keys()),
        ),
        (dns.MUTABLE_FIELDS, dns.READ_ONLY_FIELDS, frozenset(dns.DnsRecord.model_fields.keys())),
        (
            dynamic_dns.MUTABLE_FIELDS,
            dynamic_dns.READ_ONLY_FIELDS,
            frozenset(dynamic_dns.DynamicDns.model_fields.keys()),
        ),
        (firewall.MUTABLE_FIELDS, firewall.READ_ONLY_FIELDS, frozenset(firewall.FirewallRule.model_fields.keys())),
        (
            firewall.FIREWALLGROUP_MUTABLE_FIELDS,
            firewall.FIREWALLGROUP_READ_ONLY_FIELDS,
            frozenset(firewall.FirewallGroup.model_fields.keys()),
        ),
        (networks.MUTABLE_FIELDS, networks.READ_ONLY_FIELDS, frozenset(networks.Network.model_fields.keys())),
        (oon.MUTABLE_FIELDS, oon.READ_ONLY_FIELDS, frozenset(oon.OonPolicy.model_fields.keys())),
        (
            port_forwards.MUTABLE_FIELDS,
            port_forwards.READ_ONLY_FIELDS,
            frozenset(port_forwards.PortForward.model_fields.keys()),
        ),
        (qos.MUTABLE_FIELDS, qos.READ_ONLY_FIELDS, frozenset(qos.QosRule.model_fields.keys())),
        (switch.MUTABLE_FIELDS, switch.READ_ONLY_FIELDS, frozenset(switch.PortProfile.model_fields.keys())),
        (
            system.SNMPSETTINGS_MUTABLE_FIELDS,
            system.SNMPSETTINGS_READ_ONLY_FIELDS,
            frozenset(system.SnmpSettings.model_fields.keys()),
        ),
        (
            system.AUTOBACKUPSETTINGS_MUTABLE_FIELDS,
            system.AUTOBACKUPSETTINGS_READ_ONLY_FIELDS,
            frozenset(system.AutoBackupSettings.model_fields.keys()),
        ),
        (vpn.VPNCLIENT_MUTABLE_FIELDS, vpn.VPNCLIENT_READ_ONLY_FIELDS, frozenset(vpn.VpnClient.model_fields.keys())),
        (wlans.MUTABLE_FIELDS, wlans.READ_ONLY_FIELDS, frozenset(wlans.Wlan.model_fields.keys())),
    ],
)
def test_partition(mutable, read_only, model_fields):
    assert mutable | read_only == model_fields


@pytest.mark.parametrize(
    "read_only, model_fields",
    [
        (client_group.USERGROUP_READ_ONLY_FIELDS, frozenset(client_group.UserGroup.model_fields.keys())),
        (clients.CLIENT_READ_ONLY_FIELDS, frozenset(clients.Client.model_fields.keys())),
        (route.ROUTE_READ_ONLY_FIELDS, frozenset(route.Route.model_fields.keys())),
        (route.ACTIVEROUTE_READ_ONLY_FIELDS, frozenset(route.ActiveRoute.model_fields.keys())),
    ],
)
def test_read_only(read_only, model_fields):
    assert read_only == model_fields
