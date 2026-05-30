"""Fixture e2e tests for protect/recognition resolvers.

# tool: protect_list_known_faces
# tool: protect_list_known_license_plates
# tool: protect_search_detections
# tool: protect_detection_search_labels
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_protect_known_faces_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "recognition_manager", "list_known_faces"): {
                "faces": [
                    {
                        "id": "face-1",
                        "name": "Person One",
                        "matched_name": "Person One",
                        "type": "face",
                        "detections_count": 9,
                        "last_detected_at": 1778700000000,
                        "metadata": {},
                    }
                ],
                "count": 1,
                "links": {},
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ knownFaces(controller: "{cid}", limit: 10, groupTypes: ["unknown"]) {{
            items {{ id name matchedName detectionsCount lastDetectedAt }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["protect"]["knownFaces"]["items"]
    assert len(items) == 1
    assert items[0]["id"] == "face-1"
    assert items[0]["matchedName"] == "Person One"
    assert items[0]["detectionsCount"] == 9


@pytest.mark.asyncio
async def test_protect_known_license_plates_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "recognition_manager", "list_known_license_plates"): {
                "license_plates": [
                    {
                        "id": "plate-uuid-1",
                        "name": "Example Vehicle",
                        "matched_name": "ABC1234",
                        "type": "vehicle",
                        "detections_count": 42,
                        "last_detected_at": 1778700000000,
                        "metadata": {"color": {"val": "gray", "confidence": 73}},
                    }
                ],
                "count": 1,
                "links": {},
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ knownLicensePlates(controller: "{cid}", limit: 10, groupTypes: ["known"]) {{
            items {{ id name matchedName detectionsCount lastDetectedAt metadata }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["protect"]["knownLicensePlates"]["items"]
    assert len(items) == 1
    assert items[0]["id"] == "plate-uuid-1"
    assert items[0]["matchedName"] == "ABC1234"
    assert items[0]["detectionsCount"] == 42


@pytest.mark.asyncio
async def test_protect_search_detections(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "event_manager", "search_detections"): {
                "detections": [
                    {
                        "id": "det-1",
                        "type": "smartDetectZone",
                        "start": "2026-05-29T00:00:00+00:00",
                        "end": "2026-05-29T00:00:05+00:00",
                        "score": 88,
                        "smart_detect_types": ["vehicle"],
                        "camera_id": "cam-1",
                    }
                ],
                "count": 1,
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ searchDetections(controller: "{cid}", labels: ["vehicleType:truck"]) {{
            id type score smartDetectTypes camera
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["protect"]["searchDetections"]
    assert len(items) == 1
    assert items[0]["id"] == "det-1"
    assert items[0]["smartDetectTypes"] == ["vehicle"]
    assert items[0]["camera"] == "cam-1"


@pytest.mark.asyncio
async def test_protect_detection_search_labels(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "event_manager", "get_detection_search_labels"): {
                "colors": [{"label": "Black", "value": "color:black"}],
                "vehicle_types": [{"label": "Truck", "value": "vehicleType:truck"}],
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ detectionSearchLabels(controller: "{cid}") {{
            colors vehicleTypes
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    data = body["data"]["protect"]["detectionSearchLabels"]
    assert data["colors"] == [{"label": "Black", "value": "color:black"}]
    assert data["vehicleTypes"] == [{"label": "Truck", "value": "vehicleType:truck"}]
