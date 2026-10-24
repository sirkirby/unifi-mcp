"""Shared write-filter examples for Network models, retaining every original input."""

import pytest
from unifi_core.network.models import (
    ap_group,
    client_group,
    content_filter,
    devices,
    dns,
    dynamic_dns,
    firewall,
    gateway_settings,
    networks,
    oon,
    port_forwards,
    qos,
    switch,
    system,
    traffic_routes,
    vpn,
)

from .model_assertions import assert_fields


@pytest.mark.parametrize(
    "convert, fields, absent",
    [
        (
            ap_group.to_controller_create,
            ap_group.ApGroup(id="should-not-appear", name="Test", ap_count=5),
            ("id", "ap_count"),
        ),
        (
            dns.to_controller_create,
            dns.DnsRecord(id="should-not-appear", key="test.local", value="1.2.3.4", record_type="A"),
            ("id",),
        ),
        (
            dynamic_dns.to_controller_create,
            dynamic_dns.DynamicDns(
                id="should-not-appear", site_id="nope", host_name="home.example.com", service="dyndns"
            ),
            ("id", "site_id"),
        ),
        (
            networks.to_controller_create,
            networks.Network(id="should-not-appear", site_id="also-not", name="Test"),
            ("id", "site_id"),
        ),
        (oon.to_controller_create, oon.OonPolicy(id="should-not-appear", name="Test"), ("id", "restriction_level")),
        (
            port_forwards.to_controller_create,
            port_forwards.PortForward(id="should-not-appear", site_id="site", name="Test"),
            ("id", "site_id"),
        ),
        (qos.to_controller_create, qos.QosRule(id="should-not-appear", site_id="site", name="Test"), ("id", "site_id")),
        (
            switch.to_controller_create,
            switch.PortProfile(id="should-not-appear", attr_no_delete=True, name="Test"),
            ("id", "attr_no_delete"),
        ),
    ],
)
def test_create_read_only_fields(convert, fields, absent):
    result = convert(fields)
    for key in absent:
        assert key not in result


@pytest.mark.parametrize(
    "convert, fields, expected, absent",
    [
        (ap_group.to_controller_update, {"id": "ignore-me", "name": "New Name"}, {"name": "New Name"}, ("id",)),
        (ap_group.to_controller_update, {"ap_count": 5, "name": "Test"}, {}, ("ap_count",)),
        (client_group.to_controller_update, {"id": "ignore-me", "name": "New Name"}, {"name": "New Name"}, ("id",)),
        (client_group.to_controller_update, {"group_type": "CLIENTS", "name": "Test"}, {}, ("group_type",)),
        (dns.to_controller_update, {"id": "ignore-me", "key": "new.local"}, {"key": "new.local"}, ("id",)),
        (
            dynamic_dns.to_controller_update,
            {"id": "ignore", "site_id": "ignore", "service": "noip"},
            {"service": "noip"},
            ("id", "site_id"),
        ),
        (firewall.to_controller_update, {"id": "ignore-me", "name": "New Name"}, {"name": "New Name"}, ("id",)),
        (firewall.to_controller_update, {"predefined": True, "name": "Test"}, {}, ("predefined",)),
        (port_forwards.to_controller_update, {"id": "ignore-me", "name": "New Name"}, {"name": "New Name"}, ("id",)),
        (switch.to_controller_update, {"id": "ignore-me", "name": "New Name"}, {"name": "New Name"}, ("id",)),
        (traffic_routes.to_controller_update, {"id": "ignore-me", "enabled": True}, {"enabled": True}, ("id",)),
    ],
)
def test_update_read_only_fields(convert, fields, expected, absent):
    result = convert(fields)
    assert_fields(result, expected)
    for key in absent:
        assert key not in result


@pytest.mark.parametrize(
    "convert, fields, expected, absent",
    [
        (
            ap_group.to_controller_update,
            {"name": None, "device_macs": ["aa:bb:cc:dd:ee:ff"]},
            {"device_macs": ["aa:bb:cc:dd:ee:ff"]},
            ("name",),
        ),
        (
            client_group.to_controller_update,
            {"name": None, "members": ["aa:bb:cc:dd:ee:ff"]},
            {"members": ["aa:bb:cc:dd:ee:ff"]},
            ("name",),
        ),
        (dns.to_controller_update, {"key": None, "value": "1.2.3.4"}, {"value": "1.2.3.4"}, ("key",)),
        (
            dynamic_dns.to_controller_update,
            {"service": None, "host_name": "home.example.com"},
            {"host_name": "home.example.com"},
            ("service",),
        ),
        (firewall.to_controller_update, {"name": None, "action": "ALLOW"}, {"action": "ALLOW"}, ("name",)),
        (port_forwards.to_controller_update, {"name": None, "enabled": True}, {"enabled": True}, ("name",)),
        (switch.to_controller_update, {"name": None, "forward": "all"}, {"forward": "all"}, ("name",)),
        (
            system.snmp_to_controller_update,
            {"enabled": None, "community": "public"},
            {"community": "public"},
            ("enabled",),
        ),
        (
            system.autobackup_to_controller_update,
            {"autobackup_enabled": None, "autobackup_days": 7},
            {"autobackup_days": 7},
            ("autobackup_enabled",),
        ),
        (
            traffic_routes.to_controller_update,
            {"enabled": None, "kill_switch_enabled": False},
            {"kill_switch_enabled": False},
            ("enabled",),
        ),
    ],
)
def test_update_none_fields(convert, fields, expected, absent):
    result = convert(fields)
    assert_fields(result, expected)
    for key in absent:
        assert key not in result


