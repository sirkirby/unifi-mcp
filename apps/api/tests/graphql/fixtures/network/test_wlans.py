"""Fixture e2e tests for network/wlans resolvers.

# tool: unifi_list_wlans
# tool: unifi_get_wlan_details
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import (
    bootstrap,
    graphql_query,
    stub_managers,
)


@pytest.mark.asyncio
async def test_wlans_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "network_manager", "get_wlans"): [
                {"_id": "wl-1", "name": "HomeNet", "security": "wpapsk"},
                {"_id": "wl-2", "name": "GuestNet", "security": "open"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ wlans(controller: "{cid}", limit: 10) {{
            items {{ id name }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["wlans"]["items"]
    assert len(items) == 2
    names = {it["name"] for it in items}
    assert names == {"HomeNet", "GuestNet"}


@pytest.mark.asyncio
async def test_wlan_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "network_manager", "get_wlans"): [
                {"_id": "wl-1", "name": "HomeNet"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ wlan(controller: "{cid}", id: "wl-1") {{
            id name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["wlan"]["id"] == "wl-1"
