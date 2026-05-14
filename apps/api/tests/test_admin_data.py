"""Admin-scoped data endpoints: /v1/diagnostics, /v1/logs, /v1/settings."""

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
async def test_diagnostics_returns_shape(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/diagnostics", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body.keys()) >= {"service", "database", "capability_cache", "logs", "counts"}
        assert isinstance(body["service"]["version"], str)
        assert body["service"]["version"]
        assert body["counts"]["api_keys"] >= 1


@pytest.mark.asyncio
async def test_logs_returns_empty_when_no_log_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/logs", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["items"] == []
        assert body["file_size_bytes"] == 0


@pytest.mark.asyncio
async def test_settings_get_returns_dict(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    await app.state.settings_service.set_str("foo", "1")
    await app.state.settings_service.set_str("bar", "two")
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/settings", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["settings"]["foo"] == "1"
        assert body["settings"]["bar"] == "two"


@pytest.mark.asyncio
async def test_settings_put_round_trip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    payload = {"settings": {"theme.default": "dark", "audit.retention.max_age_days": "30"}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put("/v1/settings", headers=headers, json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["settings"]["theme.default"] == "dark"
        assert body["settings"]["audit.retention.max_age_days"] == "30"
    assert await app.state.settings_service.get_str("theme.default") == "dark"


@pytest.mark.asyncio
async def test_diagnostics_requires_admin(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path, scopes="read")
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/diagnostics", headers=headers)
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_settings_put_requires_admin(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path, scopes="read")
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put("/v1/settings", headers=headers, json={"settings": {"k": "v"}})
        assert r.status_code == 403
