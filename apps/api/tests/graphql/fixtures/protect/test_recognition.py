"""Fixture e2e tests for protect/recognition resolvers.

# tool: protect_list_known_faces
# tool: protect_list_known_license_plates
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
