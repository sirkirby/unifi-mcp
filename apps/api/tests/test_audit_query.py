"""GET /v1/audit — paginated audit log query route."""

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


async def _seed_audit(app, rows: list[dict]) -> None:
    sm = app.state.sessionmaker
    async with sm() as session:
        for r in rows:
            session.add(AuditLog(**r))
        await session.commit()


@pytest.mark.asyncio
async def test_default_returns_all_rows_newest_first(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    await _seed_audit(
        app,
        [
            {"ts": base, "key_id_prefix": "p1", "controller": "c1", "target": "t1", "outcome": "ok"},
            {
                "ts": base + timedelta(seconds=10),
                "key_id_prefix": "p1",
                "controller": "c1",
                "target": "t2",
                "outcome": "ok",
            },
            {
                "ts": base + timedelta(seconds=20),
                "key_id_prefix": "p1",
                "controller": "c1",
                "target": "t3",
                "outcome": "ok",
            },
        ],
    )
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/audit", headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["items"]) == 3
        targets = [item["target"] for item in data["items"]]
        assert targets == ["t3", "t2", "t1"]


@pytest.mark.asyncio
async def test_filter_by_outcome(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    await _seed_audit(
        app,
        [
            {"ts": base, "key_id_prefix": "p1", "controller": "c1", "target": "t1", "outcome": "ok"},
            {
                "ts": base + timedelta(seconds=10),
                "key_id_prefix": "p1",
                "controller": "c1",
                "target": "t2",
                "outcome": "ok",
            },
            {
                "ts": base + timedelta(seconds=20),
                "key_id_prefix": "p1",
                "controller": "c1",
                "target": "t3",
                "outcome": "error",
            },
        ],
    )
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/audit?outcome=error", headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["outcome"] == "error"
        assert data["items"][0]["target"] == "t3"


@pytest.mark.asyncio
async def test_pagination_with_cursor(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    await _seed_audit(
        app,
        [
            {
                "ts": base + timedelta(seconds=i * 10),
                "key_id_prefix": "p1",
                "controller": "c1",
                "target": f"t{i}",
                "outcome": "ok",
            }
            for i in range(5)
        ],
    )
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/audit?limit=2", headers=headers)
        assert r.status_code == 200, r.text
        page1 = r.json()
        assert len(page1["items"]) == 2
        assert page1["next_cursor"] is not None
        seen_ids = {item["id"] for item in page1["items"]}

        r = await c.get(
            f"/v1/audit?limit=2&cursor={page1['next_cursor']}",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        page2 = r.json()
        assert len(page2["items"]) == 2
        # No overlap between page 1 and page 2.
        for item in page2["items"]:
            assert item["id"] not in seen_ids


@pytest.mark.asyncio
async def test_admin_scope_required(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path, scopes="read")
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/audit", headers=headers)
        assert r.status_code == 403
