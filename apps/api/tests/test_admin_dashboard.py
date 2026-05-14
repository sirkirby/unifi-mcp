"""Phase 5B PR2 Task 15 — admin dashboard + diagnostics fragment."""

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


@pytest.mark.asyncio
async def test_dashboard_page_renders(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, _ = await _bootstrap_app_with_admin_key(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/admin/")
        assert r.status_code == 200
        assert "Service health" in r.text
        # Page references the fragment endpoint and includes the layout shell
        assert "/admin/_diagnostics_html" in r.text
        assert "unifi-api" in r.text  # nav brand from _layout.html
        assert r.headers.get("cache-control") == "no-store"


@pytest.mark.asyncio
async def test_diagnostics_fragment_renders_with_counts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app_with_admin_key(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/admin/_diagnostics_html", headers=headers)
        assert r.status_code == 200
        # Server-rendered HTML, not JSON
        ctype = r.headers.get("content-type", "")
        assert "html" in ctype.lower()
        assert r.headers.get("cache-control") == "no-store"
        # Counts populated correctly: 1 admin key seeded by bootstrap, 0 controllers, 0 audit rows
        assert "1 keys" in r.text  # exact substring match against the template
        assert "0 controllers" in r.text
        assert "0 audit rows" in r.text
        # Section headers
        assert "Service" in r.text
        assert "Database" in r.text
        # Self-refresh is wired
        assert 'hx-trigger="load delay:30s"' in r.text
