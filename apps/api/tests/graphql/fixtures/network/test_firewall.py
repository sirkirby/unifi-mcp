"""Fixture e2e tests for network/firewall resolvers.

# tool: unifi_list_firewall_policies
# tool: unifi_get_firewall_policy_details
# tool: unifi_list_firewall_groups
# tool: unifi_get_firewall_group_details
# tool: unifi_list_firewall_zones
# tool: unifi_get_firewall_policy_ordering
# tool: unifi_list_legacy_firewall_rules
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import (
    bootstrap,
    graphql_query,
    stub_managers,
)


@pytest.mark.asyncio
async def test_firewall_policies_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "firewall_manager", "get_firewall_policies"): [
                {"_id": "fp-1", "name": "Block-IoT", "action": "drop", "enabled": True},
                {"_id": "fp-2", "name": "Allow-LAN", "action": "accept", "enabled": True},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ firewallPolicies(controller: "{cid}", limit: 10) {{
            items {{ id name action }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["firewallPolicies"]["items"]
    assert len(items) == 2
    names = {it["name"] for it in items}
    assert names == {"Block-IoT", "Allow-LAN"}


@pytest.mark.asyncio
async def test_firewall_policy_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "firewall_manager", "get_firewall_policies"): [
                {"_id": "fp-1", "name": "Block-IoT", "action": "drop"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ firewallPolicy(controller: "{cid}", id: "fp-1") {{
            id name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["firewallPolicy"]["id"] == "fp-1"


@pytest.mark.asyncio
async def test_firewall_groups_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "firewall_manager", "get_firewall_groups"): [
                {"_id": "fg-1", "name": "TrustedHosts", "group_type": "address-group"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ firewallGroups(controller: "{cid}", limit: 10) {{
            items {{ id name groupType }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["firewallGroups"]["items"]
    assert len(items) == 1
    assert items[0]["name"] == "TrustedHosts"


@pytest.mark.asyncio
async def test_firewall_group_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "firewall_manager", "get_firewall_groups"): [
                {"_id": "fg-1", "name": "TrustedHosts"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ firewallGroup(controller: "{cid}", id: "fg-1") {{
            id name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["firewallGroup"]["id"] == "fg-1"


@pytest.mark.asyncio
async def test_firewall_zones_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "firewall_manager", "get_firewall_zones"): [
                {"_id": "fz-1", "name": "LAN", "default_policy": "accept"},
                {"_id": "fz-2", "name": "WAN", "default_policy": "drop"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ firewallZones(controller: "{cid}") {{
            id name defaultPolicy
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    zones = body["data"]["network"]["firewallZones"]
    assert len(zones) == 2
    names = {z["name"] for z in zones}
    assert names == {"LAN", "WAN"}


@pytest.mark.asyncio
async def test_legacy_firewall_rules_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "firewall_manager", "get_legacy_firewall_rules"): [
                {
                    "_id": "lfr-1",
                    "name": "Block IoT to LAN",
                    "ruleset": "LAN_IN",
                    "rule_index": 2001,
                    "action": "drop",
                    "enabled": True,
                    "src_firewallgroup_ids": ["grp-1"],
                    "state_established": False,
                },
                {
                    "_id": "lfr-2",
                    "name": "Allow established",
                    "ruleset": "WAN_IN",
                    "rule_index": 2000,
                    "action": "accept",
                    "enabled": True,
                    "state_established": True,
                },
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ legacyFirewallRules(controller: "{cid}") {{
            id name ruleset ruleIndex action enabled srcFirewallgroupIds stateEstablished
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    rules = body["data"]["network"]["legacyFirewallRules"]
    assert len(rules) == 2

    by_id = {r["id"]: r for r in rules}
    assert by_id["lfr-1"]["ruleset"] == "LAN_IN"
    assert by_id["lfr-1"]["ruleIndex"] == 2001
    # Legacy actions stay lowercase; the V2 engine's ALLOW/BLOCK casing does not apply.
    assert by_id["lfr-1"]["action"] == "drop"
    assert by_id["lfr-1"]["srcFirewallgroupIds"] == ["grp-1"]
    assert by_id["lfr-1"]["stateEstablished"] is False
    assert by_id["lfr-2"]["stateEstablished"] is True


@pytest.mark.asyncio
async def test_firewall_policy_ordering_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "firewall_manager", "get_firewall_policy_ordering"): {
                "orderedFirewallPolicyIds": {
                    "beforeSystemDefined": ["allow-1"],
                    "afterSystemDefined": ["block-1"],
                }
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ firewallPolicyOrdering(
            controller: "{cid}",
            sourceFirewallZoneId: "zone-src",
            destinationFirewallZoneId: "zone-dst"
        ) {{
            ordering
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    ordering = body["data"]["network"]["firewallPolicyOrdering"]["ordering"]
    assert ordering["beforeSystemDefined"] == ["allow-1"]
