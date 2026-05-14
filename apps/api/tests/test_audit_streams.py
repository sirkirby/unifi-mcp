"""POST /v1/audit/prune + GET /v1/streams/audit — Phase 5B PR1 Task 9."""

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from unifi_api.auth.api_key import generate_key, hash_key
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.db.models import ApiKey, AuditLog, Base
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
async def test_prune_endpoint_returns_counts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    sm = app.state.sessionmaker
    old_ts = datetime.now(timezone.utc) - timedelta(days=100)
    async with sm() as session:
        for i in range(2):
            session.add(
                AuditLog(
                    ts=old_ts,
                    key_id_prefix="p1",
                    controller="c1",
                    target=f"t{i}",
                    outcome="ok",
                )
            )
        await session.commit()

    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/audit/prune", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pruned"] == 2
        assert body["current_count"] == 0


@pytest.mark.asyncio
async def test_prune_requires_admin(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path, scopes="read")
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/audit/prune", headers=headers)
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_stream_returns_event_stream_content_type(tmp_path: Path, monkeypatch) -> None:
    """Verify SSE route headers without consuming the infinite body.

    The real route's generator runs forever, so we monkeypatch
    ``_audit_event_stream`` with a finite stub that yields one keepalive frame
    and returns. This still exercises route registration, the admin-scope
    dependency, and the SSE response media type / headers — the parts that
    matter for this PR.
    """
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")

    from unifi_api.routes import audit as audit_routes

    async def _finite_gen():
        yield b": keepalive\n\n"

    monkeypatch.setattr(audit_routes, "_audit_event_stream", _finite_gen)

    app, key = await _bootstrap_app(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        async with c.stream("GET", "/v1/streams/audit", headers=headers) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")


@pytest.mark.asyncio
async def test_stream_requires_admin(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path, scopes="read")
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/streams/audit", headers=headers)
        assert r.status_code == 403
