"""End-to-end smoke: the GraphQL endpoint exposes a `health` query field."""

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


async def _bootstrap(tmp_path: Path):
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
                scopes="read",
                name="t",
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    return app, material.plaintext


@pytest.mark.asyncio
async def test_graphql_health_query_returns_ok(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/v1/graphql",
            headers=headers,
            json={"query": "{ health { ok version pythonVersion } }"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("errors") is None, body
        assert body["data"]["health"]["ok"] is True
        assert isinstance(body["data"]["health"]["version"], str)
        assert isinstance(body["data"]["health"]["pythonVersion"], str)


@pytest.mark.asyncio
async def test_graphql_health_query_unauthenticated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, _ = await _bootstrap(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/graphql", json={"query": "{ health { ok } }"})
        assert r.status_code == 200, r.text
        body = r.json()
        # GraphQL convention: HTTP 200 with errors[] populated when permission denied.
        # data may be {"health": null} or null depending on Strawberry's behavior.
        assert body.get("errors"), body
        codes = [e.get("extensions", {}).get("code") for e in body["errors"]]
        # Could be UNAUTHENTICATED or FORBIDDEN depending on how empty scopes get classified.
        # Either is acceptable — the contract is "not 200 + data".
        assert any(c in ("UNAUTHENTICATED", "FORBIDDEN") for c in codes), codes


@pytest.mark.asyncio
async def test_graphiql_get_returns_html(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, _ = await _bootstrap(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/graphql")
        assert r.status_code == 200
        assert "html" in r.headers.get("content-type", "").lower()
        assert "graphiql" in r.text.lower() or "graphql" in r.text.lower()
