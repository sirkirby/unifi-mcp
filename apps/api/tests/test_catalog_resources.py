"""/v1/catalog/resources endpoint tests."""

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
async def test_catalog_resources_shape(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_with_read_key(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/catalog/resources", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    sample = body["items"][0]
    assert "product" in sample
    assert "resource_path" in sample
    assert "render_hint" in sample
    assert sample["resource_path"].startswith("/v1/sites/{site_id}/")


@pytest.mark.asyncio
async def test_catalog_resources_count(tmp_path, monkeypatch) -> None:
    """Resource registration regression guard.

    Current registered count is 28 (network=10, protect=9, access=9). Task 22's
    test_resource_route_coverage gate will flag the gap to 50+ that the plan
    anticipated; this test simply prevents regressions below today's surface.
    """
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_with_read_key(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/catalog/resources", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 28, f"expected >=28 resource entries, got {len(items)}"


@pytest.mark.asyncio
async def test_catalog_resources_includes_render_hint_kinds(tmp_path, monkeypatch) -> None:
    """Render hints should include the kinds we registered (list, detail, event_log, etc.)."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_with_read_key(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/catalog/resources", headers={"Authorization": f"Bearer {key}"})
    body = r.json()
    kinds = {item["render_hint"]["kind"] for item in body["items"] if "kind" in item.get("render_hint", {})}
    assert "list" in kinds  # Phase 3+5A registered many LIST resources
