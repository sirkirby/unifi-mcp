"""Fixture e2e tests for network/dns resolvers.

# tool: unifi_list_dns_records
# tool: unifi_get_dns_record_details
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import (
    bootstrap,
    graphql_query,
    stub_managers,
)


@pytest.mark.asyncio
async def test_dns_records_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "dns_manager", "list_dns_records"): [
                {"_id": "dns-1", "key": "nas.local", "value": "10.0.0.10"},
                {"_id": "dns-2", "key": "printer.local", "value": "10.0.0.11"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ dnsRecords(controller: "{cid}", limit: 10) {{
            items {{ id }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["dnsRecords"]["items"]
    assert len(items) == 2


@pytest.mark.asyncio
async def test_dns_record_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "dns_manager", "list_dns_records"): [
                {"_id": "dns-1", "key": "nas.local", "value": "10.0.0.10"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ dnsRecord(controller: "{cid}", id: "dns-1") {{
            id
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["dnsRecord"]["id"] == "dns-1"
