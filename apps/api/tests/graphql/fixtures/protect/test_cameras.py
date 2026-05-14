"""Fixture e2e tests for protect/cameras resolvers.

# tool: protect_list_cameras
# tool: protect_get_camera
# tool: protect_get_camera_analytics
# tool: protect_get_camera_streams
# tool: protect_get_snapshot
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_protect_cameras_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "camera_manager", "list_cameras"): [
                {"id": "cam1", "name": "Front Door", "model": "G4_PRO"},
                {"id": "cam2", "name": "Garage", "model": "G5_FLEX"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ cameras(controller: "{cid}", limit: 10) {{
            items {{ id name model }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["protect"]["cameras"]["items"]
    assert len(items) == 2
    assert {it["id"] for it in items} == {"cam1", "cam2"}


@pytest.mark.asyncio
async def test_protect_camera_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "camera_manager", "list_cameras"): [
                {"id": "cam1", "name": "Front Door", "model": "G4_PRO"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ camera(controller: "{cid}", id: "cam1") {{
            id name model
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["protect"]["camera"]["id"] == "cam1"
    assert body["data"]["protect"]["camera"]["name"] == "Front Door"


@pytest.mark.asyncio
async def test_protect_camera_analytics(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "camera_manager", "get_camera_analytics"): {
                "camera_id": "cam1",
                "camera_name": "Front Door",
                "motion_zone_count": 3,
                "smart_detect_zone_count": 1,
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ cameraAnalytics(controller: "{cid}", id: "cam1") {{
            cameraId cameraName motionZoneCount
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["protect"]["cameraAnalytics"]["cameraId"] == "cam1"
    assert body["data"]["protect"]["cameraAnalytics"]["motionZoneCount"] == 3


@pytest.mark.asyncio
async def test_protect_camera_streams(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "camera_manager", "get_camera_streams"): {
                "camera_id": "cam1",
                "camera_name": "Front Door",
                "channels": {},
                "rtsps_streams": {},
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ cameraStreams(controller: "{cid}", id: "cam1") {{
            cameraId cameraName
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["protect"]["cameraStreams"]["cameraId"] == "cam1"


@pytest.mark.asyncio
async def test_protect_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "camera_manager", "get_snapshot"): {
                "camera_id": "cam1",
                "content_type": "image/jpeg",
                "size_bytes": 48200,
                "captured_at": "2024-01-01T00:00:00Z",
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ snapshot(controller: "{cid}", id: "cam1") {{
            contentType sizeBytes capturedAt
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["protect"]["snapshot"]["contentType"] == "image/jpeg"
    assert body["data"]["protect"]["snapshot"]["sizeBytes"] == 48200
