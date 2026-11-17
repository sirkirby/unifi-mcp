"""The access log names the route template, never the request's ids or query string."""

import logging
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.db.models import Base
from unifi_api.server import create_app

SECRET_ID = "7f3c2a9e-controller-id"
SECRET_CURSOR = "cursor-value-9b1d"


def _cfg(tmp_path: Path) -> ApiConfig:
    return ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
    )


def _access_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "unifi-api.access"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "route", "status"),
    [
        (f"/v1/controllers/{SECRET_ID}?cursor={SECRET_CURSOR}", "/v1/controllers/{cid}", 401),
        (f"/v1/health?cursor={SECRET_CURSOR}", "/v1/health", 200),
        (f"/v1/no-such-route/{SECRET_ID}?cursor={SECRET_CURSOR}", None, 404),
    ],
)
async def test_access_log_records_the_route_template(tmp_path: Path, monkeypatch, caplog, path, route, status) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app = create_app(_cfg(tmp_path))
    # Tables must exist so the auth middleware can write its denial audit row.
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    caplog.set_level(logging.INFO, logger="unifi-api.access")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(path, headers={"X-Request-ID": "req-1"})

    assert r.status_code == status
    (record,) = _access_records(caplog)
    assert (record.method, record.route, record.status) == ("GET", route, status)
    assert record.duration_ms >= 0
    logged = f"{record.getMessage()} {record.__dict__}"
    assert SECRET_ID not in logged and SECRET_CURSOR not in logged
