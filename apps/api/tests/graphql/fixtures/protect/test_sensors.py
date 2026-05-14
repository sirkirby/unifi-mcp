"""Fixture e2e tests for protect/sensors resolver.

# tool: protect_list_sensors
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_protect_sensors_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "sensor_manager", "list_sensors"): [
                {"id": "sensor1", "name": "Garage Door", "type": "door"},
                {"id": "sensor2", "name": "Basement Leak", "type": "leak"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ sensors(controller: "{cid}", limit: 10) {{
            items {{ id name type }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["protect"]["sensors"]["items"]
    assert len(items) == 2
    assert {it["id"] for it in items} == {"sensor1", "sensor2"}
