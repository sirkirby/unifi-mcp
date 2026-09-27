"""Fixture coverage for the V2 NAT read family.

# tool: unifi_list_nat_rules
# tool: unifi_get_nat_rule
"""

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_nat_list_detail_and_missing_rule(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "nat_manager", "list_nat_rules"): [
                {
                    "_id": "nat-1",
                    "type": "DNAT",
                    "enabled": False,
                    "source_filter": {"filter_type": "NONE", "x_password": "private"},
                }
            ]
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{ network {{
            natRules(controller: "{cid}") {{ items {{ id type enabled description sourceFilter }} }}
            natRule(controller: "{cid}", id: "nat-1") {{ id type enabled description sourceFilter }}
            missing: natRule(controller: "{cid}", id: "missing") {{ id }}
        }} }}''',
    )
    assert body.get("errors") is None, body
    network = body["data"]["network"]
    expected = {
        "id": "nat-1",
        "type": "DNAT",
        "enabled": False,
        "description": None,
        "sourceFilter": {"filter_type": "NONE", "x_password": "***REDACTED***"},
    }
    assert network["natRules"]["items"] == [expected]
    assert network["natRule"] == expected
    assert network["missing"] is None
