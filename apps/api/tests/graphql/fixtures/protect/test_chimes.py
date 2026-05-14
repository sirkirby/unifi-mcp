"""Fixture e2e tests for protect/chimes resolver.

# tool: protect_list_chimes
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_protect_chimes_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "chime_manager", "list_chimes"): [
                {"id": "chime1", "name": "Doorbell", "model": "G4 Doorbell", "volume": 80},
                {"id": "chime2", "name": "Back Door", "model": "G4 Doorbell", "volume": 60},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ chimes(controller: "{cid}", limit: 10) {{
            items {{ id name model volume }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["protect"]["chimes"]["items"]
    assert len(items) == 2
    assert {it["id"] for it in items} == {"chime1", "chime2"}
    assert items[0]["volume"] in (80, 60)
