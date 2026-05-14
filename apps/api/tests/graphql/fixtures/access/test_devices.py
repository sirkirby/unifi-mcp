"""Fixture e2e tests for access/devices resolvers.

# tool: access_list_devices
# tool: access_get_device
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_access_devices_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "device_manager", "list_devices"): [
                {"id": "dev1", "name": "Reader A", "type": "UA-Reader"},
                {"id": "dev2", "name": "Hub B", "type": "UA-Hub"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ devices(controller: "{cid}", limit: 10) {{
            items {{ id name }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["access"]["devices"]["items"]
    assert len(items) == 2
    assert {it["id"] for it in items} == {"dev1", "dev2"}


@pytest.mark.asyncio
async def test_access_device_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "device_manager", "list_devices"): [
                {"id": "dev1", "name": "Reader A", "type": "UA-Reader"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ device(controller: "{cid}", id: "dev1") {{
            id name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["access"]["device"]["id"] == "dev1"
    assert body["data"]["access"]["device"]["name"] == "Reader A"
