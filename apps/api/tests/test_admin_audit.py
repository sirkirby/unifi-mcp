"""Phase 5B PR3 Task 20 — admin /admin/audit page (filters + pagination + live-tail SSE + CSV)."""

import re
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


async def _bootstrap_app_with_admin_key(tmp_path: Path):
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
                scopes="admin",
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
async def test_audit_page_shell_renders_unauth(tmp_path: Path, monkeypatch) -> None:
    """Page shell is unauth + HTMX-driven; rows are NOT inlined."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, _ = await _bootstrap_app_with_admin_key(tmp_path)
    # Seed a row whose target should NOT appear in the page shell
    base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    await _seed_audit(
        app,
        [
            {
                "ts": base,
                "key_id_prefix": "p1",
                "controller": "c1",
                "target": "should-not-be-inlined",
                "outcome": "success",
            },
        ],
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/admin/audit")
        assert r.status_code == 200
        body = r.text
        assert "Audit log" in body
        assert 'hx-get="/admin/audit/_rows"' in body
        # Filters form is present
        assert 'id="audit-filters"' in body
        assert "should-not-be-inlined" not in body  # rows arrive via fragment
        assert r.headers.get("cache-control") == "no-store"


@pytest.mark.asyncio
async def test_audit_rows_fragment_returns_rows_and_pagination(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Seed 60 rows, fetch page 1 (50), then page 2 (10) via cursor."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app_with_admin_key(tmp_path)
    base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    await _seed_audit(
        app,
        [
            {
                "ts": base + timedelta(seconds=i * 10),
                "key_id_prefix": "p1",
                "controller": "c1",
                "target": f"t{i:02d}",
                "outcome": "success",
            }
            for i in range(60)
        ],
    )
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Page 1: 50 rows + Load more button with a cursor
        r = await c.get("/admin/audit/_rows?limit=50", headers=headers)
        assert r.status_code == 200, r.text
        body = r.text
        # Count <tr ... > occurrences that are real data rows (skip the load-more row).
        # The load-more row carries id="audit-load-more-row".
        data_rows = re.findall(r"<tr(?![^>]*id=\"audit-load-more-row\")[^>]*>", body)
        assert len(data_rows) == 50, f"expected 50 data rows, got {len(data_rows)}"
        assert "Load more" in body
        match = re.search(r'cursor=([^&"]+)', body)
        assert match is not None, "expected cursor query param in Load more URL"
        cursor = match.group(1)

        # Page 2: 10 remaining rows + no Load more
        r = await c.get(
            f"/admin/audit/_rows?limit=50&cursor={cursor}",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        body = r.text
        data_rows = re.findall(r"<tr(?![^>]*id=\"audit-load-more-row\")[^>]*>", body)
        assert len(data_rows) == 10, f"expected 10 data rows on page 2, got {len(data_rows)}"
        assert "Load more" not in body


@pytest.mark.asyncio
async def test_audit_rows_filter_by_outcome(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app_with_admin_key(tmp_path)
    base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    await _seed_audit(
        app,
        [
            {"ts": base, "key_id_prefix": "p1", "controller": "c1", "target": "target-success-1", "outcome": "success"},
            {
                "ts": base + timedelta(seconds=10),
                "key_id_prefix": "p1",
                "controller": "c1",
                "target": "target-success-2",
                "outcome": "success",
            },
            {
                "ts": base + timedelta(seconds=20),
                "key_id_prefix": "p1",
                "controller": "c1",
                "target": "target-error-1",
                "outcome": "error",
            },
        ],
    )
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/admin/audit/_rows?outcome=error", headers=headers)
        assert r.status_code == 200, r.text
        body = r.text
        assert "target-error-1" in body
        assert "target-success-1" not in body
        assert "target-success-2" not in body


@pytest.mark.asyncio
async def test_audit_export_csv_returns_csv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app_with_admin_key(tmp_path)
    base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    await _seed_audit(
        app,
        [
            {"ts": base, "key_id_prefix": "p1", "controller": "c1", "target": "csv-row-a", "outcome": "success"},
            {
                "ts": base + timedelta(seconds=10),
                "key_id_prefix": "p1",
                "controller": "c1",
                "target": "csv-row-b",
                "outcome": "success",
            },
            {
                "ts": base + timedelta(seconds=20),
                "key_id_prefix": "p1",
                "controller": "c1",
                "target": "csv-row-c",
                "outcome": "error",
            },
        ],
    )
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/admin/audit/export.csv", headers=headers)
        assert r.status_code == 200, r.text
        assert "text/csv" in r.headers["content-type"].lower()
        body = r.text
        lines = [ln for ln in body.splitlines() if ln.strip()]
        assert lines[0].startswith("id,ts,key_id_prefix,controller,target,outcome,error_kind,detail")
        # 3 data rows after the header
        assert len(lines) == 1 + 3
        assert "csv-row-a" in body
        assert "csv-row-b" in body
        assert "csv-row-c" in body


@pytest.mark.asyncio
async def test_audit_stream_returns_event_stream_content_type(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """SSE headers-only test — stub the infinite generator with a finite version."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")

    from unifi_api.routes.admin import audit as admin_audit_routes

    async def _finite_gen(filter_fn):
        yield b": keepalive\n\n"

    monkeypatch.setattr(
        admin_audit_routes,
        "_admin_audit_event_stream",
        _finite_gen,
    )

    app, key = await _bootstrap_app_with_admin_key(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        async with c.stream("GET", "/admin/audit/_stream", headers=headers) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
