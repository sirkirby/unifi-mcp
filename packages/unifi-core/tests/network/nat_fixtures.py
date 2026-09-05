"""NAT rule fixtures shared by the model and manager tests.

The shapes mirror what a Network 10.6 controller stores at
``/v2/api/site/{site}/nat``; every address and id is a placeholder.
"""

from __future__ import annotations

from typing import Any

NONE_FILTER = {"filter_type": "NONE", "firewall_group_ids": [], "invert_address": False, "invert_port": False}

DNS_REDIRECT: dict[str, Any] = {
    "_id": "6f0000000000000000000001",
    "type": "DNAT",
    "description": "All DNS to resolver",
    "enabled": True,
    "rule_index": 3,
    "protocol": "tcp_udp",
    "ip_version": "IPV4",
    "in_interface": "6f0000000000000000000010",
    "ip_address": "192.0.2.53",
    "port": "53",
    "logging": False,
    "exclude": False,
    "is_predefined": False,
    "setting_preference": "manual",
    "pppoe_use_base_interface": False,
    "source_filter": dict(NONE_FILTER),
    "destination_filter": {
        "filter_type": "ADDRESS_AND_PORT",
        "firewall_group_ids": [],
        "invert_address": True,
        "invert_port": False,
        "address": "192.0.2.53",
        "port": "53",
    },
}

READ_ONLY = ("_id", "is_predefined", "setting_preference")


def dnat(**overrides: Any) -> dict[str, Any]:
    """The DNS-redirect rule as a caller would submit it, with overrides applied."""
    rule = {k: v for k, v in DNS_REDIRECT.items() if k not in READ_ONLY}
    rule.update(overrides)
    return rule
