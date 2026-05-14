"""Fixture e2e tests for protect/recordings resolvers.

# tool: protect_list_recordings
# tool: protect_get_recording_status
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_protect_recordings_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "recording_manager", "list_recordings"): [
                {"id": "rec1", "type": "continuous", "camera_id": "cam1", "start": 1000},
                {"id": "rec2", "type": "motion", "camera_id": "cam1", "start": 2000},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ recordings(controller: "{cid}", cameraId: "cam1", limit: 10) {{
            items {{ id type }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["protect"]["recordings"]["items"]
    assert len(items) == 2
    assert {it["id"] for it in items} == {"rec1", "rec2"}


@pytest.mark.asyncio
async def test_protect_recording_status(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "recording_manager", "get_recording_status"): {
                "cameras": [
                    {"camera_id": "cam1", "is_recording": True, "recording_mode": "always"},
                ],
                "count": 1,
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ recordingStatus(controller: "{cid}") {{
            count
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["protect"]["recordingStatus"]["count"] == 1
