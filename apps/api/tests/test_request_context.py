"""contextvars-based request ID threading test."""

import json
import logging as stdlib_logging
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.logging import configure_logging
from unifi_api.server import create_app


@pytest.mark.asyncio
async def test_request_id_in_log_records(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    cfg = ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=0, cors_origins=()),
        logging=LoggingConfig(level="INFO"),
        db=DbConfig(path=str(tmp_path / "state.db")),
    )
    configure_logging(level="INFO")
    app = create_app(cfg)

    @app.get("/_log_test")
    async def _t():
        stdlib_logging.getLogger("test").info("inside_request")
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/_log_test", headers={"X-Request-ID": "test-req-99"})

    assert r.status_code == 200
    assert r.headers["X-Request-ID"] == "test-req-99"
    captured = capsys.readouterr().err
    inside = [json.loads(line) for line in captured.splitlines() if '"inside_request"' in line]
    assert inside, "expected at least one log line emitted during request"
    assert any(rec.get("request_id") == "test-req-99" for rec in inside)
