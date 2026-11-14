"""Catalog endpoint tests."""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from unifi_api.auth.api_key import generate_key, hash_key
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.db.models import ApiKey, Base
from unifi_api.server import create_app


async def _bootstrap_with_read_key(tmp_path):
    app = create_app(
        ApiConfig(
            http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
            logging=LoggingConfig(level="WARNING"),
            db=DbConfig(path=str(tmp_path / "state.db")),
        )
    )
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = app.state.sessionmaker
    material = generate_key()
    async with sm() as session:
        session.add(
            ApiKey(
                id=str(uuid.uuid4()),
                prefix=material.prefix,
                hash=hash_key(material.plaintext),
                scopes="read",
                name="t",
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    return app, material.plaintext


@pytest.mark.asyncio
async def test_catalog_tools(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_with_read_key(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/catalog/tools", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert len(body["items"]) > 0
    sample = body["items"][0]
    assert "name" in sample and "product" in sample and "render_hint" in sample
    assert all(
        item["auth_method"] == app.state.manifest_registry.resolve(item["name"]).auth_method for item in body["items"]
    )
    requirements = {item["name"]: item["auth_method"] for item in body["items"]}
    assert requirements["unifi_list_devices"] == "either"
    assert requirements["unifi_create_firewall_zone"] == "both"
    assert requirements["unifi_get_firewall_policy_ordering"] == "both"
    assert requirements["unifi_reorder_firewall_policies"] == "both"
    assert requirements["access_lock_door"] == "either"


@pytest.mark.asyncio
async def test_catalog_categories(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_with_read_key(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/catalog/categories", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    sample = body["items"][0]
    assert "product" in sample and "category" in sample and "tool_count" in sample


@pytest.mark.asyncio
async def test_catalog_render_hints(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_with_read_key(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/catalog/render-hints", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    kinds = {item["kind"] for item in body["items"]}
    assert "list" in kinds  # at least one tool uses LIST kind


@pytest.mark.asyncio
async def test_cloud_catalog_paths_methods_hints_and_connection_kind(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from tests.sitemanager_data import CASES, bootstrap

    app, key, _ = await bootstrap(tmp_path, monkeypatch)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {key}"}
            tools = (await client.get("/v1/catalog/tools", headers=headers)).json()["items"]
            cloud = [item for item in tools if item["product"] == "sitemanager"]
            assert len(cloud) == 9
            assert {item["name"] for item in cloud} == {case[0] for case in CASES}
            assert all(
                item["connection_kind"] == "sitemanager_account" and item["render_hint"]["kind"] in {"list", "detail"}
                for item in cloud
            )
            resources = (await client.get("/v1/catalog/resources", headers=headers)).json()["items"]
            cloud = [item for item in resources if item["product"] == "sitemanager"]
            assert len(cloud) == 9
            expected = {
                (case[1], case[2].replace("synthetic-host", "{host_id}").replace("synthetic-config", "{config_id}"))
                for case in CASES
            }
            assert {(item["method"], item["resource_path"]) for item in cloud} == expected
            query = next(item for item in cloud if item["method"] == "POST")
            assert query["render_hint"]["kind"] == "detail"
            hints = (await client.get("/v1/catalog/render-hints", headers=headers)).json()["items"]
            cloud_resources = [
                resource for group in hints for resource in group["resources"] if resource["product"] == "sitemanager"
            ]
            assert len(cloud_resources) == 9
    finally:
        await app.state.engine.dispose()
