"""Fixture e2e tests for network/acl_ordering resolvers.

# tool: unifi_list_integration_acl_rules
# tool: unifi_get_acl_rule_ordering
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import (
    bootstrap,
    graphql_query,
    stub_managers,
)


@pytest.mark.asyncio
async def test_integration_acl_rules_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "acl_manager", "list_integration_acl_rules"): [
                {"id": "rule-1", "name": "Block guest", "index": 2000, "action": "BLOCK", "enabled": True},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ integrationAclRules(controller: "{cid}", limit: 10) {{
            items {{ id name index action }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["integrationAclRules"]["items"]
    assert len(items) == 1
    assert items[0]["name"] == "Block guest"
    assert items[0]["action"] == "BLOCK"


@pytest.mark.asyncio
async def test_acl_rule_ordering_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "acl_manager", "get_acl_rule_ordering"): [
                "rule-2",
                "rule-1",
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ aclRuleOrdering(controller: "{cid}") {{
            orderedAclRuleIds
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["aclRuleOrdering"]["orderedAclRuleIds"] == ["rule-2", "rule-1"]
