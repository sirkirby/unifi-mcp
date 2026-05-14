"""Phase 5B lifespan integration: rotating file handler + audit pruner."""

import asyncio
from pathlib import Path

import pytest
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.db.models import Base
from unifi_api.server import create_app


def _cfg(tmp_path: Path) -> ApiConfig:
    return ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
    )


@pytest.mark.asyncio
async def test_lifespan_wires_file_logging_and_pruner(tmp_path: Path, monkeypatch) -> None:
    """Lifespan startup attaches the rotating file handler and starts the pruner task."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app = create_app(_cfg(tmp_path))

    # Materialize tables (lifespan doesn't run migrations — schema must exist).
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed a settings row pinning the log file under tmp_path so we can verify it gets attached.
    log_target = tmp_path / "state" / "phase5b.log"
    svc = app.state.settings_service
    await svc.set_str("logs.file.enabled", "true")
    await svc.set_str("logs.file.path", str(log_target))
    # Quick prune interval so the loop doesn't dominate tests; we don't wait for it to fire.
    await svc.set_int("audit.retention.prune_interval_hours", 1)

    # Use FastAPI's lifespan_context — the same async cm used at runtime.
    async with app.router.lifespan_context(app):
        # Inside lifespan startup window:
        assert app.state.log_file_path == log_target, (
            f"expected log_file_path={log_target}, got {app.state.log_file_path}"
        )
        # log_reader rebound to the real file
        assert app.state.log_reader._path == log_target  # noqa: SLF001
        # background pruner task scheduled
        task = app.state._audit_pruner_task
        assert isinstance(task, asyncio.Task)
        assert not task.done()
        # settings_service reachable (already wired pre-lifespan)
        assert app.state.settings_service is svc

    # After lifespan shutdown, the pruner task should be cancelled / done.
    assert task.done()
