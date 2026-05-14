"""Fixture e2e tests for protect/lights resolver.

# tool: protect_list_lights
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_protect_lights_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "light_manager", "list_lights"): [
                {"id": "light1", "name": "Porch", "model": "USF-Floodlight", "is_light_on": False},
                {"id": "light2", "name": "Back Yard", "model": "USF-Floodlight", "is_light_on": True},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ lights(controller: "{cid}", limit: 10) {{
            items {{ id name isLightOn }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["protect"]["lights"]["items"]
    assert len(items) == 2
    assert {it["id"] for it in items} == {"light1", "light2"}
