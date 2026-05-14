"""Fixture e2e tests for access/system resolvers.

# tool: access_get_health
# tool: access_get_system_info
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_access_health(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "system_manager", "get_health"): {
                "status": "healthy",
                "num_doors": 5,
                "num_devices": 10,
                "num_offline_devices": 0,
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ health(controller: "{cid}") {{
            status numDoors numDevices numOfflineDevices
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    health = body["data"]["access"]["health"]
    assert health["status"] == "healthy"
    assert health["numDoors"] == 5
    assert health["numDevices"] == 10
    assert health["numOfflineDevices"] == 0


@pytest.mark.asyncio
async def test_access_system_info(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "system_manager", "get_system_info"): {
                "name": "UniFi Access",
                "version": "2.5.0",
                "hostname": "access.local",
                "uptime": 86400,
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ systemInfo(controller: "{cid}") {{
            name version hostname uptime
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    info = body["data"]["access"]["systemInfo"]
    assert info["name"] == "UniFi Access"
    assert info["version"] == "2.5.0"
    assert info["uptime"] == 86400
