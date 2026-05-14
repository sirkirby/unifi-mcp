"""Fixture e2e tests for protect/liveviews resolver.

# tool: protect_list_liveviews
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_protect_liveviews_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "liveview_manager", "list_liveviews"): [
                {"id": "lv1", "name": "All Cameras", "layout": 4, "is_default": True, "slot_count": 4},
                {"id": "lv2", "name": "Front", "layout": 1, "is_default": False, "slot_count": 1},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ liveviews(controller: "{cid}", limit: 10) {{
            items {{ id name layout isDefault }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["protect"]["liveviews"]["items"]
    assert len(items) == 2
    assert {it["id"] for it in items} == {"lv1", "lv2"}
    default = next(it for it in items if it["id"] == "lv1")
    assert default["isDefault"] is True
