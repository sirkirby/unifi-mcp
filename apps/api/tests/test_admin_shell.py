"""Phase 5B Task 14 — admin UI shell smoke."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.db.models import Base
from unifi_api.server import create_app


def _cfg(tmp_path: Path) -> ApiConfig:
    return ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
    )


async def _bootstrap_app(tmp_path: Path):
    app = create_app(_cfg(tmp_path))
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return app


@pytest.mark.asyncio
async def test_login_page_renders(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app = await _bootstrap_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/admin/login")
        assert r.status_code == 200
        assert "Admin API key" in r.text
        assert r.headers.get("cache-control") == "no-store"


@pytest.mark.asyncio
async def test_login_post_renders_bootstrap(tmp_path: Path, monkeypatch) -> None:
    """POST /admin/login with a key returns the page with the localStorage bootstrap script."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app = await _bootstrap_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/admin/login", data={"key": "unifi_live_TESTKEY12345"})
        assert r.status_code == 200
        # Inline bootstrap script + the validated key
        assert "localStorage.setItem('admin_bearer_key'" in r.text
        assert "unifi_live_TESTKEY12345" in r.text
        assert "/admin/" in r.text  # redirect target


@pytest.mark.asyncio
async def test_static_pico_css_served(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app = await _bootstrap_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/admin/static/pico.min.css")
        assert r.status_code == 200
        ctype = r.headers.get("content-type", "")
        assert "text/css" in ctype, f"expected text/css, got {ctype}"
        assert "Pico CSS" in r.text  # vendored file's banner comment
