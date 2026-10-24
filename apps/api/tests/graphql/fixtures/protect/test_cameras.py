"""Fixture e2e tests for protect/cameras resolvers.

# tool: protect_list_cameras
# tool: protect_get_camera
# tool: protect_get_camera_analytics
# tool: protect_get_camera_streams
# tool: protect_get_snapshot
"""

from __future__ import annotations

import pytest
from unifi_core.redaction import REDACTED

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


@pytest.mark.parametrize(
    ("manager_results", "query", "query_field", "value_field", "expected", "second_value_field", "expected_2"),
    [
        pytest.param(
            {("protect", "camera_manager", "get_camera"): {"id": "cam1", "name": "Front Door", "model": "G4_PRO"}},
            '{ protect { camera(controller: "CONTROLLER_ID", id: "cam1") { id name model } } }',
            "camera",
            "id",
            "cam1",
            "name",
            "Front Door",
            id="protect_camera_detail",
        ),
        pytest.param(
            {
                ("protect", "camera_manager", "get_camera_analytics"): {
                    "camera_id": "cam1",
                    "camera_name": "Front Door",
                    "motion_zone_count": 3,
                    "smart_detect_zone_count": 1,
                }
            },
            (
                '{ protect { cameraAnalytics(controller: "CONTROLLER_ID", id: "cam1") '
                "{ cameraId cameraName motionZoneCount } } }"
            ),
            "cameraAnalytics",
            "cameraId",
            "cam1",
            "motionZoneCount",
            3,
            id="protect_camera_analytics",
        ),
        pytest.param(
            {
                ("protect", "camera_manager", "get_snapshot"): {
                    "camera_id": "cam1",
                    "content_type": "image/jpeg",
                    "size_bytes": 48200,
                    "captured_at": "2024-01-01T00:00:00Z",
                }
            },
            '{ protect { snapshot(controller: "CONTROLLER_ID", id: "cam1") { contentType sizeBytes capturedAt } } }',
            "snapshot",
            "contentType",
            "image/jpeg",
            "sizeBytes",
            48200,
            id="protect_snapshot",
        ),
    ],
)
@pytest.mark.asyncio
async def test_camera_details(
    tmp_path, monkeypatch, manager_results, query, query_field, value_field, expected, second_value_field, expected_2
):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(monkeypatch, manager_results)
    body = await graphql_query(app, key, query.replace("CONTROLLER_ID", cid))
    assert body.get("errors") is None, body
    assert body["data"]["protect"][query_field][value_field] == expected
    assert body["data"]["protect"][query_field][second_value_field] == expected_2


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
                "channels": {
                    "high": {
                        "rtsp_alias": "abc123",
                        "rtsps_url": "rtsps://nvr.local/abc123",
                        "rtsp_url": "rtsp://nvr.local/abc123",
                    }
                },
                "rtsps_streams": {"high": "rtsps://nvr.local/abc123"},
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ cameraStreams(controller: "{cid}", id: "cam1") {{
            cameraId cameraName channels rtspsStreams
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    streams = body["data"]["protect"]["cameraStreams"]
    assert streams["cameraId"] == "cam1"
    assert streams["channels"]["high"]["rtsp_alias"] == REDACTED
    assert streams["channels"]["high"]["rtsps_url"] == REDACTED
    assert streams["channels"]["high"]["rtsp_url"] == REDACTED
    assert streams["rtspsStreams"] == REDACTED


@pytest.mark.asyncio
async def test_protect_camera_streams_policy_disabled_returns_raw_urls(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect", redact_sensitive_fields=False)
    stub_managers(
        monkeypatch,
        {
            ("protect", "camera_manager", "get_camera_streams"): {
                "camera_id": "cam1",
                "camera_name": "Front Door",
                "channels": {
                    "high": {
                        "rtsp_alias": "abc123",
                        "rtsps_url": "rtsps://nvr.local/abc123",
                        "rtsp_url": "rtsp://nvr.local/abc123",
                    }
                },
                "rtsps_streams": {"high": "rtsps://nvr.local/abc123"},
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ cameraStreams(controller: "{cid}", id: "cam1") {{
            channels rtspsStreams
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    streams = body["data"]["protect"]["cameraStreams"]
    assert streams["channels"]["high"]["rtsp_alias"] == "abc123"
    assert streams["channels"]["high"]["rtsps_url"] == "rtsps://nvr.local/abc123"
    assert streams["channels"]["high"]["rtsp_url"] == "rtsp://nvr.local/abc123"
    assert streams["rtspsStreams"]["high"] == "rtsps://nvr.local/abc123"
