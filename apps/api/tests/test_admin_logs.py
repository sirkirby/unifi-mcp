"""Phase 5B PR3 Task 21 — /admin/logs page."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from unifi_api.auth.api_key import generate_key, hash_key
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.db.models import ApiKey, Base
from unifi_api.server import create_app
from unifi_api.services.log_reader import LogReader


def _cfg(tmp_path: Path) -> ApiConfig:
    return ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
    )


async def _bootstrap_app_with_log_reader(tmp_path: Path):
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

    # Replace the default LogReader (/dev/null) with one pointing at a real file.
    log_path = tmp_path / "app.log"
    log_path.write_text("", encoding="utf-8")
    app.state.log_file_path = log_path
    app.state.log_reader = LogReader(log_path)
    return app, material.plaintext, log_path


def _write_log(path: Path, entries: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_logs_page_shell_renders_unauth(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, _, _ = await _bootstrap_app_with_log_reader(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/admin/logs")
        assert r.status_code == 200
        assert "Application logs" in r.text
        assert 'hx-get="/admin/logs/_rows"' in r.text
        assert r.headers.get("cache-control") == "no-store"


@pytest.mark.asyncio
async def test_logs_rows_filter_by_level(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, log_path = await _bootstrap_app_with_log_reader(tmp_path)
    _write_log(
        log_path,
        [
            {"ts": "2026-05-01T00:00:00.000Z", "level": "INFO", "logger": "a", "event": "hello"},
            {"ts": "2026-05-01T00:00:01.000Z", "level": "ERROR", "logger": "a", "event": "boom"},
            {"ts": "2026-05-01T00:00:02.000Z", "level": "INFO", "logger": "b", "event": "hi"},
        ],
    )
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/admin/logs/_rows?level=ERROR", headers=headers)
        assert r.status_code == 200
        assert "boom" in r.text
        assert "hello" not in r.text
        assert "hi" not in r.text


@pytest.mark.asyncio
async def test_logs_rows_filter_by_logger(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, log_path = await _bootstrap_app_with_log_reader(tmp_path)
    _write_log(
        log_path,
        [
            {"ts": "2026-05-01T00:00:00.000Z", "level": "INFO", "logger": "alpha", "event": "from-alpha"},
            {"ts": "2026-05-01T00:00:01.000Z", "level": "INFO", "logger": "beta", "event": "from-beta"},
            {"ts": "2026-05-01T00:00:02.000Z", "level": "INFO", "logger": "alpha", "event": "alpha-2"},
        ],
    )
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/admin/logs/_rows?logger=alpha", headers=headers)
        assert r.status_code == 200
        assert "from-alpha" in r.text
        assert "alpha-2" in r.text
        assert "from-beta" not in r.text


@pytest.mark.asyncio
async def test_logs_stream_returns_event_stream_content_type(tmp_path: Path, monkeypatch) -> None:
    """Headers-only check; the infinite generator is replaced by a finite one to avoid hanging."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, _ = await _bootstrap_app_with_log_reader(tmp_path)

    async def _finite_gen(*args, **kwargs):
        yield b": keepalive\n\n"

    monkeypatch.setattr("unifi_api.routes.admin.logs._admin_logs_event_stream", _finite_gen)

    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        async with c.stream("GET", "/admin/logs/_stream", headers=headers) as resp:
            assert resp.status_code == 200
            assert resp.headers.get("content-type", "").startswith("text/event-stream")
