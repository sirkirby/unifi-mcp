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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("param", "value", "expect_row"),
    [
        # The seeded row is 2026-04-01T12:00:00Z.
        ("since", "2026-04-01T17:30:00+05:30", True),  # == 12:00Z, inclusive
        ("since", "2026-04-01T18:30:00+05:30", False),  # == 13:00Z
        ("since", "2026-04-01T12:00:00Z", True),
        ("since", "2026-04-01T12:00:00", True),  # offset-free stays UTC
        ("until", "2026-04-01T06:00:00-08:00", True),  # == 14:00Z
        ("until", "2026-04-01T03:00:00-08:00", False),  # == 11:00Z
        ("until", "2026-04-01T12:00:00Z", True),
        ("until", "2026-04-01T12:00:00", True),  # offset-free stays UTC
    ],
)
async def test_since_until_honour_utc_offset(
    tmp_path: Path, monkeypatch, param: str, value: str, expect_row: bool
) -> None:
    """A non-UTC offset in since/until must be converted to UTC before comparing with the UTC rows."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    await _seed_audit(
        app,
        [
            {
                "ts": datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc),
                "key_id_prefix": "p1",
                "controller": "c1",
                "target": "t1",
                "outcome": "ok",
            },
        ],
    )
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/audit", params={param: value}, headers=headers)
        assert r.status_code == 200, r.text
        assert [item["target"] for item in r.json()["items"]] == (["t1"] if expect_row else [])


@pytest.mark.asyncio
@pytest.mark.parametrize("param", ["since", "until"])
@pytest.mark.parametrize(
    "value",
    [
        "0001-01-01T00:00:00+05:00",  # UTC instant before datetime.min
        "9999-12-31T23:59:59-05:00",  # UTC instant after datetime.max
        "not-a-date",
    ],
)
async def test_unusable_bound_is_400(tmp_path: Path, monkeypatch, param: str, value: str) -> None:
    """A bound that does not parse, or whose UTC instant is out of range, is a 400, never a 500."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/v1/audit", params={param: value}, headers=headers)
        assert r.status_code == 400, r.text
        assert r.json()["detail"] == f"invalid '{param}' timestamp"
