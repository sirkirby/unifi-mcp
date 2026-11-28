"""Fixture e2e tests for the network/ips_suppression resolver and route.

# tool: unifi_list_ips_suppressions
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from unifi_api.db.models import ApiKey, Controller
from unifi_api.services.managers import ManagerFactory
from unifi_core.network.models.ips_suppression import ips_suppressions_from_controller

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


def _stub(monkeypatch):
    value = ips_suppressions_from_controller(
        {
            "alerts": [
                {"id": 4294967295, "gid": 1, "type": "all", "category": "emerging-misc", "signature": "ET"},
                {"id": 2000002, "type": "all"},
            ],
            "whitelist": [{"mode": "ip", "value": "192.0.2.30", "direction": "dest"}],
        }
    )
    stub_managers(monkeypatch, {("network", "system_manager", "list_ips_suppressions"): value})


@pytest.mark.asyncio
async def test_ips_suppressions_graphql(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    _stub(monkeypatch)
    body = await graphql_query(
        app,
        key,
        f'''{{ network {{ ipsSuppressions(controller: "{cid}") {{
            suppressions {{ signatureId gid signature category suppressionType scope direction mode target }}
            exclusions {{ scope direction mode target }}
        }} }} }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["ipsSuppressions"] == {
        "suppressions": [
            {
                "signatureId": 4294967295,
                "gid": 1,
                "signature": "ET",
                "category": "emerging-misc",
                "suppressionType": "all",
                "scope": "global",
                "direction": None,
                "mode": None,
                "target": None,
            },
            {
                "signatureId": 2000002,
                "gid": None,
                "signature": None,
                "category": None,
                "suppressionType": "all",
                "scope": "global",
                "direction": None,
                "mode": None,
                "target": None,
            },
        ],
        "exclusions": [{"scope": "destination", "direction": "dest", "mode": "ip", "target": "192.0.2.30"}],
    }


@pytest.mark.asyncio
async def test_ips_suppressions_rest(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    _stub(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/sites/default/ips-suppressions?controller={cid}", headers={"Authorization": f"Bearer {key}"}
        )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert [(s["signature_id"], s["scope"]) for s in data["suppressions"]] == [
        (4294967295, "global"),
        (2000002, "global"),
    ]
    assert data["exclusions"] == [{"scope": "destination", "direction": "dest", "mode": "ip", "target": "192.0.2.30"}]


def _by_site(monkeypatch) -> None:
    async def _get(self, session, controller_id, product, attr_name, *, site=None):
        manager = AsyncMock()
        manager.list_ips_suppressions.return_value = ips_suppressions_from_controller(
            {"alerts": [], "whitelist": [{"mode": "ip", "value": site, "direction": "src"}]}
        )
        return manager

    monkeypatch.setattr(ManagerFactory, "get_domain_manager", _get)


@pytest.mark.asyncio
async def test_each_site_gets_its_own_suppressions(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, {})
    _by_site(monkeypatch)
    body = await graphql_query(
        app,
        key,
        f'''{{ network {{
            a: ipsSuppressions(controller: "{cid}", site: "a") {{ exclusions {{ target }} }}
            b: ipsSuppressions(controller: "{cid}", site: "b") {{ exclusions {{ target }} }}
        }} }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"] == {
        "a": {"exclusions": [{"target": "a"}]},
        "b": {"exclusions": [{"target": "b"}]},
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/sites/a/ips-suppressions?controller={cid}", headers={"Authorization": f"Bearer {key}"}
        )
    assert response.json()["data"]["exclusions"][0]["target"] == "a"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model,values,status", [(ApiKey, {"scopes": "write"}, 403), (Controller, {"product_kinds": "protect"}, 409)]
)
async def test_route_requires_read_scope_and_network(tmp_path, monkeypatch, model, values, status):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    _stub(monkeypatch)
    async with app.state.sessionmaker() as session:
        await session.execute(update(model).values(**values))
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/sites/default/ips-suppressions?controller={cid}", headers={"Authorization": f"Bearer {key}"}
        )
    assert response.status_code == status
