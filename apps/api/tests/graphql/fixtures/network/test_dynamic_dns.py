"""Fixture e2e tests for network/dynamic_dns resolvers.

# tool: unifi_list_dynamic_dns
# tool: unifi_get_dynamic_dns_entry_details
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import (
    bootstrap,
    graphql_query,
    stub_managers,
)


@pytest.mark.asyncio
async def test_dynamic_dns_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "dynamic_dns_manager", "list_dynamic_dns"): [
                {"_id": "ddns-1", "host_name": "home.example.com", "service": "dyndns"},
                {"_id": "ddns-2", "host_name": "alt.example.com", "service": "noip"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ dynamicDns(controller: "{cid}", limit: 10) {{
            items {{ id hostName service }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["dynamicDns"]["items"]
    assert len(items) == 2
    assert {i["hostName"] for i in items} == {"home.example.com", "alt.example.com"}


@pytest.mark.asyncio
async def test_dynamic_dns_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "dynamic_dns_manager", "list_dynamic_dns"): [
                {"_id": "ddns-1", "host_name": "home.example.com", "service": "dyndns"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ dynamicDnsEntry(controller: "{cid}", id: "ddns-1") {{
            id
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["dynamicDnsEntry"]["id"] == "ddns-1"


@pytest.mark.asyncio
async def test_dynamic_dns_redacts_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "dynamic_dns_manager", "list_dynamic_dns"): [
                {"_id": "ddns-1", "host_name": "home.example.com", "x_password": "super-secret"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ dynamicDns(controller: "{cid}", limit: 10) {{
            items {{ xPassword }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["dynamicDns"]["items"][0]["xPassword"] == "***REDACTED***"


@pytest.mark.asyncio
async def test_dynamic_dns_entry_redacts_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "dynamic_dns_manager", "list_dynamic_dns"): [
                {"_id": "ddns-1", "host_name": "home.example.com", "x_password": "super-secret"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ dynamicDnsEntry(controller: "{cid}", id: "ddns-1") {{
            xPassword
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["dynamicDnsEntry"]["xPassword"] == "***REDACTED***"


@pytest.mark.asyncio
async def test_dynamic_dns_shows_secret_when_policy_off(tmp_path, monkeypatch):
    """With the redaction policy disabled, the resolver must honor it and return
    the raw secret (the policy flag has to be threaded into from_manager_output)."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network", redact_sensitive_fields=False)
    stub_managers(
        monkeypatch,
        {
            ("network", "dynamic_dns_manager", "list_dynamic_dns"): [
                {"_id": "ddns-1", "host_name": "home.example.com", "x_password": "super-secret"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ dynamicDns(controller: "{cid}", limit: 10) {{
            items {{ xPassword }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["dynamicDns"]["items"][0]["xPassword"] == "super-secret"


@pytest.mark.asyncio
async def test_dynamic_dns_entry_shows_secret_when_policy_off(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network", redact_sensitive_fields=False)
    stub_managers(
        monkeypatch,
        {
            ("network", "dynamic_dns_manager", "list_dynamic_dns"): [
                {"_id": "ddns-1", "host_name": "home.example.com", "x_password": "super-secret"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ dynamicDnsEntry(controller: "{cid}", id: "ddns-1") {{
            xPassword
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["dynamicDnsEntry"]["xPassword"] == "super-secret"
