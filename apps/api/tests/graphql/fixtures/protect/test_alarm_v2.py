"""Fixture e2e coverage for the Alarm Manager v2 GraphQL resolvers.

# tool: protect_alarm_v2_list_rules
# tool: protect_alarm_v2_get_rule
# tool: protect_alarm_v2_list_profiles
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_protect_alarm_v2_list_rules(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "alarm_v2_manager", "list_rules"): [
                {"id": "r1", "title": "Dog Alarm", "triggers": [{"trigger_id": "protect:ai.nls"}]},
                {"id": "r2", "title": "Person", "triggers": []},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'{{ protect {{ alarmV2Rules(controller: "{cid}") {{ count rules }} }} }}',
    )
    assert body.get("errors") is None, body
    result = body["data"]["protect"]["alarmV2Rules"]
    assert result["count"] == 2
    assert {r["id"] for r in result["rules"]} == {"r1", "r2"}


@pytest.mark.asyncio
async def test_protect_alarm_v2_get_rule(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "alarm_v2_manager", "get_rule"): {
                "id": "r1",
                "title": "Dog Alarm",
                "triggers": [{"trigger_id": "protect:ai.nls", "data": {"nlsSentence": "x"}}],
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'{{ protect {{ alarmV2Rule(controller: "{cid}", id: "r1") {{ id title triggers }} }} }}',
    )
    assert body.get("errors") is None, body
    result = body["data"]["protect"]["alarmV2Rule"]
    assert result["id"] == "r1"
    assert result["title"] == "Dog Alarm"


@pytest.mark.asyncio
async def test_protect_alarm_v2_list_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "alarm_v2_manager", "list_profiles"): [],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'{{ protect {{ alarmV2Profiles(controller: "{cid}") {{ count profiles }} }} }}',
    )
    assert body.get("errors") is None, body
    result = body["data"]["protect"]["alarmV2Profiles"]
    assert result["count"] == 0
    assert result["profiles"] == []
