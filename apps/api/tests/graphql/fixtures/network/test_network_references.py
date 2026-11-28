"""Fixture e2e tests for the network/network_references resolver.

# tool: unifi_get_network_references
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import (
    bootstrap,
    graphql_query,
    stub_managers,
)


@pytest.mark.asyncio
async def test_network_references_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "network_reference_manager", "get_network_references"): {
                "network_id": "net-1",
                "name": "Corporate",
                "references": {
                    "wlans": [{"id": "wlan-1", "name": "Office"}],
                    "port_profiles": [],
                    "device_port_overrides": [],
                    "firewall_policies": [{"id": "fp-1", "name": "Block", "direction": "source"}],
                    "clients": [],
                },
                "counts": {
                    "wlans": 1,
                    "port_profiles": 0,
                    "device_port_overrides": 0,
                    "firewall_policies": 1,
                    "clients": 0,
                },
                "unavailable": [],
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ networkReferences(controller: "{cid}", networkId: "net-1") {{
            networkId name references counts unavailable
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    refs = body["data"]["network"]["networkReferences"]
    assert refs["networkId"] == "net-1"
    assert refs["name"] == "Corporate"
    assert refs["references"]["wlans"] == [{"id": "wlan-1", "name": "Office"}]
    assert refs["counts"]["firewall_policies"] == 1
    assert refs["unavailable"] == []
