"""Server factory + request id middleware tests."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.server import create_app


def _cfg(tmp_path: Path) -> ApiConfig:
    return ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
    )


@pytest.mark.asyncio
async def test_create_app_returns_fastapi_instance(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app = create_app(_cfg(tmp_path))
    assert isinstance(app, FastAPI)
    # state wired
    assert app.state.engine is not None
    assert app.state.sessionmaker is not None


@pytest.mark.asyncio
async def test_request_id_header_added(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app = create_app(_cfg(tmp_path))

    @app.get("/_test")
    async def _t():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/_test")
    assert r.status_code == 200
    assert r.headers.get("X-Request-ID")


@pytest.mark.asyncio
async def test_request_id_passthrough(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app = create_app(_cfg(tmp_path))

    @app.get("/_test")
    async def _t():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/_test", headers={"X-Request-ID": "client-req-42"})
    assert r.headers["X-Request-ID"] == "client-req-42"
