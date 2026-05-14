"""Fixture e2e tests for protect/system resolvers.

# tool: protect_get_system_info
# tool: protect_get_health
# tool: protect_get_firmware_status
# tool: protect_list_viewers
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_protect_system_info(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "system_manager", "get_system_info"): {
                "id": "nvr1",
                "name": "Home NVR",
                "model": "UNVR",
                "firmware_version": "4.0.1",
                "camera_count": 4,
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ systemInfo(controller: "{cid}") {{
            id name model firmwareVersion cameraCount
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    result = body["data"]["protect"]["systemInfo"]
    assert result["id"] == "nvr1"
    assert result["name"] == "Home NVR"
    assert result["cameraCount"] == 4


@pytest.mark.asyncio
async def test_protect_health(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "system_manager", "get_health"): {
                "cpu": {"averageLoad": 12.5},
                "memory": {"total": 8192, "used": 4096},
                "storage": {"used": 500, "total": 2000},
                "is_updating": False,
                "uptime_seconds": 86400,
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ health(controller: "{cid}") {{
            isUpdating uptimeSeconds
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    result = body["data"]["protect"]["health"]
    assert result["isUpdating"] is False
    assert result["uptimeSeconds"] == 86400


@pytest.mark.asyncio
async def test_protect_firmware_status(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "system_manager", "get_firmware_status"): {
                "nvr": {"version": "4.0.1", "latestVersion": "4.0.2"},
                "devices": [],
                "total_devices": 4,
                "devices_with_updates": 1,
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ firmwareStatus(controller: "{cid}") {{
            totalDevices devicesWithUpdates
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    result = body["data"]["protect"]["firmwareStatus"]
    assert result["totalDevices"] == 4
    assert result["devicesWithUpdates"] == 1


@pytest.mark.asyncio
async def test_protect_viewers_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "system_manager", "list_viewers"): {
                "viewers": [
                    {"id": "vw1", "name": "Living Room TV", "type": "viewer"},
                    {"id": "vw2", "name": "Office Monitor", "type": "viewer"},
                ],
                "count": 2,
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ viewers(controller: "{cid}") {{
            count
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["protect"]["viewers"]["count"] == 2
