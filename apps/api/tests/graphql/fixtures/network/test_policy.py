"""Fixture e2e tests for network/policy resolvers.

# tool: unifi_list_qos_rules
# tool: unifi_get_qos_rule_details
# tool: unifi_list_content_filters
# tool: unifi_get_content_filter_details
# tool: unifi_list_acl_rules
# tool: unifi_get_acl_rule_details
# tool: unifi_list_oon_policies
# tool: unifi_get_oon_policy_details
# tool: unifi_list_port_forwards
# tool: unifi_get_port_forward
# tool: unifi_list_dpi_applications
# tool: unifi_list_dpi_categories
# tool: unifi_get_dpi_stats
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import (
    bootstrap,
    graphql_query,
    stub_managers,
)


@pytest.mark.asyncio
async def test_qos_rules_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "qos_manager", "get_qos_rules"): [
                {"_id": "qr-1", "name": "Streaming", "enabled": True},
                {"_id": "qr-2", "name": "Gaming", "enabled": True},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ qosRules(controller: "{cid}", limit: 10) {{
            items {{ id name }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["qosRules"]["items"]
    assert len(items) == 2


@pytest.mark.asyncio
async def test_qos_rule_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "qos_manager", "get_qos_rules"): [
                {"_id": "qr-1", "name": "Streaming"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ qosRule(controller: "{cid}", id: "qr-1") {{
            id name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["qosRule"]["id"] == "qr-1"


@pytest.mark.asyncio
async def test_content_filters_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "content_filter_manager", "get_content_filters"): [
                {"_id": "cf-1", "name": "Kids-Filter", "enabled": True},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ contentFilters(controller: "{cid}", limit: 10) {{
            items {{ id name }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["contentFilters"]["items"]
    assert len(items) == 1
    assert items[0]["name"] == "Kids-Filter"


@pytest.mark.asyncio
async def test_content_filter_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "content_filter_manager", "get_content_filters"): [
                {"_id": "cf-1", "name": "Kids-Filter"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ contentFilter(controller: "{cid}", id: "cf-1") {{
            id name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["contentFilter"]["id"] == "cf-1"


@pytest.mark.asyncio
async def test_acl_rules_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "acl_manager", "get_acl_rules"): [
                {"_id": "acl-1", "name": "Block-Social", "action": "deny"},
                {"_id": "acl-2", "name": "Allow-Work", "action": "allow"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ aclRules(controller: "{cid}", limit: 10) {{
            items {{ id name action }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["aclRules"]["items"]
    assert len(items) == 2


@pytest.mark.asyncio
async def test_acl_rule_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "acl_manager", "get_acl_rules"): [
                {"_id": "acl-1", "name": "Block-Social"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ aclRule(controller: "{cid}", id: "acl-1") {{
            id name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["aclRule"]["id"] == "acl-1"


@pytest.mark.asyncio
async def test_oon_policies_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "oon_manager", "get_oon_policies"): [
                {"_id": "oon-1", "name": "School-Mode", "enabled": True},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ oonPolicies(controller: "{cid}", limit: 10) {{
            items {{ id name }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["oonPolicies"]["items"]
    assert len(items) == 1
    assert items[0]["name"] == "School-Mode"


@pytest.mark.asyncio
async def test_oon_policy_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "oon_manager", "get_oon_policies"): [
                {"_id": "oon-1", "name": "School-Mode"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ oonPolicy(controller: "{cid}", id: "oon-1") {{
            id name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["oonPolicy"]["id"] == "oon-1"


@pytest.mark.asyncio
async def test_port_forwards_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "firewall_manager", "get_port_forwards"): [
                {"_id": "pf-1", "name": "HTTP-Server", "enabled": True, "fwd_protocol": "tcp"},
                {"_id": "pf-2", "name": "Game-Server", "enabled": True, "fwd_protocol": "udp"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ portForwards(controller: "{cid}", limit: 10) {{
            items {{ id name fwdProtocol }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["portForwards"]["items"]
    assert len(items) == 2


@pytest.mark.asyncio
async def test_port_forward_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "firewall_manager", "get_port_forwards"): [
                {"_id": "pf-1", "name": "HTTP-Server"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ portForward(controller: "{cid}", id: "pf-1") {{
            id name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["portForward"]["id"] == "pf-1"


@pytest.mark.asyncio
async def test_dpi_applications_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "dpi_manager", "get_dpi_applications"): [
                {"id": 101, "name": "Netflix"},
                {"id": 102, "name": "YouTube"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ dpiApplications(controller: "{cid}", limit: 10) {{
            items {{ id name }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["dpiApplications"]["items"]
    assert len(items) == 2


@pytest.mark.asyncio
async def test_dpi_categories_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "dpi_manager", "get_dpi_categories"): [
                {"id": 1, "name": "Streaming"},
                {"id": 2, "name": "Social"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ dpiCategories(controller: "{cid}", limit: 10) {{
            items {{ id name }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["dpiCategories"]["items"]
    assert len(items) == 2


@pytest.mark.asyncio
async def test_dpi_stats(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "stats_manager", "get_dpi_stats"): {
                "applications": [{"id": 101, "name": "Netflix"}],
                "categories": [{"id": 1, "name": "Streaming"}],
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ dpiStats(controller: "{cid}") {{
            applications
            categories
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["dpiStats"] is not None
    assert len(body["data"]["network"]["dpiStats"]["applications"]) == 1
