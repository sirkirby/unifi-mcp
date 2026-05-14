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
