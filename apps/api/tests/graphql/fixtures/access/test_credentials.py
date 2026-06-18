"""Fixture e2e tests for access/credentials resolvers.

# tool: access_list_credentials
# tool: access_get_credential
"""

from __future__ import annotations

import pytest
from unifi_core.redaction import REDACTED

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_access_credentials_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "credential_manager", "list_credentials"): [
                {"id": "cred1", "type": "nfc", "status": "active"},
                {"id": "cred2", "type": "pin", "status": "active"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ credentials(controller: "{cid}", limit: 10) {{
            items {{ id type status }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["access"]["credentials"]["items"]
    assert len(items) == 2
    assert {it["id"] for it in items} == {"cred1", "cred2"}


@pytest.mark.asyncio
async def test_access_credential_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "credential_manager", "list_credentials"): [
                {"id": "cred1", "type": "nfc", "status": "active", "token": "nfc-token", "pin_code": "123456"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ credential(controller: "{cid}", id: "cred1") {{
            id type status token pinCode
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["access"]["credential"]["id"] == "cred1"
    assert body["data"]["access"]["credential"]["type"] == "nfc"
    assert body["data"]["access"]["credential"]["token"] == REDACTED
    assert body["data"]["access"]["credential"]["pinCode"] == REDACTED


@pytest.mark.asyncio
async def test_access_credential_detail_policy_disabled_returns_raw_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access", redact_sensitive_fields=False)
    stub_managers(
        monkeypatch,
        {
            ("access", "credential_manager", "list_credentials"): [
                {"id": "cred1", "type": "nfc", "status": "active", "token": "nfc-token", "pin_code": "123456"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ credential(controller: "{cid}", id: "cred1") {{
            id type status token pinCode
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["access"]["credential"]["token"] == "nfc-token"
    assert body["data"]["access"]["credential"]["pinCode"] == "123456"
