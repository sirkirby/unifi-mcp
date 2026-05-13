"""Fixture e2e tests for protect/events resolvers.

# tool: protect_list_events
# tool: protect_get_event
# tool: protect_get_event_thumbnail
# tool: protect_list_smart_detections
# tool: protect_alarm_get_status
# tool: protect_alarm_list_profiles
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_protect_events_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "event_manager", "list_events"): [
                {
                    "id": "evt1",
                    "type": "motion",
                    "camera_id": "cam1",
                    "start": 1000,
                    "recognized_person_name": "Assigned Person",
                },
                {"id": "evt2", "type": "person", "camera_id": "cam1", "start": 2000},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ events(controller: "{cid}", limit: 10) {{
            items {{ id type recognizedPersonName }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["protect"]["events"]["items"]
    assert len(items) == 2
    assert {it["id"] for it in items} == {"evt1", "evt2"}
    assert next(it for it in items if it["id"] == "evt1")["recognizedPersonName"] == "Assigned Person"


@pytest.mark.asyncio
async def test_protect_event_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "event_manager", "list_events"): [
                {
                    "id": "evt1",
                    "type": "motion",
                    "camera_id": "cam1",
                    "start": 1000,
                    "recognized_person_id": "face-group-1",
                    "recognized_person_name": "Assigned Person",
                },
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ event(controller: "{cid}", id: "evt1") {{
            id type recognizedPersonId recognizedPersonName
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["protect"]["event"]["id"] == "evt1"
    assert body["data"]["protect"]["event"]["type"] == "motion"
    assert body["data"]["protect"]["event"]["recognizedPersonId"] == "face-group-1"
    assert body["data"]["protect"]["event"]["recognizedPersonName"] == "Assigned Person"


@pytest.mark.asyncio
async def test_protect_event_thumbnail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "event_manager", "get_event_thumbnail"): {
                "event_id": "evt1",
                "thumbnail_id": "thumb1",
                "thumbnail_available": True,
                "content_type": "image/jpeg",
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ eventThumbnail(controller: "{cid}", eventId: "evt1") {{
            eventId thumbnailAvailable contentType
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["protect"]["eventThumbnail"]["eventId"] == "evt1"
    assert body["data"]["protect"]["eventThumbnail"]["thumbnailAvailable"] is True


@pytest.mark.asyncio
async def test_protect_smart_detections_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "event_manager", "list_smart_detections"): [
                {
                    "id": "sd1",
                    "type": "face",
                    "camera_id": "cam1",
                    "start": 1000,
                    "score": 90,
                    "recognized_person_name": "Assigned Person",
                },
                {"id": "sd2", "type": "vehicle", "camera_id": "cam1", "start": 2000, "score": 75},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ smartDetections(controller: "{cid}", limit: 10) {{
            items {{ id type score recognizedPersonName }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["protect"]["smartDetections"]["items"]
    assert len(items) == 2
    assert {it["id"] for it in items} == {"sd1", "sd2"}
    assert next(it for it in items if it["id"] == "sd1")["recognizedPersonName"] == "Assigned Person"


@pytest.mark.asyncio
async def test_protect_alarm_status(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "alarm_manager", "get_arm_state"): {
                "armed": True,
                "status": "armed_away",
                "active_profile_id": "prof1",
                "active_profile_name": "Away",
                "profile_count": 2,
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ alarmStatus(controller: "{cid}") {{
            armed status activeProfileName
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    result = body["data"]["protect"]["alarmStatus"]
    assert result["armed"] is True
    assert result["status"] == "armed_away"
    assert result["activeProfileName"] == "Away"


@pytest.mark.asyncio
async def test_protect_alarm_list_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "alarm_manager", "list_arm_profiles"): {
                "profiles": [
                    {"id": "prof1", "name": "Away"},
                    {"id": "prof2", "name": "Home"},
                ],
                "count": 2,
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ alarmProfiles(controller: "{cid}") {{
            count
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    result = body["data"]["protect"]["alarmProfiles"]
    assert result["count"] == 2