@pytest.mark.parametrize(
    "convert, fields, expected, absent",
    [
        (ap_group.to_controller_update, {"unknown": "value", "name": "Valid"}, {"name": "Valid"}, ("unknown",)),
        (client_group.to_controller_update, {"unknown": "value", "name": "Valid"}, {"name": "Valid"}, ("unknown",)),
        (devices.to_controller_update, {"unknown": "value", "name": "Valid"}, {"name": "Valid"}, ("unknown",)),
        (dns.to_controller_update, {"unknown": "value", "key": "test.local"}, {"key": "test.local"}, ("unknown",)),
        (firewall.to_controller_update, {"ruleset": "WAN_IN", "name": "Valid"}, {"name": "Valid"}, ("ruleset",)),
        (port_forwards.to_controller_update, {"unknown": "value", "name": "Valid"}, {"name": "Valid"}, ("unknown",)),
        (switch.to_controller_update, {"unknown": "value", "name": "Valid"}, {"name": "Valid"}, ("unknown",)),
        (system.snmp_to_controller_update, {"unknown": "value", "enabled": True}, {"enabled": True}, ("unknown",)),
        (
            system.autobackup_to_controller_update,
            {"unknown": "value", "autobackup_enabled": True},
            {"autobackup_enabled": True},
            ("unknown",),
        ),
        (
            traffic_routes.to_controller_update,
            {"unknown_key": "value", "enabled": True},
            {"enabled": True},
            ("unknown_key",),
        ),
    ],
)
def test_update_unknown_fields(convert, fields, expected, absent):
    result = convert(fields)
    assert_fields(result, expected)
    for key in absent:
        assert key not in result


@pytest.mark.parametrize(
    "convert, fields, expected",
    [
        (ap_group.to_controller_update, {"id": "read-only"}, {}),
        (client_group.to_controller_update, {"id": "read-only"}, {}),
        (content_filter.to_controller_update, {"id": "read-only"}, {}),
        (devices.to_controller_update, {"name": None}, {}),
        (dns.to_controller_update, {"id": "read-only"}, {}),
        (dynamic_dns.to_controller_update, {"id": "read-only"}, {}),
        (firewall.to_controller_update, {"id": "read-only"}, {}),
        (gateway_settings.to_controller_update, {"syn_cookies": False, "broadcast_ping": None}, {"syn_cookies": False}),
        (networks.to_controller_update, {"id": "read-only", "site_id": "also-read-only"}, {}),
        (oon.to_controller_update, {"id": "read-only"}, {}),
        (port_forwards.to_controller_update, {"id": "read-only"}, {}),
        (qos.to_controller_update, {"id": "read-only", "site_id": "also"}, {}),
        (switch.to_controller_update, {"id": "read-only", "attr_no_delete": True}, {}),
    ],
)
def test_update_values(convert, fields, expected):
    assert convert(fields) == expected


@pytest.mark.parametrize(
    "convert, fields, absent",
    [
        (
            dns.to_controller_create,
            dns.DnsRecord(key="test.local", value="1.2.3.4", record_type="A"),
            ("port", "priority", "weight", "enabled"),
        ),
        (
            dynamic_dns.to_controller_create,
            dynamic_dns.DynamicDns(host_name="home.example.com", service="dyndns"),
            ("server", "login", "x_password", "custom_service", "options"),
        ),
        (networks.to_controller_create, networks.Network(name="Minimal"), ("dhcpd_start", "vlan")),
        (qos.to_controller_create, qos.QosRule(name="Minimal"), ("target_ip_address", "target_subnet")),
        (
            traffic_routes.to_controller_create,
            traffic_routes.TrafficRoute(name="Minimal", matching_target="INTERNET", network_id="net-1"),
            ("next_hop", "kill_switch_enabled"),
        ),
        (vpn.to_controller_create, vpn.VpnClient(name="Minimal"), ("server_address", "enabled")),
    ],
)
def test_create_none_fields(convert, fields, absent):
    result = convert(fields)
    for key in absent:
        assert key not in result
