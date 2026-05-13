"""Fixture e2e tests for protect/recognition resolvers.

# tool: protect_list_known_faces
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
        protect {{ knownFaces(controller: "{cid}", limit: 10) {{
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
