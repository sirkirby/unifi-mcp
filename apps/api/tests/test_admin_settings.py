"""Phase 5B PR3 Task 22 — /admin/settings page."""

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


@pytest.mark.asyncio
async def test_settings_form_renders_with_current_values(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app_with_admin_key(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    # Pre-seed a non-default value so we can confirm the form pre-fills it.
    await app.state.settings_service.set_int("audit.retention.max_age_days", 30)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/admin/settings/_form", headers=headers)
        assert r.status_code == 200
        # max_age_days = 30 (not the 90 default)
        assert 'name="audit_max_age_days" value="30"' in r.text
        # File logging level select with INFO option present
        assert "INFO" in r.text
        assert "DEBUG" in r.text
        assert r.headers.get("cache-control") == "no-store"


@pytest.mark.asyncio
async def test_settings_save_round_trips_through_settings_service(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app_with_admin_key(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/admin/settings/save",
            headers=headers,
            data={
                "audit_max_age_days": "45",
                "audit_max_rows": "500000",
                "audit_enabled": "on",
                "audit_prune_interval_hours": "12",
                "logs_enabled": "",  # disabled
                "logs_max_bytes": "5242880",
                "logs_backup_count": "3",
                "logs_level": "WARNING",
            },
        )
        assert r.status_code == 200
        assert "Saved" in r.text  # the saved indicator
        # Form re-renders with the new values
        assert 'value="45"' in r.text
        assert 'value="500000"' in r.text
    # Confirm via SettingsService directly
    svc = app.state.settings_service
    assert await svc.get_int("audit.retention.max_age_days") == 45
    assert await svc.get_int("audit.retention.max_rows") == 500_000
    assert await svc.get_bool("audit.retention.enabled") is True
    assert await svc.get_int("audit.retention.prune_interval_hours") == 12
    assert await svc.get_bool("logs.file.enabled") is False
    assert await svc.get_int("logs.file.max_bytes") == 5_242_880
    assert await svc.get_int("logs.file.backup_count") == 3
    assert await svc.get_str("logs.file.level") == "WARNING"


@pytest.mark.asyncio
async def test_settings_prune_button_returns_counts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app_with_admin_key(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    # Seed 3 audit rows with old timestamps so prune deletes them.
    sm = app.state.sessionmaker
    now = datetime.now(timezone.utc)
    async with sm() as session:
        for i in range(3):
            session.add(
                AuditLog(
                    ts=now - timedelta(days=200),
                    key_id_prefix="p",
                    controller=None,
                    target=f"t{i}",
                    outcome="ok",
                )
            )
        await session.commit()
    # Pin retention so the prune actually removes rows.
    await app.state.settings_service.set_int("audit.retention.max_age_days", 30)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/admin/settings/_prune", headers=headers)
        assert r.status_code == 200
        # The fragment renders pruned + current_count
        assert "Pruned" in r.text
        assert "3" in r.text  # 3 rows removed
        assert "0" in r.text  # current_count = 0
