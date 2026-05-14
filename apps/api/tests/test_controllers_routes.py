"""Controllers HTTP routes."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from unifi_api.auth.api_key import generate_key, hash_key
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.db.models import ApiKey, Base
from unifi_api.server import create_app


def _cfg(tmp_path: Path) -> ApiConfig:
    return ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
    )


async def _bootstrap_app(tmp_path: Path, scopes: str = "admin"):
    app = create_app(_cfg(tmp_path))
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
                scopes=scopes,
                name="t",
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    return app, material.plaintext


@pytest.mark.asyncio
async def test_create_list_get_delete(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/v1/controllers",
            headers=headers,
            json={
                "name": "Home",
                "base_url": "https://10.0.0.1",
                "username": "root",
                "password": "hunter2",
                "product_kinds": ["network"],
                "verify_tls": False,
                "is_default": True,
            },
        )
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        r = await c.get("/v1/controllers", headers=headers)
        assert r.status_code == 200 and len(r.json()) == 1
        assert "credentials_blob" not in r.json()[0]
        r = await c.get(f"/v1/controllers/{cid}", headers=headers)
        assert r.status_code == 200 and r.json()["name"] == "Home"
        assert "credentials_blob" not in r.json()
        r = await c.delete(f"/v1/controllers/{cid}", headers=headers)
        assert r.status_code == 204
        r = await c.get(f"/v1/controllers/{cid}", headers=headers)
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_read_scope_cannot_create(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path, scopes="read")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/v1/controllers",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "name": "X",
                "base_url": "https://x",
                "username": "u",
                "password": "p",
                "product_kinds": ["network"],
                "verify_tls": True,
                "is_default": False,
            },
        )
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_no_auth_401(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, _ = await _bootstrap_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/controllers")
        assert r.status_code == 401
